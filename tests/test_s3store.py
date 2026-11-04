"""tools/publish.py S3Store against a fake `aws` (a script over a directory), no network, no GnuPG, no container needed.

The fake answers the few `aws s3api` calls S3Store makes and records every object's Cache-Control and metadata, so the
test checks the headers the publisher sets (ADR-0033 h.5, the same as edge/worker.js) and the pointer rule.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import publish  # noqa: E402

FAKE_AWS = r'''#!/usr/bin/env python3
import datetime, json, os, shutil, sys
root = os.environ["FAKE_BUCKET"]
a = sys.argv[1:]
assert a[0] == "--endpoint-url" and a[2] == "s3api", a
op, rest = a[3], a[4:]
opt, pos = {}, []
i = 0
while i < len(rest):
    if rest[i].startswith("--"):
        opt[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        pos.append(rest[i]); i += 1
assert opt["bucket"] == "grassfield"
key = opt.get("key")
path = lambda k: os.path.join(root, "objects", k)
meta = lambda k: os.path.join(root, "meta", k.replace("/", "%"))
def miss():
    sys.stderr.write("An error occurred (404) when calling the %s operation: Not Found\n" % op); sys.exit(254)
if op == "head-object":
    if not os.path.isfile(path(key)): miss()
    print(open(meta(key)).read())
elif op == "get-object":
    if not os.path.isfile(path(key)): miss()
    shutil.copyfile(path(key), pos[0]); print("{}")
elif op == "put-object":
    os.makedirs(os.path.dirname(path(key)), exist_ok=True); os.makedirs(os.path.dirname(meta(key)), exist_ok=True)
    shutil.copyfile(opt["body"], path(key))
    m = dict(kv.split("=", 1) for kv in opt.get("metadata", "").split(",") if kv)
    open(meta(key), "w").write(json.dumps({"CacheControl": opt["cache-control"], "ContentType": opt["content-type"], "Metadata": m}))
    print("{}")
elif op == "delete-object":
    if os.path.isfile(path(key)): os.unlink(path(key)); os.unlink(meta(key))
elif op == "list-objects-v2":
    out = []
    for d, _, files in os.walk(os.path.join(root, "objects")):
        for f in files:
            k = os.path.relpath(os.path.join(d, f), os.path.join(root, "objects"))
            if k.startswith(opt["prefix"]):
                t = os.path.getmtime(os.path.join(d, f))
                out.append({"Key": k, "LastModified": datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()})
    print(json.dumps({"Contents": out}) if out else "null")
else:
    sys.stderr.write("unsupported " + op); sys.exit(2)
'''


class S3(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bucket = os.path.join(self.tmp, "bucket")
        os.makedirs(self.bucket)
        aws = os.path.join(self.tmp, "aws")
        with open(aws, "w") as f:
            f.write(FAKE_AWS)
        os.chmod(aws, 0o755)
        os.environ["FAKE_BUCKET"] = self.bucket
        self.store = publish.S3Store("grassfield", "https://example.invalid", "stable", "x86_64", aws=(sys.executable, aws))

    def src(self, name, data=b"x"):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def head(self, rel):
        with open(os.path.join(self.bucket, "meta", ("stable/x86_64/" + rel).replace("/", "%"))) as f:
            return json.load(f)

    def test_no_pointer_yet(self):
        self.assertEqual(self.store.read_pointer(), (None, None))

    def test_immutable_once_with_long_cache(self):
        p = self.src("a.pkg.tar.zst", b"one")
        digest = self.store.put_immutable("a.pkg.tar.zst", p)
        self.assertEqual(self.head("a.pkg.tar.zst")["CacheControl"], "public, max-age=31536000, immutable")
        self.assertEqual(self.head("a.pkg.tar.zst")["Metadata"], {"sha256": digest})
        self.assertEqual(self.store.put_immutable("a.pkg.tar.zst", p), digest)  # the same bytes again are fine
        with self.assertRaises(publish.Refused):
            self.store.put_immutable("a.pkg.tar.zst", self.src("b", b"two"))

    def test_snapshot_then_pointer_no_store(self):
        snap = "20261104T120000Z-0123456789ab"
        self.store.put_snapshot(snap, {"grassfield.db": self.src("db"), "manifest.json": self.src("m", b"{}")})
        self.assertEqual(self.head(f"snap/{snap}/grassfield.db")["CacheControl"], "public, max-age=31536000, immutable")
        self.assertTrue(self.store.write_pointer_if(None, snap))
        self.assertEqual(self.head("pointer")["CacheControl"], "no-store")
        current, tag = self.store.read_pointer()
        self.assertEqual(current, snap)
        self.assertEqual(self.store.manifest(snap), {})
        # a stale tag does not write; the pointer keeps its value
        self.assertFalse(self.store.write_pointer_if(None, "20261104T130000Z-ba9876543210"))
        self.assertEqual(self.store.read_pointer()[0], snap)
        self.assertTrue(self.store.write_pointer_if(tag, "20261104T130000Z-ba9876543210"))

    def test_snapshots_listed_and_dropped(self):
        for snap in ("20261104T120000Z-0123456789ab", "20261104T130000Z-ba9876543210"):
            self.store.put_snapshot(snap, {"manifest.json": self.src("m", b"{}")})
        listed = self.store.snapshots()
        self.assertEqual([s for s, _ in listed], ["20261104T120000Z-0123456789ab", "20261104T130000Z-ba9876543210"])
        self.assertLess(abs(listed[0][1] - datetime.datetime.now().timestamp()), 60)
        self.store.drop_snapshot("20261104T120000Z-0123456789ab")
        self.assertEqual([s for s, _ in self.store.snapshots()], ["20261104T130000Z-ba9876543210"])
        with self.assertRaises(FileNotFoundError):
            self.store.manifest("20261104T120000Z-0123456789ab")

    def test_other_errors_are_not_a_missing_key(self):
        broken = publish.S3Store("grassfield", "https://example.invalid", "stable", "x86_64", aws=("false",))
        with self.assertRaises(RuntimeError):
            broken.read_pointer()


if __name__ == "__main__":
    unittest.main()
