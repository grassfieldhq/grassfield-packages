#!/usr/bin/env python3
"""The one publisher of a channel (grassfield ADR-0033 h.2 as amended by ADR-0037 g). Written and disabled: CI never runs it
until the owner decides, after the M5 legal review (CLAUDE.md). Standard library, plus pacman's `vercmp` and `bsdtar`.

  publish.py --store DIR --channel stable [--arch x86_64] --releases DIR [--catalog DIR] [--keep-days 7]

One run publishes the latest state, never what started it (GitHub cancels a waiting run when a newer one queues, and each
tag is built once): the newest release built and signed for the channel (--releases holds one folder per version, as each
tag's build left it) and the catalog built from main's head (--catalog). It
  1. reads the pointer and the current snapshot's manifest;
  2. builds the new snapshot from it: the newest release when it is newer than the snapshot's, the catalog when its serial
     is higher, the rest kept; nothing new, nothing written;
  3. refuses to go backwards: a grassfield.db naming an older version of a package than the current one, an older release
     or a lower serial are never published (a rollback is a new release, ADR-0033 h.2);
  4. uploads the files with immutable names (packages, icons) once, then the snapshot, then writes the pointer only if it
     still names the snapshot step 1 read (compare-and-swap); otherwise it discards its snapshot and starts again.
Storage: `LocalStore`, a directory laid out as the bucket will be (ADR-0033 h: <channel>/<arch>/, snap/<id>/, pointer).
The bucket's own backend waits for the host (ADR-0033 O8); its conditional write is NOT VERIFIED.
Exit codes: 0 published or nothing new, 1 refused (going backwards, a changed immutable file), 2 usage or environment,
3 the pointer kept moving.
"""
import argparse
import contextlib
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

SNAPSHOT_FILES = ("grassfield.db", "grassfield.files", "grassfield-notes.json")
CATALOG_FILE = "grassfield-catalog.v1.json"
PACKAGE_FILE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*\.pkg\.tar\.(zst|xz|gz)(\.sig)?$")
ICON_FILE = re.compile(r"^[0-9a-f]{64}\.png$")
VERSION_DIR = re.compile(r"^[A-Za-z0-9._+:~-]{1,64}$")
ATTEMPTS = 5


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


def catalog_serial(folder):
    with open(os.path.join(folder, CATALOG_FILE), "rb") as f:
        return json.loads(f.read())["serial"]


def plan(store, current, releases, catalog):
    """What the new snapshot holds, from the current one: (files {name: path}, packages, icons, manifest) or None."""
    old = store.manifest(current) if current else {"release": None, "catalogSerial": None, "files": {}}
    files = {name: store.snapshot_path(current, name) for name in old["files"]}
    manifest = {"version": 1, "release": old["release"], "catalogSerial": old["catalogSerial"], "previous": current}
    packages, icons, changed = [], [], []

    version, folder = newest_release(releases)
    if version is not None:
        order = 1 if old["release"] is None else vercmp(version, old["release"])
        if order > 0:
            if old["release"] is not None:
                new_db, old_db = db_versions(os.path.join(folder, "grassfield.db")), db_versions(files["grassfield.db"])
                for name, was in old_db.items():
                    if name in new_db and vercmp(new_db[name], was) < 0:
                        raise Refused(f"release {version}: grassfield.db has {name} {new_db[name]}, older than the "
                                      f"published {was} (a rollback is a new release with a higher pkgrel)")
            for name in SNAPSHOT_FILES:
                files[name], files[name + ".sig"] = os.path.join(folder, name), os.path.join(folder, name + ".sig")
            packages = sorted(f for f in os.listdir(folder) if PACKAGE_FILE.match(f))
            packages = [(f, os.path.join(folder, f)) for f in packages]
            manifest["release"] = version
            changed.append(f"release {version}")
        elif order < 0:
            print(f"publish: the newest build ({version}) is older than the published release ({old['release']}): kept")

    if catalog:
        serial = catalog_serial(catalog)
        was = old["catalogSerial"]
        if was is None or serial > was:
            files[CATALOG_FILE] = os.path.join(catalog, CATALOG_FILE)
            files[CATALOG_FILE + ".sig"] = os.path.join(catalog, CATALOG_FILE + ".sig")
            icon_dir = os.path.join(catalog, "catalog")
            icons = [(f, os.path.join(icon_dir, f)) for f in sorted(os.listdir(icon_dir)) if ICON_FILE.match(f)] \
                if os.path.isdir(icon_dir) else []
            manifest["catalogSerial"] = serial
            changed.append(f"catalog {serial}")
        elif serial < was:
            print(f"publish: catalog serial {serial} is lower than the published {was}: kept")

    if not changed:
        return None
    if manifest["release"] is None:
        raise Refused("no release is built for this channel yet: a snapshot without grassfield.db fails every client")
    manifest["files"] = {name: sha256_file(path) for name, path in sorted(files.items())}
    manifest["packages"] = sorted(set(old.get("packages", [])) | {f for f, _ in packages})
    manifest["icons"] = sorted(set(old.get("icons", [])) | {f for f, _ in icons})
    return files, packages, icons, manifest, changed


def publish(store, releases, catalog, now=None):
    """One run. Returns the new snapshot id, or None when nothing was new."""
    with store.run_lock():
        for _ in range(ATTEMPTS):
            current, tag = store.read_pointer()
            planned = plan(store, current, releases, catalog)
            if planned is None:
                print(f"publish: nothing new (snapshot {current})")
                return None
            files, packages, icons, manifest, changed = planned
            for name, path in packages:
                store.put_immutable(name, path)
            for name, path in icons:
                store.put_immutable(os.path.join("catalog", name), path)
            manifest["created"] = int(now if now is not None else time.time())
            body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            snapshot = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(manifest["created"])) + "-" + \
                hashlib.sha256(body).hexdigest()[:12]
            with tempfile.TemporaryDirectory() as tmp:
                with open(os.path.join(tmp, "manifest.json"), "wb") as f:
                    f.write(body + b"\n")
                store.put_snapshot(snapshot, dict(files, **{"manifest.json": os.path.join(tmp, "manifest.json")}))
            if store.write_pointer_if(tag, snapshot):
                print(f"publish: snapshot {snapshot} ({', '.join(changed)}), was {current}")
                return snapshot
            store.drop_snapshot(snapshot)
            print("publish: the pointer moved while this run built its snapshot: starting again from it")
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
    ap.add_argument("--store", required=True, help="the local store (the bucket's backend waits for the host)")
    ap.add_argument("--channel", required=True, choices=("stable", "beta"))
    ap.add_argument("--arch", default="x86_64", choices=("x86_64",))
    ap.add_argument("--releases", help="one folder per built version: grassfield.db, .files, the notes, packages, .sig")
    ap.add_argument("--catalog", help="the catalog built from main's head and signed for this channel")
    ap.add_argument("--keep-days", type=int, default=7)
    args = ap.parse_args(argv)
    for tool in ("vercmp", "bsdtar"):
        if shutil.which(tool) is None:
            print(f"publish: {tool} is missing (pacman, libarchive)", file=sys.stderr)
            return 2
    store = LocalStore(args.store, args.channel, args.arch)
    try:
        publish(store, args.releases, args.catalog)
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
