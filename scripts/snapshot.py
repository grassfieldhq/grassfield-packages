#!/usr/bin/env python3
"""A channel's snapshots and pointer in the format of the one serialized publisher (grassfield ADR-0033 h.2, ADR-0037 g;
Grassfield Store step 1's tools/publish.py, grassfield-packages PR #2): `pointer` is {"snapshot": "<id>"}, each snapshot
holds `manifest.json` (every file with its SHA-256, the release, the catalog's serial, the previous snapshot), and its id
is the UTC time and the manifest's hash. For this repository's test trees (build-channel.sh, rollback.sh) and their
readers (check-tree.sh, view.sh); once PR #2 is merged, tools/publish.py makes these snapshots and this script keeps
only `current`.

  snapshot.py current DIR                            the current snapshot's id ("" when none)
  snapshot.py write DIR --release VERSION --source SRC [--expect ID]
        a new snapshot of DIR (<channel>/x86_64) from the current one: grassfield.db, grassfield.files and
        grassfield-notes.json with their .sig from SRC, every other file of the current snapshot kept (the catalog);
        --expect: the pointer must still name ID (compare and swap); prints the new id
Standard library only. Exit 0, 1 refused, 2 usage.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time

FROM_RELEASE = ("grassfield.db", "grassfield.files", "grassfield-notes.json")
ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
PACKAGE = re.compile(r"^grassfield-[a-z0-9@._+-]+\.pkg\.tar\.zst(\.sig)?$")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def current(base):
    try:
        with open(os.path.join(base, "pointer"), "rb") as f:
            snap = json.loads(f.read())["snapshot"]
    except FileNotFoundError:
        return None
    if not isinstance(snap, str) or not ID.match(snap):
        raise ValueError(f"{base}/pointer does not name a snapshot")
    return snap


def write(base, release, source, expect):
    cur = current(base)
    if expect is not None and cur != (expect or None):
        raise ValueError(f"the pointer moved: {cur}, not {expect}")
    old = {"release": None, "catalogSerial": None, "files": {}}
    if cur:
        with open(os.path.join(base, "snap", cur, "manifest.json"), "rb") as f:
            old = json.loads(f.read())
    files = {n: os.path.join(base, "snap", cur, n) for n in old["files"]}
    for n in FROM_RELEASE:
        files[n], files[n + ".sig"] = os.path.join(source, n), os.path.join(source, n + ".sig")
    packages = {f for f in os.listdir(base) if PACKAGE.match(f)}
    manifest = {"version": 1, "release": release, "catalogSerial": old.get("catalogSerial"),
                "catalogContent": old.get("catalogContent"), "previous": cur,
                "files": {n: sha256(p) for n, p in sorted(files.items())},
                "packages": sorted(set(old.get("packages", [])) | packages), "icons": old.get("icons", []),
                "created": int(time.time())}
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    snap = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(manifest["created"])) + "-" + hashlib.sha256(body).hexdigest()[:12]
    tmp = tempfile.mkdtemp(dir=os.path.join(base, "snap"), prefix=".tmp-")
    for n, p in files.items():
        shutil.copyfile(p, os.path.join(tmp, n))
    with open(os.path.join(tmp, "manifest.json"), "wb") as f:
        f.write(body)
    for n in os.listdir(tmp):
        os.chmod(os.path.join(tmp, n), 0o644)
    os.chmod(tmp, 0o755)
    os.rename(tmp, os.path.join(base, "snap", snap))
    fd, ptmp = tempfile.mkstemp(dir=base, prefix=".pointer-")
    with os.fdopen(fd, "wb") as f:
        f.write(json.dumps({"snapshot": snap}).encode() + b"\n")
    os.chmod(ptmp, 0o644)
    if expect is not None and current(base) != (expect or None):
        os.unlink(ptmp)
        raise ValueError("the pointer moved while the snapshot was written")
    os.replace(ptmp, os.path.join(base, "pointer"))
    return snap


def main(argv):
    try:
        if len(argv) == 2 and argv[0] == "current":
            print(current(argv[1]) or "")
            return 0
        if len(argv) >= 6 and argv[0] == "write" and argv[2] == "--release" and argv[4] == "--source":
            expect = argv[7] if len(argv) == 8 and argv[6] == "--expect" else None
            if len(argv) not in (6, 8) or (len(argv) == 8 and argv[6] != "--expect"):
                raise IndexError
            os.makedirs(os.path.join(argv[1], "snap"), exist_ok=True)
            print(write(argv[1], argv[3], argv[5], expect))
            return 0
        raise IndexError
    except IndexError:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as e:
        print(f"snapshot.py: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
