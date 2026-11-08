"""tools/watch_toolkit.py: the daily comparison of the published Grassfield with Omarchy's stable and rc channels.

Offline: every URL is answered from memory by a fake. Needs the `zstd` command line (the packages and Omarchy's database are
zstd streams); skipped without it.
"""
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import watch_toolkit as w  # noqa: E402

HAVE_ZSTD = shutil.which("zstd") is not None
BASE = "https://packages.example.org"


def tar_bytes(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def zstd(data):
    return subprocess.run(["zstd", "-c", "-q"], input=data, capture_output=True, check=True).stdout


def desc(name, version, filename=None, sha=""):
    return f"%FILENAME%\n{filename or name + '-' + version + '-x86_64.pkg.tar.zst'}\n\n%NAME%\n{name}\n\n%VERSION%\n{version}\n\n%SHA256SUM%\n{sha}\n"


def db(entries, compress):
    files = {f"{n}-{v}/desc": desc(n, v, f, s) for n, v, f, s in entries}
    raw = tar_bytes(files)
    return zstd(raw) if compress == "zst" else gzip.compress(raw)


def version_h(commit="efb50993780079460b0cbed1363e2166a2de1d9f", aq="0.15.1", hu="0.14.2", hg="0.5.0", hc="0.1.0", hlg="0.6.3"):
    return "\n".join([f'#define GIT_COMMIT_HASH    "{commit}"', f'#define AQUAMARINE_VERSION "{aq}"', f'#define HYPRUTILS_VERSION "{hu}"',
                      f'#define HYPRGRAPHICS_VERSION "{hg}"', f'#define HYPRCURSOR_VERSION "{hc}"', f'#define HYPRLANG_VERSION "{hlg}"'])


ABI = "efb50993780079460b0cbed1363e2166a2de1d9f_aq_0.15_hu_0.14_hg_0.5_hc_0.1_hlg_0.6"
RECORD = "qt6-base 6.12.0-3\nquickshell 0.3.2.r7.g2b4501a-1\nhyprland 0.56.2-4\naquamarine 0.15.1-1\nkcoreaddons 6.31.0-1\n"


class Fake:
    """Answers the URLs the tool asks; every request is kept."""

    def __init__(self):
        self.files = {}
        self.asked = []

    def get(self, url, limit):
        self.asked.append(url)
        return self.files.get(url)


def world(published="1.0.0rc7-1", record=RECORD, abi=ABI, stable=None, rc=None, channels=("beta",), hypr_h=None):
    """A fake network: Grassfield's published channels, Omarchy's stable and rc."""
    f = Fake()
    stable = stable or {"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}
    rc = rc or stable
    for channel in channels:
        desktop = zstd(tar_bytes({"usr/share/grassfield/BUILD-DEPS": record}))
        compositor = zstd(tar_bytes({"usr/lib/grassfield/grassfield-compositor.abi": abi + "\nsource " + published + "\n"} if abi else {"usr/lib/x": "x"}))
        entries = []
        for name, blob in (("grassfield-desktop", desktop), ("grassfield-compositor", compositor)):
            filename = f"{name}-{published}-x86_64.pkg.tar.zst"
            f.files[f"{BASE}/{channel}/x86_64/{filename}"] = blob
            entries.append((name, published, filename, hashlib.sha256(blob).hexdigest()))
        f.files[f"{BASE}/{channel}/x86_64/grassfield.db"] = db(entries, "gz")
    for name, ch in (("stable", stable), ("rc", rc)):
        f.files[f"{w.OMARCHY}/{name}/x86_64/omarchy.db"] = db([("quickshell", ch["quickshell"], None, "")], "zst")
        hyprland = zstd(tar_bytes({"usr/include/hyprland/src/version.h": (hypr_h or {}).get(name, version_h())}))
        filename = f"hyprland-{ch['hyprland']}-x86_64.pkg.tar.zst"
        f.files[f"https://{name}-mirror.omarchy.org/extra/os/x86_64/{filename}"] = hyprland
        f.files[f"https://{name}-mirror.omarchy.org/extra/os/x86_64/extra.db"] = db(
            [("qt6-base", ch["qt6-base"], None, ""), ("hyprland", ch["hyprland"], filename, hashlib.sha256(hyprland).hexdigest())], "gz")
    return f


class Rules(unittest.TestCase):
    """The same cases as grassfield's tests/shell/update_hold.sh (the bounds) and compositor/abi-stamp.cmake (the stamp)."""

    def test_boundsOfARecord(self):
        b = w.bounds_of(w.parse_record(RECORD))
        self.assertEqual(b, {"quickshell": "0.3.2.r7.g2b4501a", "qt6-base": ["6.12", "6.13"]})
        self.assertEqual(w.bounds_of({"qt6-base": "6.9.3-2", "quickshell": "0.3.1-1"}), {"quickshell": "0.3.1", "qt6-base": ["6.9", "6.10"]})
        self.assertEqual(w.bounds_of({"qt6-base": "1:6.12.0-1", "quickshell": "0.3.2-1"}), {"quickshell": "0.3.2", "qt6-base": ["1:6.12", "1:6.13"]})

    def test_aRecordThatCannotBeBoundedIsAnError(self):
        for bad in ({"qt6-base": "6.12.0-1"}, {"quickshell": "0.3.2-1"}, {}, {"qt6-base": "six", "quickshell": "0.3.2-1"}):
            with self.assertRaises(w.WatchError):
                w.bounds_of(bad)
        for text in ("qt6-base 6.12.0-1 extra\n", "Qt6-base 6.12.0-1\n", "qt6-base\n", "qt6-base 6.12>=1\n"):
            with self.assertRaises(w.WatchError):
                w.parse_record(text)

    def test_abiStamp(self):
        self.assertEqual(w.abi_of(version_h()), ABI)
        self.assertEqual(w.abi_of(version_h(aq="0.16.0")), "efb50993780079460b0cbed1363e2166a2de1d9f_aq_0.16_hu_0.14_hg_0.5_hc_0.1_hlg_0.6")
        with self.assertRaises(w.WatchError):
            w.abi_of(version_h().replace("HYPRLANG_VERSION", "X"))
        with self.assertRaises(w.WatchError):
            w.abi_of(version_h(commit=""))

    def test_tagOfAPublishedVersion(self):
        self.assertEqual(w.tag_of("1.0.0rc7-1"), ("v1.0.0-rc7", 1))
        self.assertEqual(w.tag_of("1.0.0-3"), ("v1.0.0", 3))
        self.assertEqual(w.tag_of("1.2.0beta2-12"), ("v1.2.0-beta2", 12))
        for bad in ("1.0.0", "1.0-1", "1.0.0rc-1", "1.0.0rc7-0", "../1.0.0-1", "1.0.0rc7-1\n"):
            with self.assertRaises(w.WatchError):
                w.tag_of(bad)

    def test_redirectsStayOnKnownHostsOverHttps(self):
        h = w.SameHosts({"packages.example.org"})
        req = w.urllib.request.Request("https://packages.example.org/x")
        for bad in ("http://packages.example.org/y", "https://evil.example.net/y", "file:///etc/passwd", "https://packages.example.org.evil.net/y"):
            with self.assertRaises(w.WatchError):
                h.redirect_request(req, None, 302, "Found", {}, bad)
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://packages.example.org/snap/1/x"))
        with self.assertRaises(w.WatchError):
            w.Http(hosts={"packages.example.org"}).get("https://other.example.net/x", 10)

    def test_whatReachesAnIssueIsPlain(self):
        self.assertTrue(w.ABI_RE.fullmatch(ABI))
        for bad in ("@owner", "[x](http://y)", "efb5_aq_0.15", "x" * 40 + "_aq_0.15"):
            self.assertFalse(w.ABI_RE.fullmatch(bad))
        with self.assertRaises(w.WatchError):
            w.abi_of(version_h(commit="@everyone look"))

    def test_httpRefusesAnythingButHttps(self):
        with self.assertRaises(w.WatchError):
            w.Http().get("http://example.org/x", 10)
        with self.assertRaises(w.WatchError):
            w.Http().get("file:///etc/passwd", 10)


@unittest.skipUnless(HAVE_ZSTD, "needs the zstd command line")
class Watch(unittest.TestCase):
    def run_watch(self, f, channels=("beta", "stable")):
        return w.watch(f, BASE, list(channels))

    def test_nothingMovedNothingToDo(self):
        r = self.run_watch(world())
        self.assertEqual((r["rebuild"], r["issue"]), ([], None))
        self.assertIn("stable: nothing is published", r["notes"][0])
        self.assertEqual(r["published"]["beta"]["bounds"], {"quickshell": "0.3.2.r7.g2b4501a", "qt6-base": ["6.12", "6.13"]})
        self.assertEqual(r["published"]["beta"]["abi"], ABI)

    def test_theSameHyprlandPackageIsNotDownloaded(self):
        f = world()
        self.run_watch(f)
        self.assertFalse([u for u in f.asked if "hyprland-" in u and u.endswith(".zst")])

    def test_stableMovesQuickshellARebuildWithTheNextPkgrel(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.3-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}))
        self.assertEqual(len(r["rebuild"]), 1)
        self.assertEqual((r["rebuild"][0]["ref"], r["rebuild"][0]["pkgrel"], r["rebuild"][0]["channels"]), ("v1.0.0-rc7", 2, ["beta"]))
        self.assertIn("quickshell 0.3.3-1", r["rebuild"][0]["reasons"][0])
        self.assertIsNone(r["issue"], "rc is as stable here: no decision is left")

    def test_aQuickshellPkgrelBumpIsNotADifference(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.2.r7.g2b4501a-4", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}))
        self.assertEqual((r["rebuild"], r["issue"]), ([], None))

    def test_stableMovesQtAMinor(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.13.0-1", "hyprland": "0.56.2-4"}))
        self.assertEqual([x["pkgrel"] for x in r["rebuild"]], [2])
        self.assertIn("qt6-base 6.13.0-1", r["rebuild"][0]["reasons"][0])

    def test_aQtPatchReleaseIsNotADifference(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.12.4-1", "hyprland": "0.56.2-4"}))
        self.assertEqual((r["rebuild"], r["issue"]), ([], None))

    def test_hyprlandWithAnotherAbiIsARebuild(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-5"},
                                 hypr_h={"stable": version_h(aq="0.16.0"), "rc": version_h(aq="0.16.0")}))
        self.assertEqual(len(r["rebuild"]), 1)
        self.assertIn("plugin ABI efb50993780079460b0cbed1363e2166a2de1d9f_aq_0.16", r["rebuild"][0]["reasons"][0])

    def test_hyprlandPkgrelWithTheSameAbiNeedsNoRebuild(self):
        r = self.run_watch(world(stable={"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-5"}))
        self.assertEqual((r["rebuild"], r["issue"]), ([], None))
        self.assertTrue([n for n in r["notes"] if "no rebuild is needed" in n])

    def test_onlyRcMovedAPersonDecides(self):
        r = self.run_watch(world(rc={"quickshell": "0.3.4-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"},
                                 stable={"quickshell": "0.3.2.r7.g2b4501a-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}))
        self.assertEqual(r["rebuild"], [])
        self.assertIn("Omarchy rc: quickshell 0.3.4-1", r["issue"]["body"])
        self.assertIn("build.yml builds against stable", r["issue"]["body"])

    def test_stableAndRcBothMovedIsOneRebuildAndNoIssue(self):
        moved = {"quickshell": "0.3.3-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}
        r = self.run_watch(world(stable=moved, rc=moved))
        self.assertEqual((len(r["rebuild"]), r["issue"]), (1, None))

    def test_aPluginWithoutAStampIsAnIssue(self):
        r = self.run_watch(world(abi=""))
        self.assertEqual(r["rebuild"], [])
        self.assertIn("no ABI stamp", r["issue"]["body"])

    def test_bothChannelsOfTheSameBuildMakeOneRebuild(self):
        r = self.run_watch(world(channels=("beta", "stable"), stable={"quickshell": "0.3.3-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}))
        self.assertEqual(len(r["rebuild"]), 1)
        self.assertEqual(sorted(r["rebuild"][0]["channels"]), ["beta", "stable"])

    def test_nothingPublishedFailsLoudly(self):
        with self.assertRaises(w.WatchError):
            self.run_watch(world(channels=()))

    def test_aPackageThatDoesNotMatchItsHashFails(self):
        f = world()
        key = [k for k in f.files if k.endswith("grassfield-desktop-1.0.0rc7-1-x86_64.pkg.tar.zst")][0]
        f.files[key] = f.files[key] + b"x"
        with self.assertRaises(w.WatchError):
            self.run_watch(f)

    def test_aMirrorThatCannotBeReadFailsLoudly(self):
        for gone in ("https://rc-mirror.omarchy.org/extra/os/x86_64/extra.db", f"{w.OMARCHY}/stable/x86_64/omarchy.db"):
            f = world()
            del f.files[gone]
            with self.assertRaises(w.WatchError):
                self.run_watch(f)

    def test_aDatabaseWithoutTheDesktopFails(self):
        f = world()
        f.files[f"{BASE}/beta/x86_64/grassfield.db"] = db([("grassfield-compositor", "1.0.0rc7-1", None, "")], "gz")
        with self.assertRaises(w.WatchError):
            self.run_watch(f)

    def test_aPublishedVersionWithMarkupFailsBeforeAnyIssue(self):
        for bad in ("1.0.0rc7-1 @owner", "1.0.0rc7-1\n- [x](http://evil)", "latest"):
            with self.assertRaises(w.WatchError):
                self.run_watch(world(published=bad))

    def test_anOmarchyVersionWithMarkupFails(self):
        f = world()
        f.files[f"https://stable-mirror.omarchy.org/extra/os/x86_64/extra.db"] = db(
            [("qt6-base", "6.12.0-3 @owner", None, ""), ("hyprland", "0.56.2-4", "hyprland-0.56.2-4-x86_64.pkg.tar.zst", "")], "gz")
        with self.assertRaises(w.WatchError):
            self.run_watch(f)

    def test_aFileThatUnpacksTooLargeIsRefused(self):
        blob = zstd(b"\0" * (3 << 20))
        with unittest.mock.patch.object(w, "LIMIT_UNPACKED", 1 << 20):
            with self.assertRaises(w.WatchError):
                w.decompress(blob)
        self.assertEqual(len(w.decompress(blob)), 3 << 20)

    def test_aRecordWithoutQuickshellFails(self):
        with self.assertRaises(w.WatchError):
            self.run_watch(world(record="qt6-base 6.12.0-3\nhyprland 0.56.2-4\n"))

    def test_summaryAndIssueNeverNameASecret(self):
        r = self.run_watch(world(rc={"quickshell": "0.3.4-1", "qt6-base": "6.12.0-3", "hyprland": "0.56.2-4"}))
        text = w.summary(r) + r["issue"]["body"]
        self.assertNotIn("TOKEN", text.upper())


if __name__ == "__main__":
    unittest.main()
