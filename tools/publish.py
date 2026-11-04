#!/usr/bin/env python3
"""The one publisher of a channel (grassfield ADR-0033 h.2 as amended by ADR-0037 g). Run by publish.yml in the
protected environment of its channel (owner decision of 2026-11-04). Standard library, plus pacman's `vercmp` and `bsdtar`
and, for the bucket, the `aws` command line.

  publish.py (--store DIR | --s3-bucket NAME --s3-endpoint URL) --channel stable [--arch x86_64] --releases DIR
             --keyring-dir DIR [--catalog DIR] [--keep-days 7]
  publish.py --store DIR --channel stable [--arch x86_64] --keyring-dir DIR --rollback-to SNAPSHOT

One run publishes the latest state, never what started it (GitHub cancels a waiting run when a newer one queues, and each
tag is built once): the newest release built and signed for the channel (--releases holds one folder per version, as each
tag's build left it) and the catalog built from main's head (--catalog). It
  1. reads the pointer and the current snapshot's manifest;
  2. builds the new snapshot from it: the newest release when it is newer than the snapshot's, the catalog when its content
     differs (serial and build time aside) and its serial is higher, the rest kept; nothing new, nothing written. Every
     file of the release (databases, notes, packages) must be signed by one key grassfield-trusted lists and
     grassfield-revoked does not, and the catalog must pass the Store's own checks for this channel (tools/catalog.py
     verify: that signature, the rules, the icons); only the icons it lists are uploaded;
  3. refuses to go backwards: a grassfield.db naming an older version of a package than the current one, an older release
     or a lower serial are never published, except ADR-0033 h.2's deliberate rollback (--rollback-to: a new snapshot with
     an older snapshot's databases and notes, the rest kept; scripts/rollback.sh withdraws the newer release builds
     first, so that the next run does not publish them again);
  4. uploads the files with immutable names (packages, icons) once, then the snapshot, then writes the pointer only if it
     still names the snapshot step 1 read (compare-and-swap); otherwise it discards its snapshot and starts again.
Storage: `LocalStore`, a directory laid out as the bucket (ADR-0033 h: <channel>/<arch>/, snap/<id>/, pointer), for the
tests; `S3Store`, the bucket itself through `aws s3api` (R2). The pointer's conditional write on R2 is NOT VERIFIED: the
workflow's concurrency group serializes the runs and the pointer is read again just before its write.
Exit codes: 0 published or nothing new, 1 refused (going backwards, a changed immutable file), 2 usage or environment,
3 the pointer kept moving.
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog as catalogtool  # noqa: E402  the Store's own checks of a catalog (tools/catalog.py verify)

SNAPSHOT_FILES = ("grassfield.db", "grassfield.files", "grassfield-notes.json")
CATALOG_FILE = "grassfield-catalog.v1.json"
PACKAGE_FILE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*\.pkg\.tar\.(zst|xz|gz)(\.sig)?$")
VERSION_DIR = re.compile(r"^[A-Za-z0-9._+:~-]{1,64}$")
ATTEMPTS = 5
SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


class Refused(Exception):
    """The run would publish something older than what is published, or change an immutable file."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def vercmp(a, b):
    out = subprocess.run(["vercmp", a, b], capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return int(out.stdout.strip())


def db_versions(path):
    """{package: version} from a pacman sync database (its desc files, read with bsdtar)."""
    out = subprocess.run(["bsdtar", "-xOf", path, "--include", "*/desc"], capture_output=True, check=True,
                         stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    versions, lines = {}, out.split("\n")
    name = None
    for i, line in enumerate(lines):
        if line == "%NAME%" and i + 1 < len(lines):
            name = lines[i + 1]
        elif line == "%VERSION%" and i + 1 < len(lines) and name:
            versions[name] = lines[i + 1]
            name = None
    return versions


class LocalStore:
    """A directory laid out as the bucket: <channel>/<arch>/{<package files>, catalog/<sha256>.png, snap/<id>/, pointer}."""

    def __init__(self, root, channel, arch):
        self.channel = channel
        self.base = os.path.join(root, channel, arch)
        os.makedirs(os.path.join(self.base, "snap"), exist_ok=True)

    @contextlib.contextmanager
    def run_lock(self):
        # CI serializes with one concurrency group per channel; this lock does the same for a local store.
        with open(os.path.join(self.base, ".publish.lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def read_pointer(self):
        """(snapshot id or None, tag): the tag is what the conditional write compares."""
        path = os.path.join(self.base, "pointer")
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return None, None
        return json.loads(raw)["snapshot"], hashlib.sha256(raw).hexdigest()

    def write_pointer_if(self, expected_tag, snapshot):
        """Writes the pointer only if its tag is still expected_tag (None: no pointer yet). True when written."""
        with open(os.path.join(self.base, ".pointer.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.read_pointer()[1] != expected_tag:
                return False
            self._write(os.path.join(self.base, "pointer"), json.dumps({"snapshot": snapshot}).encode() + b"\n")
            return True

    def manifest(self, snapshot):
        with open(os.path.join(self.base, "snap", snapshot, "manifest.json"), "rb") as f:
            return json.loads(f.read())

    def snapshot_path(self, snapshot, name):
        return os.path.join(self.base, "snap", snapshot, name)

    def put_immutable(self, rel, source):
        """Uploads a file whose name never changes content: once; the same bytes again are fine, others are refused."""
        dest = os.path.join(self.base, rel)
        digest = sha256_file(source)
        if os.path.exists(dest):
            if sha256_file(dest) != digest:
                raise Refused(f"{rel} is already published with other content (immutable names, ADR-0033 g)")
            return digest
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(source, "rb") as f:
            self._write(dest, f.read())
        return digest

    def put_snapshot(self, snapshot, files):
        """files: {name: source path}. The snapshot is complete before anything points to it."""
        tmp = tempfile.mkdtemp(dir=os.path.join(self.base, "snap"), prefix=".tmp-")
        for name, source in files.items():
            shutil.copyfile(source, os.path.join(tmp, name))
        os.rename(tmp, os.path.join(self.base, "snap", snapshot))

    def drop_snapshot(self, snapshot):
        shutil.rmtree(os.path.join(self.base, "snap", snapshot), ignore_errors=True)

    def snapshots(self):
        snap = os.path.join(self.base, "snap")
        return [(s, os.path.getmtime(os.path.join(snap, s))) for s in os.listdir(snap) if not s.startswith(".")]

    @staticmethod
    def _write(path, data):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


NO_STORE = "no-store"
IMMUTABLE = "public, max-age=31536000, immutable"  # the same headers as edge/worker.js (ADR-0033 h.5)


class S3Store:
    """The bucket itself (Cloudflare R2, S3 API), through the `aws` command line: same layout and same methods as
    LocalStore. Credentials come from the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY). Files are fetched into
    a private work folder when a method needs them as paths. Headers on upload (ADR-0033 h.5): `no-store` on the pointer,
    `public, max-age=31536000, immutable` on everything else this class writes (packages, signatures, icons, snapshots).
    No locking: the one concurrency group of the workflow serializes the runs; the pointer is read again just before its
    write (a conditional PutObject on R2 is NOT VERIFIED, so it is not used)."""

    def __init__(self, bucket, endpoint, channel, arch, aws=("aws",)):
        self.bucket, self.endpoint, self.channel, self.aws = bucket, endpoint, channel, tuple(aws)
        self.prefix = f"{channel}/{arch}/"
        self.work = tempfile.mkdtemp(prefix="publish-s3-")

    def _run(self, *args, check=True):
        cmd = [*self.aws, "--endpoint-url", self.endpoint, "s3api", *args, "--bucket", self.bucket]
        out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if check and out.returncode != 0:
            raise RuntimeError(f"aws s3api {args[0]} failed: {out.stderr.strip()[:300]}")
        return out

    @staticmethod
    def _missing(out):
        return out.returncode != 0 and ("(404)" in out.stderr or "Not Found" in out.stderr or "NoSuchKey" in out.stderr)

    def _head(self, key):
        out = self._run("head-object", "--key", key, "--output", "json", check=False)
        if out.returncode == 0:
            return json.loads(out.stdout or "{}")
        if self._missing(out):
            return None
        raise RuntimeError(f"aws s3api head-object {key} failed: {out.stderr.strip()[:300]}")

    def _get(self, key, path):
        """True when fetched, False when the key does not exist."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out = self._run("get-object", "--key", key, path, check=False)
        if out.returncode == 0:
            return True
        if self._missing(out):
            return False
        raise RuntimeError(f"aws s3api get-object {key} failed: {out.stderr.strip()[:300]}")

    def _put(self, key, path, cache, sha=None):
        args = ["put-object", "--key", key, "--body", path, "--cache-control", cache]
        if key.endswith(".json") or key.endswith("/pointer"):
            args += ["--content-type", "application/json"]
        else:
            args += ["--content-type", "application/octet-stream"]
        if sha:
            args += ["--metadata", f"sha256={sha}"]
        self._run(*args, "--output", "json")

    def _list(self, prefix):
        """[(key, LastModified epoch)] under prefix."""
        out = self._run("list-objects-v2", "--prefix", prefix, "--output", "json").stdout.strip()
        data = json.loads(out) if out and out != "null" else None
        return [(o["Key"], datetime.datetime.fromisoformat(o["LastModified"]).timestamp())
                for o in (data or {}).get("Contents", [])]

    @contextlib.contextmanager
    def run_lock(self):
        yield

    def read_pointer(self):
        path = os.path.join(self.work, "pointer")
        if not self._get(self.prefix + "pointer", path):
            return None, None
        with open(path, "rb") as f:
            raw = f.read()
        os.unlink(path)
        return json.loads(raw)["snapshot"], hashlib.sha256(raw).hexdigest()

    def write_pointer_if(self, expected_tag, snapshot):
        if self.read_pointer()[1] != expected_tag:
            return False
        path = os.path.join(self.work, "pointer.new")
        with open(path, "wb") as f:
            f.write(json.dumps({"snapshot": snapshot}).encode() + b"\n")
        self._put(self.prefix + "pointer", path, NO_STORE)
        os.unlink(path)
        return True

    def snapshot_path(self, snapshot, name):
        path = os.path.join(self.work, "snap", snapshot, name)
        if not os.path.exists(path) and not self._get(f"{self.prefix}snap/{snapshot}/{name}", path):
            raise FileNotFoundError(f"{snapshot}/{name}")
        return path

    def manifest(self, snapshot):
        with open(self.snapshot_path(snapshot, "manifest.json"), "rb") as f:
            return json.loads(f.read())

    def put_immutable(self, rel, source):
        key, digest = self.prefix + rel, sha256_file(source)
        head = self._head(key)
        if head is not None:
            stored = (head.get("Metadata") or {}).get("sha256")
            if stored is None:  # not written by this class: compare the bytes
                path = os.path.join(self.work, "compare")
                self._get(key, path)
                stored = sha256_file(path)
                os.unlink(path)
            if stored != digest:
                raise Refused(f"{rel} is already published with other content (immutable names, ADR-0033 g)")
            return digest
        self._put(key, source, IMMUTABLE, digest)
        return digest

    def put_snapshot(self, snapshot, files):
        """The files first, the manifest last: the snapshot is complete before anything points to it."""
        for name, source in sorted(files.items(), key=lambda kv: kv[0] == "manifest.json"):
            self._put(f"{self.prefix}snap/{snapshot}/{name}", source, IMMUTABLE)

    def drop_snapshot(self, snapshot):
        for key, _ in self._list(f"{self.prefix}snap/{snapshot}/"):
            self._run("delete-object", "--key", key)
        shutil.rmtree(os.path.join(self.work, "snap", snapshot), ignore_errors=True)

    def snapshots(self):
        found = {}
        for key, mtime in self._list(self.prefix + "snap/"):
            snap = key[len(self.prefix) + len("snap/"):].split("/", 1)[0]
            found[snap] = min(mtime, found.get(snap, mtime))
        return sorted(found.items())


def newest_release(releases):
    """(version, folder) of the newest complete release build, or (None, None)."""
    best = (None, None)
    for name in os.listdir(releases) if releases and os.path.isdir(releases) else []:
        folder = os.path.join(releases, name)
        if not VERSION_DIR.match(name) or not all(os.path.isfile(os.path.join(folder, f)) and
                                                  os.path.isfile(os.path.join(folder, f + ".sig"))
                                                  for f in SNAPSHOT_FILES):
            continue
        if best[0] is None or vercmp(name, best[0]) > 0:
            best = (name, folder)
    return best


def checked_catalog(folder, keyring_dir, channel):
    """(serial, content hash, icon file names) of a catalog that passes the Store's own checks for this channel: its
    signature by a trusted key, its rules, its icons. The content hash leaves out the serial and the build time, so a
    catalog rebuilt with nothing changed is nothing new."""
    p = catalogtool.Problems()
    catalogtool.verify(folder, keyring_dir, channel, 0, p)
    if p:
        raise Refused(f"the catalog does not pass the Store's checks for {channel}: {'; '.join(p.items[:3])}")
    with open(os.path.join(folder, CATALOG_FILE), "rb") as f:
        obj = json.loads(f.read())
    icons = sorted({a["icon"]["sha256"] + ".png" for a in obj["apps"] if isinstance(a.get("icon"), dict)})
    content = {k: v for k, v in obj.items() if k not in ("serial", "generated")}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return obj["serial"], digest, icons


def plan(store, current, releases, catalog, keyring_dir=None):
    """What the new snapshot holds, from the current one: (files {name: path}, packages, icons, manifest) or None."""
    old = store.manifest(current) if current else {"release": None, "catalogSerial": None, "files": {}}
    files = {name: store.snapshot_path(current, name) for name in old["files"]}
    manifest = {"version": 1, "release": old["release"], "catalogSerial": old["catalogSerial"],
                "catalogContent": old.get("catalogContent"), "previous": current}
    packages, icons, changed = [], [], []

    version, folder = newest_release(releases)
    if version is not None:
        order = 1 if old["release"] is None else vercmp(version, old["release"])
        if order > 0:
            packages = sorted(f for f in os.listdir(folder) if PACKAGE_FILE.match(f))
            # Every file the release brings, signed by a key the Store and pacman trust, before anything is read (bsdtar
            # never sees an unverified database) or uploaded.
            for name in list(SNAPSHOT_FILES) + [f for f in packages if not f.endswith(".sig")]:
                problem = catalogtool.signature_problem(os.path.join(folder, name), keyring_dir)
                if problem:
                    raise Refused(f"release {version}: {name}: {problem}")
            if old["release"] is not None:
                new_db, old_db = db_versions(os.path.join(folder, "grassfield.db")), db_versions(files["grassfield.db"])
                for name, was in old_db.items():
                    if name in new_db and vercmp(new_db[name], was) < 0:
                        raise Refused(f"release {version}: grassfield.db has {name} {new_db[name]}, older than the "
                                      f"published {was} (a rollback is a new release with a higher pkgrel, or "
                                      "ADR-0033 h.2's deliberate --rollback-to)")
            for name in SNAPSHOT_FILES:
                files[name], files[name + ".sig"] = os.path.join(folder, name), os.path.join(folder, name + ".sig")
            packages = [(f, os.path.join(folder, f)) for f in packages]
            manifest["release"] = version
            changed.append(f"release {version}")
        elif order < 0:
            print(f"publish: the newest build ({version}) is older than the published release ({old['release']}): kept")

    if catalog:
        serial, content, names = checked_catalog(catalog, keyring_dir, store.channel)
        was = old["catalogSerial"]
        if content == old.get("catalogContent"):
            pass  # the same catalog, rebuilt: nothing new
        elif was is None or serial > was:
            files[CATALOG_FILE] = os.path.join(catalog, CATALOG_FILE)
            files[CATALOG_FILE + ".sig"] = os.path.join(catalog, CATALOG_FILE + ".sig")
            icons = [(f, os.path.join(catalog, "catalog", f)) for f in names]  # only what the signed file lists
            manifest["catalogSerial"], manifest["catalogContent"] = serial, content
            changed.append(f"catalog {serial}")
        else:
            print(f"publish: a catalog with serial {serial}, not above the published {was}: kept")

    if not changed:
        return None
    if manifest["release"] is None:
        raise Refused("no release is built for this channel yet: a snapshot without grassfield.db fails every client")
    manifest["files"] = {name: sha256_file(path) for name, path in sorted(files.items())}
    manifest["packages"] = sorted(set(old.get("packages", [])) | {f for f, _ in packages})
    manifest["icons"] = sorted(set(old.get("icons", [])) | {f for f, _ in icons})
    return files, packages, icons, manifest, changed


def publish(store, releases, catalog, now=None, keyring_dir=None):
    """One run. Returns the new snapshot id, or None when nothing was new."""
    with store.run_lock():
        for _ in range(ATTEMPTS):
            current, tag = store.read_pointer()
            planned = plan(store, current, releases, catalog, keyring_dir)
            if planned is None:
                print(f"publish: nothing new (snapshot {current})")
                return None
            files, packages, icons, manifest, changed = planned
            for name, path in packages:
                store.put_immutable(name, path)
            for name, path in icons:
                store.put_immutable(os.path.join("catalog", name), path)
            snapshot = commit(store, tag, files, manifest, now)
            if snapshot:
                print(f"publish: snapshot {snapshot} ({', '.join(changed)}), was {current}")
                return snapshot
        raise RuntimeError(f"the pointer moved {ATTEMPTS} times in a row")


def commit(store, tag, files, manifest, now=None):
    """Uploads the complete snapshot, then writes the pointer only if its tag is still `tag`. The new id, or None when
    the pointer moved (the snapshot is dropped and the caller starts again from the current one)."""
    manifest["created"] = int(now if now is not None else time.time())
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    snapshot = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(manifest["created"])) + "-" + \
        hashlib.sha256(body).hexdigest()[:12]
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "manifest.json"), "wb") as f:
            f.write(body + b"\n")
        store.put_snapshot(snapshot, dict(files, **{"manifest.json": os.path.join(tmp, "manifest.json")}))
    if store.write_pointer_if(tag, snapshot):
        return snapshot
    store.drop_snapshot(snapshot)
    print("publish: the pointer moved while this run built its snapshot: starting again from it")
    return None


def rollback(store, target, now=None, keyring_dir=None):
    """ADR-0033 h.2's deliberate rollback, the one exception to "never backwards": a NEW snapshot with the databases and
    notes of an older snapshot of the channel (target) and every other file of the current one (the catalog); never the
    pointer moved back (R4: a client already on the newer snapshot would then fail every update). The files keep their
    signatures, so no key is needed. Clients that installed the newer release keep it (pacman does not downgrade).
    The caller withdraws the newer release builds first, so that a later run does not publish them again
    (scripts/rollback.sh). As a publication does, it checks the signatures of the databases and notes it reads or
    publishes against keyring_dir before bsdtar reads a database (a snapshot signed by a key revoked since is refused).
    Returns the new snapshot id."""
    if not isinstance(target, str) or not SNAPSHOT_ID.match(target):
        raise Refused(f"{target!r} is not a snapshot id")
    with store.run_lock():
        for _ in range(ATTEMPTS):
            current, tag = store.read_pointer()
            if current is None or target == current:
                raise Refused(f"{target} is not an older snapshot than the current one ({current})")
            try:
                old = store.manifest(target)
            except FileNotFoundError:
                raise Refused(f"no snapshot {target} in {store.channel}")
            cur = store.manifest(current)
            for snap in (target, current):
                for name in SNAPSHOT_FILES:
                    problem = catalogtool.signature_problem(store.snapshot_path(snap, name), keyring_dir)
                    if problem:
                        raise Refused(f"snapshot {snap}: {name}: {problem}")
            was = db_versions(store.snapshot_path(current, "grassfield.db")).get("grassfield-desktop")
            back = db_versions(store.snapshot_path(target, "grassfield.db")).get("grassfield-desktop")
            if not was or not back or vercmp(back, was) >= 0:
                raise Refused(f"{target} holds grassfield-desktop {back}, not older than the current {was}")
            files = {name: store.snapshot_path(current, name) for name in cur["files"]}
            for name in SNAPSHOT_FILES:
                files[name], files[name + ".sig"] = (store.snapshot_path(target, name),
                                                      store.snapshot_path(target, name + ".sig"))
            manifest = dict(cur, release=old["release"], previous=current, rollbackOf=target,
                            files={name: sha256_file(path) for name, path in sorted(files.items())})
            snapshot = commit(store, tag, files, manifest, now)
            if snapshot:
                print(f"publish: snapshot {snapshot} (rollback to {target}: grassfield-desktop {back}, was {was}), "
                      f"was {current}")
                return snapshot
        raise RuntimeError(f"the pointer moved {ATTEMPTS} times in a row")


def prune(store, keep_days, now=None):
    """Snapshots are kept 7 days (ADR-0033 h.2); the current one always."""
    current, _ = store.read_pointer()
    limit = (now if now is not None else time.time()) - keep_days * 86400
    for snapshot, mtime in store.snapshots():
        if snapshot != current and mtime < limit:
            store.drop_snapshot(snapshot)


def main(argv):
    ap = argparse.ArgumentParser(prog="publish.py", description="the serialized publisher of a channel")
    ap.add_argument("--store", help="a local store (tests, build trees)")
    ap.add_argument("--s3-bucket", help="the bucket (credentials in AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
    ap.add_argument("--s3-endpoint", help="the bucket's S3 endpoint (https://<account>.r2.cloudflarestorage.com)")
    ap.add_argument("--channel", required=True, choices=("stable", "beta"))
    ap.add_argument("--arch", default="x86_64", choices=("x86_64",))
    ap.add_argument("--releases", help="one folder per built version: grassfield.db, .files, the notes, packages, .sig")
    ap.add_argument("--catalog", help="the catalog built from main's head and signed for this channel")
    ap.add_argument("--keyring-dir", required=True,
                    help="the keyring folder the Store and pacman trust (grassfield.gpg, grassfield-trusted, "
                         "grassfield-revoked): every release file, the catalog and a rollback's files are checked "
                         "against it")
    ap.add_argument("--rollback-to", metavar="SNAPSHOT",
                    help="ADR-0033 h.2's deliberate rollback to an older snapshot (scripts/rollback.sh withdraws the newer "
                         "release builds first); not with --releases or --catalog")
    ap.add_argument("--keep-days", type=int, default=7)
    args = ap.parse_args(argv)
    for tool in ("vercmp", "bsdtar"):
        if shutil.which(tool) is None:
            print(f"publish: {tool} is missing (pacman, libarchive)", file=sys.stderr)
            return 2
    if args.rollback_to and (args.releases or args.catalog):
        print("publish: --rollback-to publishes an older snapshot again, nothing else", file=sys.stderr)
        return 2
    if bool(args.store) == bool(args.s3_bucket) or bool(args.s3_bucket) != bool(args.s3_endpoint):
        print("publish: give --store, or --s3-bucket with --s3-endpoint", file=sys.stderr)
        return 2
    if args.store:
        store = LocalStore(args.store, args.channel, args.arch)
    else:
        if shutil.which("aws") is None:
            print("publish: aws is missing (aws-cli-v2)", file=sys.stderr)
            return 2
        store = S3Store(args.s3_bucket, args.s3_endpoint, args.channel, args.arch)
    try:
        if args.rollback_to:
            rollback(store, args.rollback_to, keyring_dir=args.keyring_dir)
        else:
            publish(store, args.releases, args.catalog, keyring_dir=args.keyring_dir)
    except Refused as e:
        print(f"publish: refused: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"publish: {e}", file=sys.stderr)
        return 3
    prune(store, args.keep_days)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
