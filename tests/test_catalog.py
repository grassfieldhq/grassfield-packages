"""tools/catalog.py: the rules of ADR-0037 g, the build, the signature and the Store's verification.

Signing tests make throwaway keys and run only inside a container (CLAUDE.md: test keys are made in a test container and
removed with it); tests/run-in-container.sh runs everything there.
"""
import copy
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import catalog  # noqa: E402

IN_CONTAINER = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80\x80\x80\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


GOOD = {
    "version": 1, "channel": "stable", "serial": 1793095200, "generated": "2026-10-27T10:00:00Z",
    "sections": [{"id": "discover", "title": {"en": "Discover", "fr": "Découvrir"}, "symbol": "discover", "blocks": [
        {"kind": "hero", "items": [{"app": "org.example.Paint", "eyebrow": {"en": "New"},
                                    "title": {"en": "Paint"}, "text": {"en": "Line one.\nLine two."}}]},
        {"kind": "row", "title": {"en": "Tools"}, "apps": ["org.example.Paint", "example-mail"]}]}],
    "categories": [{"id": "graphics", "title": {"en": "Graphics"}, "symbol": "category-graphics",
                    "freedesktop": ["Graphics"]}],
    "apps": [
        {"id": "org.example.Paint", "source": {"kind": "repo", "repo": "extra", "package": "paint"},
         "categories": ["graphics"]},
        {"id": "example-mail", "source": {"kind": "webapp", "url": "https://mail.example.com/"},
         "name": {"en": "Example Mail"}, "license": "LicenseRef-web-service",
         "icon": {"sha256": "a" * 64, "bytes": 100, "license": "LicenseRef-trademark-of-its-owner",
                  "origin": "https://example.com/icon.png"}},
        {"id": "org.example.Game", "source": {"kind": "omarchy-setup", "install": "omarchy-install-game",
                                              "args": ["one"], "remove": "omarchy-remove-game", "packages": ["game"],
                                              "changes": {"en": "Installs the game."}}},
        {"id": "org.example.Flat", "source": {"kind": "flatpak", "remote": "flathub", "app": "org.example.Flat"}},
        {"id": "aur-tool", "source": {"kind": "aur", "package": "aur-tool"}},
    ],
    "omarchy": {"tag": "v4.0.4", "commit": "c668141e9c42b13c80c9ca4ea108e11708c5e8a5",
                "files": {"bin/omarchy-install-game": "b" * 64, "bin/omarchy-remove-game": "c" * 64,
                          "install/helpers/x.sh": "d" * 64, "bin/omarchy-pkg-aur-add": "e" * 64,
                          "bin/omarchy-pkg-drop": "f" * 64, "bin/omarchy-pkg-missing": "0" * 64}},
}


def problems(obj, channel=None):
    p = catalog.Problems()
    catalog.validate_catalog(obj, p, channel)
    return p.items


class Rules(unittest.TestCase):
    def test_good_catalog_passes(self):
        self.assertEqual(problems(GOOD), [])

    def broken(self, change, expect):
        obj = copy.deepcopy(GOOD)
        change(obj)
        found = problems(obj)
        self.assertTrue(any(expect in item for item in found), f"{expect!r} not in {found}")

    def test_top_level(self):
        self.broken(lambda o: o.update(version=2), "version: not 1")
        self.broken(lambda o: o.update(channel="nightly"), "channel: not one of")
        self.broken(lambda o: o.update(serial=0), "serial")
        self.broken(lambda o: o.update(serial=True), "serial")
        self.broken(lambda o: o.update(generated="yesterday"), "generated")
        self.broken(lambda o: o.update(extra=1), "unknown key 'extra'")
        self.assertTrue(any("not the channel it is for" in i for i in problems(GOOD, "beta")))

    def test_omarchy(self):
        # The release and the pins the Store checks the installed Omarchy against before it runs a setup (ADR-0037 g).
        self.broken(lambda o: o.pop("omarchy"), "omarchy: missing")
        self.broken(lambda o: o["omarchy"].update(tag="4.0.4"), "tag not like v4.0.4")
        self.broken(lambda o: o["omarchy"].update(commit="C668141E9C42B13C80C9CA4EA108E11708C5E8A5"), "commit not 40")
        self.broken(lambda o: o["omarchy"].update(extra=1), "unknown key 'extra'")
        self.broken(lambda o: o["omarchy"].update(files={}), "files: an object of 1 to 512 pins")
        self.broken(lambda o: o["omarchy"].update(files={f"bin/x{i}": "a" * 64 for i in range(513)}), "1 to 512")
        for bad in ("../x", "bin/../x", "/usr/bin/x", "./bin/x", "bin//x", "bin/x y", "bin/x\n", "a/" * 9 + "x"):
            with self.subTest(bad):
                self.broken(lambda o, bad=bad: o["omarchy"]["files"].update({bad: "a" * 64}), "is not a relative path")
        self.broken(lambda o: o["omarchy"]["files"].update({"bin/y": "A" * 64}), "is not a relative path with a SHA-256")
        self.broken(lambda o: o["omarchy"]["files"].pop("bin/omarchy-remove-game"),
                    "bin/omarchy-remove-game is not pinned")
        # An AUR app: the AUR's two commands must be pinned (SD21), and the object is required for it too.
        for command in ("omarchy-pkg-aur-add", "omarchy-pkg-drop", "omarchy-pkg-missing"):
            with self.subTest(command):
                self.broken(lambda o, c=command: o["omarchy"]["files"].pop(f"bin/{c}"),
                            f"bin/{command} is not pinned, so the Store could not check it (an AUR app)")
        obj = copy.deepcopy(GOOD)
        obj.pop("omarchy")
        obj["apps"] = [a for a in obj["apps"] if a["source"]["kind"] != "omarchy-setup"]
        self.assertIn("omarchy: missing: the Store checks the installed Omarchy against these pins before it builds from "
                      "the AUR", problems(obj))
        # Without a setup or an AUR app it may be left out.
        obj["apps"] = [a for a in obj["apps"] if a["source"]["kind"] != "aur"]
        self.assertEqual(problems(obj), [])

    def test_no_line_end_after_a_token(self):
        # "$" in a pattern also matches before a final line feed: the tokens the Store puts in a command line must not end
        # with one (ADR-0037 e.5).
        for change, expect in ((lambda o: o["apps"][0]["source"].update(package="paint\n"), "package"),
                               (lambda o: o["apps"][2]["source"].update(install="omarchy-install-game\n"), "install does not match"),
                               (lambda o: o["apps"][2]["source"].update(args=["one\n"]), "args"),
                               (lambda o: o["apps"][2]["source"].update(packages=["game\n"]), "packages"),
                               (lambda o: o["apps"][0].update(id="org.example.Paint\n"), "id"),
                               (lambda o: o["omarchy"].update(commit="c668141e9c42b13c80c9ca4ea108e11708c5e8a5\n"), "commit")):
            with self.subTest(expect):
                obj = copy.deepcopy(GOOD)
                change(obj)
                self.assertTrue(any(expect in item for item in problems(obj)), problems(obj))

    def test_sections(self):
        self.broken(lambda o: o["sections"][0].update(id="Discover"), "id does not match")
        self.broken(lambda o: o["sections"].insert(0, copy.deepcopy(o["sections"][0]) | {"id": "work"}),
                    "the first section must be 'discover'")
        self.broken(lambda o: o["sections"][0]["blocks"].clear(), "blocks: 1 to 12")
        self.broken(lambda o: o["sections"][0]["blocks"][0].update(kind="banner"), "kind not one of")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"].extend([{"app": "org.example.Paint",
                                                                              "title": {"en": "x"}}] * 8),
                    "items: 1 to 8")
        self.broken(lambda o: o["sections"][0]["blocks"][1]["apps"].append("org.missing.App"), "is not in apps")
        self.broken(lambda o: o["sections"][0]["blocks"][1]["apps"].append("example-mail"), "appears twice")
        self.broken(lambda o: o.update(sections=o["sections"] * 9), "not a list of 1 to 8")

    def test_texts(self):
        self.broken(lambda o: o["sections"][0].update(title={"fr": "Découvrir"}), "no English text")
        self.broken(lambda o: o["sections"][0].update(title={"en": "Discover", "de": "Entdecken"}),
                    "language 'de'")
        self.broken(lambda o: o["sections"][0].update(title={"en": "x" * 41}), "longer than 40")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"][0].update(title={"en": "a\nb"}),
                    "control, format or separator character U+000A")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"][0].update(text={"en": "evil\u202etxt"}),
                    "U+202E")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"][0].update(text={"en": " padded"}),
                    "space at an end")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"][0].update(text={"en": "é"}), "NFC")
        self.broken(lambda o: o["sections"][0]["blocks"][0]["items"][0].update(title="Paint"), "not an object")
        # Format and separator characters: zero-width space, BOM, soft hyphen, line and paragraph separators.
        for bad, code in (("zero\u200bwidth", "U+200B"), ("\ufeffbom", "U+FEFF"),
                          ("soft\u00adhyphen", "U+00AD"), ("one\u2028two", "U+2028"),
                          ("one\u2029two", "U+2029")):
            self.broken(lambda o, bad=bad: o["sections"][0]["blocks"][0]["items"][0].update(title={"en": bad}), code)
        # Markup: plain text only, so nothing a renderer could read as rich text.
        for bad in ("<b>bold</b>", "a > b", "Tom &amp; Jerry", "&#x202e;", "&#8238;"):
            self.broken(lambda o, bad=bad: o["sections"][0]["blocks"][0]["items"][0].update(text={"en": bad}),
                        "markup")
        ok = copy.deepcopy(GOOD)
        ok["sections"][0]["blocks"][0]["items"][0]["text"] = {"en": "Tom & Jerry; 100% free & open", "fr": "Été"}
        self.assertEqual(problems(ok), [])

    def test_apps(self):
        self.broken(lambda o: o["apps"].append(copy.deepcopy(o["apps"][0])), "id appears twice")
        self.broken(lambda o: o["apps"][0].update(id="has space"), "id does not match")
        self.broken(lambda o: o["apps"][0]["source"].update(repo="testing"), "repo not one of")
        self.broken(lambda o: o["apps"][0]["source"].update(package="-rf"), "package is not a package name")
        self.broken(lambda o: o["apps"][0].update(categories=["missing"]), "category 'missing'")
        self.broken(lambda o: o["apps"][0].update(homepage="http://example.com"), "not an https URL")
        self.broken(lambda o: o["apps"][0].update(homepage="https://exa mple.com"), "whitespace")
        for bad, why in (("https://@", "user information"), ("https://a.com@evil.example/", "user information"),
                         ("https://user:pw@example.com/", "user information"), ("https:///x", "no valid host"),
                         ("https://", "no valid host"), ("https://-bad.example/", "no valid host"),
                         ("https://example.com:99999/", "not a URL"), ("HTTPS://example.com/", "not an https URL")):
            self.broken(lambda o, bad=bad: o["apps"][0].update(homepage=bad), why)
            self.broken(lambda o, bad=bad: o["apps"][1]["source"].update(url=bad), why)
        for good in ("https://example.com", "https://www.example.com/path?q=1#top", "https://example.com:8443/"):
            ok = copy.deepcopy(GOOD)
            ok["apps"][0]["homepage"] = good
            self.assertEqual(problems(ok), [], good)
        self.broken(lambda o: o["apps"][0].update(desktopId="paint"), "desktopId does not match")
        self.broken(lambda o: o["apps"][0].update(license="GPL 3"), "license is not")
        self.broken(lambda o: o["apps"][1].pop("icon"), "a web app needs an icon")
        self.broken(lambda o: o["apps"][1].pop("name"), "name: missing")
        self.broken(lambda o: o["apps"][1]["icon"].update(sha256="A" * 64), "sha256")
        self.broken(lambda o: o["apps"][1]["icon"].update(bytes=300000), "bytes not between")
        self.broken(lambda o: o["apps"][1]["icon"].update(origin="ftp://x"), "not an https URL")
        self.broken(lambda o: o["apps"][3]["source"].update(remote="other"), "remote is not flathub")
        self.broken(lambda o: o["apps"][3]["source"].update(app="-bad"), "not a Flatpak app id")
        self.broken(lambda o: o.update(apps=[dict(a, id=f"x{i}") for i, a in enumerate(o["apps"] * 401)]),
                    "at most 2000")

    def test_setups(self):
        # ADR-0037 e.5: install and remove are each of their own kind.
        self.broken(lambda o: o["apps"][2]["source"].update(install="omarchy-remove-game"), "install does not match")
        self.broken(lambda o: o["apps"][2]["source"].update(remove="omarchy-install-game"), "remove does not match")
        self.broken(lambda o: o["apps"][2]["source"].update(args=["; rm -rf ~"]), "args: at most 4")
        self.broken(lambda o: o["apps"][2]["source"].update(args=["a", "b", "c", "d", "e"]), "args: at most 4")
        self.broken(lambda o: o["apps"][2]["source"].pop("changes"), "changes: missing")
        self.broken(lambda o: o["apps"][2]["source"].update(packages=[]), "packages: 1 to 16")

    def test_webapp_name(self):
        self.assertIsNone(catalog.webapp_name_problem("Example Mail"))
        for bad in ("", ".hidden", "a/b", "x" * 65, "tab\there", "rtl\u202e"):
            self.assertIsNotNone(catalog.webapp_name_problem(bad), bad)
        # validate_catalog applies it to every language of a web app's name: Omarchy's installer makes files of it.
        for bad in ("../../.config/autostart/x", ".hidden", "x" * 70, "a/b"):
            for lang in ("en", "fr"):
                self.broken(lambda o, bad=bad, lang=lang: o["apps"][1]["name"].update({lang: bad}),
                            f"name.{lang}: not a web app name")
        # A repo app's name is a title, not a file name: no such rule.
        ok = copy.deepcopy(GOOD)
        ok["apps"][0]["name"] = {"en": "Paint / Draw"}
        self.assertEqual(problems(ok), [])

    def test_malformed_types_are_problems_not_crashes(self):
        changes = [
            lambda o: o.update(apps=[1, "x", None, []]),
            lambda o: o.update(sections="x", categories={"id": "x"}),
            lambda o: o.update(categories=[{"id": ["x"], "title": {"en": "X"}}]),
            lambda o: o["apps"][0].update(id=["x"]),
            lambda o: o["apps"][0].update(id={"x": 1}),
            lambda o: o["apps"][0].update(categories="graphics"),
            lambda o: o["apps"][0].update(categories=[["graphics"], {"g": 1}]),
            lambda o: o["apps"][0].update(source=["repo"]),
            lambda o: o["apps"][0]["source"].update(kind=["repo"]),
            lambda o: o["apps"][1].update(icon="example-mail"),
            lambda o: o["apps"][1]["icon"].update(sha256=["a"]),
            lambda o: o["apps"][1].update(name=["Example Mail"]),
            lambda o: o["apps"][1].update(name={"en": ["Example Mail"]}),
            lambda o: o["apps"][2]["source"].update(args="one", packages=[["game"]]),
            lambda o: o["sections"][0]["blocks"][1].update(apps=[["org.example.Paint"], {"a": 1}]),
            lambda o: o["sections"][0]["blocks"][0]["items"][0].update(app={"x": 1}),
            lambda o: o["sections"][0].update(blocks=[1, None]),
            lambda o: o["sections"][0].update(id=["discover"]),
        ]
        for i, change in enumerate(changes):
            obj = copy.deepcopy(GOOD)
            change(obj)
            self.assertNotEqual(problems(obj), [], i)
        for obj in ([], "x", None, 1):
            self.assertNotEqual(problems(obj), [], repr(obj))


class Sources(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp()
        for d in ("apps", "sections", "icons"):
            os.makedirs(os.path.join(self.src, d))
        self.write("categories.json", {"categories": GOOD["categories"]})
        self.write("sections/discover.json", dict(GOOD["sections"][0], order=10))
        apps = copy.deepcopy(GOOD["apps"])
        apps[1]["icon"] = "example-mail"
        for a in apps:
            self.write(f"apps/{a['id']}.json", a)
        with open(os.path.join(self.src, "icons", "example-mail.png"), "wb") as f:
            f.write(png(64, 64))
        self.write("icons/example-mail.json", {"license": "LicenseRef-trademark-of-its-owner",
                                               "origin": "https://example.com/icon.png", "review": "needs legal review"})
        o = GOOD["omarchy"]
        with open(os.path.join(self.src, "omarchy.lock"), "w", encoding="utf-8") as f:
            f.write(f"tag {o['tag']}\ncommit {o['commit']}\n\n" +
                    "".join(f"file {digest} {rel}\n" for rel, digest in sorted(o["files"].items())))

    def tearDown(self):
        shutil.rmtree(self.src)

    def write(self, rel, obj):
        with open(os.path.join(self.src, rel), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def load(self):
        p = catalog.Problems()
        obj, icons = catalog.load_sources(self.src, p)
        catalog.validate_catalog(obj, p)
        return obj, icons, p.items

    def test_sources_pass_and_icons_resolve(self):
        obj, icons, found = self.load()
        self.assertEqual(found, [])
        self.assertEqual(obj["omarchy"], GOOD["omarchy"])  # omarchy.lock's release and pins, published for the Store
        icon = next(a for a in obj["apps"] if a["id"] == "example-mail")["icon"]
        self.assertEqual(list(icons), [icon["sha256"]])
        self.assertEqual(icon["bytes"], len(png(64, 64)))
        # The names catalog-facts.sh asks the AUR about: the AUR apps' packages only.
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "catalog.py")
        run = subprocess.run([sys.executable, "-I", tool, "aur-packages", "--src", self.src], capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout), (0, "aur-tool\n"), run.stderr)

    def test_source_problems(self):
        os.rename(os.path.join(self.src, "apps", "aur-tool.json"), os.path.join(self.src, "apps", "other.json"))
        with open(os.path.join(self.src, "icons", "big.png"), "wb") as f:
            f.write(png(600, 10))
        with open(os.path.join(self.src, "apps", "dup.json"), "w") as f:
            f.write('{"id": "dup", "id": "dup2"}')
        _, _, found = self.load()
        text = "\n".join(found)
        self.assertIn("must be named after the app's id", text)
        self.assertIn("at most 262144 bytes and 512x512", text)
        self.assertIn("key 'id' appears twice", text)

    def test_icon_needs_legal_review_mark(self):
        self.write("icons/example-mail.json", {"license": "MIT", "origin": "https://example.com/i.png"})
        _, _, found = self.load()
        self.assertTrue(any("needs legal review" in i for i in found), found)

    def test_unused_icon_and_missing_icon(self):
        with open(os.path.join(self.src, "icons", "spare.png"), "wb") as f:
            f.write(png(8, 8))
        self.write("icons/spare.json", {"license": "MIT", "origin": "https://e.com/s.png", "review": "needs legal review"})
        app = dict(GOOD["apps"][0], icon="nothing")
        self.write("apps/org.example.Paint.json", app)
        _, _, found = self.load()
        text = "\n".join(found)
        self.assertIn("no app uses it", text)
        self.assertIn("icon 'nothing' is not in icons/", text)

    def test_malformed_sources_give_problems_not_tracebacks(self):
        self.write("apps/bad.json", [])
        self.write("apps/x.json", {"id": ["x"], "source": "y", "icon": ["example-mail"]})
        self.write("icons/example-mail.json", [1])
        self.write("sections/a.json", {"id": ["a"], "order": 10})
        with open(os.path.join(self.src, "categories.json"), "w") as f:
            f.write('{"categories": [{"id": {}}]}')
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "catalog.py")
        run = subprocess.run([sys.executable, "-I", tool, "validate", "--src", self.src], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        self.assertIn("problem(s)", run.stderr)
        # What the tool cannot even read ends in one line and exit 2, never a traceback.
        run = subprocess.run([sys.executable, "-I", tool, "verify", "--keyring-dir", self.src, "--channel", "stable",
                              "--min-serial", "x", self.src], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_deep_json_is_a_problem(self):
        with open(os.path.join(self.src, "apps", "deep.json"), "w") as f:
            f.write("[" * 200000 + "]" * 200000)
        _, _, found = self.load()
        self.assertTrue(any("deep.json: cannot be read as UTF-8 JSON" in item for item in found), found)

    def test_build_is_deterministic_and_bounded(self):
        out1, out2 = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            for out in (out1, out2):
                p = catalog.Problems()
                self.assertIsNotNone(catalog.build(self.src, "beta", 1793095200, out, p), p.items)
            data = []
            for o in (out1, out2):
                with open(os.path.join(o, catalog.CATALOG_NAME), "rb") as f:
                    data.append(f.read())
            self.assertEqual(data[0], data[1])
            obj = json.loads(data[0])
            self.assertEqual((obj["channel"], obj["generated"]), ("beta", "2026-10-27T10:00:00Z"))
            self.assertEqual([a["id"] for a in obj["apps"]], sorted(a["id"] for a in obj["apps"]))
            self.assertNotIn("order", obj["sections"][0])
            icon = next(a for a in obj["apps"] if a["id"] == "example-mail")["icon"]
            self.assertTrue(os.path.exists(os.path.join(out1, "catalog", icon["sha256"] + ".png")))
        finally:
            shutil.rmtree(out1)
            shutil.rmtree(out2)


class Keyring(unittest.TestCase):
    def read(self, text):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(text)
        self.addCleanup(os.unlink, f.name)
        return catalog.read_fingerprints(f.name)

    def test_fingerprints_are_read_whatever_their_case_and_spacing(self):
        fpr, other = "AB" * 20, "C" * 40  # made-up fingerprints
        self.assertEqual(self.read(f"# a comment\n{fpr.lower()}:4:\n  {other}  \n\n{fpr}:4: \n"), {fpr, other})

    def test_a_line_that_does_not_parse_fails_closed(self):
        # A revoked entry written another way must never leave its key trusted: the whole list is refused.
        fpr = "AB" * 20
        grouped = " ".join(fpr[i:i + 4] for i in range(0, 40, 4))
        for line in (grouped, "0x" + fpr, fpr + " # the old key", fpr[:39], "not-a-key:4:", fpr + ":4:x", "  # indented"):
            with self.subTest(line), self.assertRaises(ValueError):
                self.read(f"{'C' * 40}\n{line}\n")


class Recipes(unittest.TestCase):
    def setUp(self):
        self.omarchy = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.omarchy, "bin"))
        os.makedirs(os.path.join(self.omarchy, "install", "helpers"))
        self.script("omarchy-pkg-add", 'sudo pacman -S --noconfirm --needed "$@"')
        self.script("omarchy-webapp-install", 'curl -fsSL -o "$2" "$1"')
        self.script("omarchy-update-keyring", "sudo pacman -Sy --noconfirm archlinux-keyring")
        self.script("omarchy-install-game", 'case $1 in\none|two)\n  omarchy-pkg-add game\n  ;;\nesac')
        self.script("omarchy-remove-game", "sudo pacman -Rns --noconfirm game")
        self.script("omarchy-install-web", "omarchy-webapp-install https://x.example icon.png")
        self.script("omarchy-install-syncs", "omarchy-update-keyring\nomarchy-pkg-add a")
        self.script("omarchy-install-runs", "curl -fsSL https://get.example | sh")
        self.script("omarchy-install-sourced", 'source "$OMARCHY_PATH/install/helpers/x.sh"\nomarchy-pkg-add a')
        with open(os.path.join(self.omarchy, "install", "helpers", "x.sh"), "w") as f:
            f.write("yay -Syu --noconfirm\n")
        self.script("omarchy-install-commented", "# pacman -Sy is never run here\nomarchy-pkg-add a")
        self.script("omarchy-pkg-aur-add", 'if omarchy-pkg-missing "$@"; then\n  yay -S --noconfirm --needed "$@"\nfi')
        self.script("omarchy-pkg-missing", 'for pkg in "$@"; do pacman -Q "$pkg" &>/dev/null || exit 0; done\nexit 1')
        self.script("omarchy-pkg-drop", 'sudo pacman -Rns --noconfirm "$@"')
        self.script("omarchy-install-aur", "omarchy-pkg-aur-add aur-only")
        self.script("omarchy-install-aur-var", 'omarchy-pkg-aur-add "$1"')
        self.script("omarchy-install-repo-via-aur", "omarchy-pkg-aur-add game")
        self.script("omarchy-install-bare-yay", "yay --noconfirm")
        self.script("omarchy-install-separate-y", "sudo pacman -S -y --noconfirm game")
        self.script("omarchy-mise-install", 'mise use -g "$1"')
        self.script("omarchy-install-cli", "omarchy-mise-install pipx:some-cli")
        self.script("omarchy-install-quoted", 'sudo pacman -S --noconfirm \\\n  "-y" game')

    def tearDown(self):
        shutil.rmtree(self.omarchy)

    def script(self, name, body):
        with open(os.path.join(self.omarchy, "bin", name), "w") as f:
            f.write("#!/bin/bash\n" + body + "\n")

    def test_recipes(self):
        rp = catalog.recipe_problems
        self.assertEqual(rp(self.omarchy, "omarchy-install-game", ["one", "two"]), [])
        self.assertEqual(rp(self.omarchy, "omarchy-install-web", []), [])  # an icon download is data (S9)
        self.assertEqual(rp(self.omarchy, "omarchy-install-commented", []), [])
        self.assertIn("has no case for 'three'", rp(self.omarchy, "omarchy-install-game", ["three"])[0])
        self.assertIn("syncs pacman's databases (through bin/omarchy-update-keyring)",
                      rp(self.omarchy, "omarchy-install-syncs", [])[0])
        self.assertIn("syncs pacman's databases (through install/helpers/x.sh)",
                      rp(self.omarchy, "omarchy-install-sourced", [])[0])
        self.assertIn("downloads outside pacman", rp(self.omarchy, "omarchy-install-runs", [])[0])
        self.assertIn("not in the pinned Omarchy release", rp(self.omarchy, "omarchy-install-gone", [])[0])
        repo = {"game", "a"}
        self.assertEqual(rp(self.omarchy, "omarchy-install-repo-via-aur", [], repo), [])  # the repo serves it
        self.assertIn("builds from the AUR (through bin/omarchy-install-aur): aur-only",
                      rp(self.omarchy, "omarchy-install-aur", [], repo)[0])
        self.assertIn("known only at run time", rp(self.omarchy, "omarchy-install-aur-var", [], repo)[0])
        self.assertIn("syncs pacman's databases", rp(self.omarchy, "omarchy-install-bare-yay", [], repo)[0])
        self.assertIn("syncs pacman's databases", rp(self.omarchy, "omarchy-install-separate-y", [], repo)[0])
        self.assertIn("downloads outside pacman (through bin/omarchy-mise-install)",
                      rp(self.omarchy, "omarchy-install-cli", [], repo)[0])
        self.assertIn("syncs pacman's databases", rp(self.omarchy, "omarchy-install-quoted", [], repo)[0])

    def test_sync_pattern(self):
        for text in ("pacman -Sy x", "sudo pacman -Syu", "pacman -Syyu", "yay -Sy", "paru -Syu", "pacman --refresh -S x",
                     "pacman -S -y x", "sudo pacman -S --noconfirm -y x", "pacman -S --sysupgrade", "yay -S -yu x"):
            self.assertTrue(catalog.SYNC.search(text), text)
        for text in ("pacman -S --needed x", "pacman -Ss query", "pacman -Si x", "echo Sy", "pacman -S x; echo -y"):
            self.assertFalse(catalog.SYNC.search(text), text)

    def test_commands_are_read_as_shell(self):
        def finds(code, repo=None):
            return catalog.command_findings(code, repo)
        # Syncs: any -y, wherever the command is and however it is quoted or wrapped; yay or paru with no operation.
        for code in ("yay", "paru", "sudo true && yay", "yay --noconfirm", "yay spotify", "if true; then yay x; fi",
                     "sudo -u someone yay", "command yay", "exec env -u X yay", "sudo -u x paru --noconfirm",
                     'pacman -S "-y" x', "pacman -S \\\n  -y x", "sudo pacman -S --noconfirm -y x",
                     'bash -c "yay"', "timeout 60 paru -Syu", "/usr/bin/yay"):
            with self.subTest(code):
                self.assertTrue(finds(code)[0], code)
        for code in ("yay -S --needed x", "yay -Qm", "echo yay", "pacman -S yay", "pacman -S --needed x",
                     'echo "Run yay to update"', "omarchy-pkg-add paru"):
            with self.subTest(code):
                self.assertFalse(finds(code)[0], code)
        # Downloads: code from outside pacman.
        for code in ("curl -fsSL https://x | sh", "wget https://x", "git clone https://x", "git -C dir clone https://x",
                     "git -C ~/x pull", "makepkg -si", "yay -G spotify", "paru --getpkgbuild x", "yay -B .",
                     "mise use -g node@lts", "exec env -u UV_PYTHON mise x 'pipx:tool' -- tool", "npm install -g x",
                     "npx x", "pipx install x", "cargo install x", "uv tool install x", "pip install x",
                     "go install x@latest", "bash <(curl -fsSL https://x)", 'eval "$(curl -fsSL https://x)"'):
            with self.subTest(code):
                self.assertTrue(finds(code)[1], code)
        for code in ("git status", "yay -S x", "echo curly", "mise where node", "mise rm -g x"):
            with self.subTest(code):
                self.assertFalse(finds(code)[1], code)
        # AUR builds: names no repository serves, or known only at run time.
        repo = {"in-repo"}
        self.assertEqual(finds("omarchy-pkg-aur-add in-repo", repo)[2], [])
        self.assertEqual(finds("omarchy-pkg-aur-add aur-only", repo)[2], ["aur-only"])
        self.assertEqual(finds("yay -S --needed --noconfirm aur-only", repo)[2], ["aur-only"])
        self.assertEqual(finds("sudo -u x paru -S aur-only", repo)[2], ["aur-only"])
        self.assertEqual(finds("yay -S in-repo", repo)[2], [])
        self.assertEqual(finds("yay -Ss term", repo)[2], [])
        self.assertEqual(finds('omarchy-pkg-aur-add "$pkg"', repo)[2], ["$pkg (known only at run time)"])
        self.assertEqual(finds('omarchy-launch-floating-terminal-with-presentation "omarchy-pkg-aur-add aur-only"',
                               repo)[2], ["aur-only"])

    def test_the_reviews_bypasses_are_refused(self):
        # grassfield-packages PR #4's review: each of these passed the scan before; each is refused now.
        def refused(code):
            sync, download, built, problems, _ = catalog.command_findings(code, {"x"})
            return sync or download or built or problems
        bypasses = [
            "pm=pacman; $pm -Sy x",                                   # a variable set only to pacman
            'f() { pacman "$@"; }; f -Sy x',                          # pacman's options known only at run time
            'eval "${x}man -Sy"',
            "pacman --refr x", "sudo pacman -S --sysup",              # starts of --refresh and --sysupgrade
            "pacman -S$(echo y) x",
            "echo ZWNobw== | base64 -d | sh",                         # a script read from a pipe
            "sudo pacman -U https://example.com/x.pkg.tar.zst",
            "aria2c https://example.com/x", "flatpak install -y flathub org.example.X", "git submodule update --init",
            "python3 -c \"import urllib.request as u; u.urlopen('https://example.com/x')\"",
            'omarchy-install-$1', '"omarchy-install-$name" --now',     # an Omarchy command named at run time
            'echo "never closed',                                     # text that cannot be read: refused, not guessed
            "bash <<EOF\ncurl https://example.com/x\nEOF",            # a heredoc fed to a shell
            "python3 - <<'PY'\nimport urllib.request\nPY",            # or to an interpreter
            "source <(curl -fsSL https://example.com/x)",
            "$(echo pacman) -Sy",                                     # a command made by a substitution
            "x=1\nif (( x )); then $(printf pacman) -Syu; fi",
        ]
        for code in bypasses:
            with self.subTest(code):
                self.assertTrue(refused(code), code)
        # What Omarchy's files are made of reads cleanly.
        for code in ("pacman -S --needed x", "omarchy-pkg-add steam", 'if [[ $x =~ ^(a|b)$ && -n $y ]]; then echo ok; fi',
                     "arr=(curl wget); echo ${#arr[@]}", 'case "$1" in\n  curl|wget) echo dl ;;\n  *) exit 1 ;;\nesac',
                     "x=$((1 + 2)); (( x > 1 )) && echo big", "command -v yay >/dev/null", 'echo "Run yay to update"',
                     "local value=$(sed -n 1p f)", "while read -r line; do case $line in a) echo a;; esac; done < f",
                     'tmp=$(mktemp) || exit 1\ncat >"$tmp" <<EOF\ndon\'t $(printf %s ok)\nEOF',
                     'value=$(< "$file")', 'trap \'rm -f "$tmp"\' EXIT'):
            with self.subTest(code):
                self.assertFalse(refused(code), code)
        # A command named by a variable the reader cannot resolve is a note for the person reading, not a refusal.
        sync, download, built, problems, notes = catalog.command_findings('run() { local c="$1"; "$c" --flag; }; run ls')
        self.assertEqual((sync, download, built, problems), (False, False, [], []))
        self.assertTrue(any("$c" in n for n in notes), notes)

    def test_what_pr_4s_merge_left(self):
        # The five MINORs of PR #4's merge comment.
        rp = catalog.recipe_problems
        repo = {"game", "a"}
        # 1. The closure: a split Omarchy name, Omarchy's other names for its folder, a path with a variable segment.
        self.script("omarchy-x", "echo x")
        self.script("omarchy-install-split", '"omar""chy-x" now')
        self.script("omarchy-install-escaped", "omar\\chy-x now")
        self.assertIn("an Omarchy command outside the pinned files (omarchy-x)", rp(self.omarchy, "omarchy-install-split", [], repo)[0])
        self.assertIn("an Omarchy command outside the pinned files (omarchy-x)", rp(self.omarchy, "omarchy-install-escaped", [], repo)[0])
        for root in ('"$OMARCHY_INSTALL/helpers/x.sh"', "/usr/share/omarchy/install/helpers/x.sh",
                     "~/.local/share/omarchy/install/helpers/x.sh", '"$HOME/.local/share/omarchy/install/helpers/x.sh"'):
            with self.subTest(root):
                self.script("omarchy-install-root", f"source {root}\nomarchy-pkg-add a")
                # followed into the closure: pinned, and scanned (x.sh syncs)
                self.assertIn("install/helpers/x.sh", [rel for rel, _ in catalog.recipe_closure(self.omarchy, "omarchy-install-root")])
                self.assertIn("syncs pacman's databases (through install/helpers/x.sh)",
                              "\n".join(rp(self.omarchy, "omarchy-install-root", [], repo)))
        self.script("omarchy-install-varpath", 'name=x\nsource "$OMARCHY_PATH/install/helpers/$name.sh"')
        self.assertIn("sources a file outside the pinned files", "\n".join(rp(self.omarchy, "omarchy-install-varpath", [], repo)))
        self.script("omarchy-install-elsewhere", "source /etc/profile.d/x.sh")
        self.assertIn("sources a file outside the pinned files (/etc/profile.d/x.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-elsewhere", [], repo)))
        # 2. A backslash at a line's end joins the lines with nothing.
        self.script("omarchy-install-continued", "pac\\\nman -Sy game")
        self.assertIn("syncs pacman's databases", rp(self.omarchy, "omarchy-install-continued", [], repo)[0])

        # 3. Wrappers and expansions.
        def finds(code):
            return catalog.command_findings(code, repo)
        self.assertTrue(finds("pm=pacman; gum spin --title x -- $pm -Sy x")[0])
        self.assertTrue(any("$pm" in n for n in finds("gum spin -- $pm -Sy x")[4]))  # unresolved: a note
        self.assertTrue(finds("pm=pacman; systemd-run $pm -Sy x")[0])
        self.assertTrue(finds("sudo systemd-run --uid 1000 -p X=1 pacman -Syu")[0])
        self.assertIn("pacman's arguments made by a substitution: they could be options", finds("pacman -S $(cat list)")[3])
        self.assertTrue(any("from an array" in n for n in finds('pkgs=(a b); pacman -S "${pkgs[@]}"')[4]))
        self.assertTrue(any("from an array" in n for n in finds('sudo pacman -S --noconfirm --needed "$@"')[4]))

    def test_what_pr_5s_merge_left(self):
        # The two gaps of PR #5's merge comment.
        rp = catalog.recipe_problems
        repo = {"game", "a"}
        # 1. A file of Omarchy's, or any other, run by a shell or by its path: judged against the pins.
        self.script("omarchy-install-shell", 'bash "$OMARCHY_PATH/install/missing.sh"')
        self.assertIn("bash runs a script outside the pinned files ($OMARCHY_PATH/install/missing.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-shell", [], repo)))
        self.script("omarchy-install-shellvar", 'h=install\nsh -e "$OMARCHY_PATH/$h/run.sh"')
        self.assertIn("sh runs a script outside the pinned files ($OMARCHY_PATH/$h/run.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-shellvar", [], repo)))
        self.script("omarchy-install-direct", '"$OMARCHY_PATH/install/missing.sh"')
        self.assertIn("runs a file outside the pinned files ($OMARCHY_PATH/install/missing.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-direct", [], repo)))
        self.script("omarchy-install-directvar", 'h=install\n"$OMARCHY_PATH/$h/run.sh"')
        self.assertIn("runs a file outside the pinned files ($OMARCHY_PATH/$h/run.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-directvar", [], repo)))
        # A wrapper option the scan does not know is refused, whatever follows: env -a takes an argument ("rm"), which the
        # scan would otherwise read as the command (PR #10's re-review); env -S and flock -c run a command string.
        self.script("omarchy-install-argv0", 'env -a rm bash "$OMARCHY_PATH/hidden/run.sh"')
        self.assertIn("bash runs a script outside the pinned files ($OMARCHY_PATH/hidden/run.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-argv0", [], repo)))
        for code in ('env --block-signal rm bash x.sh', 'env -S "bash x.sh"', 'flock -c "bash x.sh" /tmp/l',
                     'sudo -s bash x.sh', 'runuser -u u -c "bash x.sh"', 'nice -10 bash x.sh', 'systemd-run -S',
                     'xargs -e rm bash x.sh', 'uwsm-app --weird -- bash x.sh'):
            with self.subTest(code):
                self.assertIn("an option the scan does not know", "\n".join(catalog.command_findings(code, repo)[3]))
        # Omarchy's own wrapper options read as before (each form found in v4.0.4's files).
        for code in ("uwsm-app -- true", "env -u BROWSER true", "flock -n 9 true", "flock -w 5 /tmp/l true",
                     "timeout --kill-after=1s 5 true", "sudo -n true", "sudo -v", "sudo -n -l -l", "sudo -u root true",
                     "sudo -E true", "xargs -r true", "xargs -a /tmp/f true", "setsid -f true", "setsid --fork true",
                     'systemd-run --user --collect --quiet --on-active="2s" --timer-property=AccuracySec=100ms true',
                     'systemd-run --user --quiet --collect --unit="omarchy-x" true', "runuser -u u true", "exec -- true",
                     "sudo -nl true"):
            with self.subTest(code):
                self.assertNotIn("an option the scan does not know", "\n".join(catalog.command_findings(code, repo)[3]))
        self.script("omarchy-install-elsewhere", "bash /tmp/x.sh")
        self.assertIn("bash runs a script outside the pinned files (/tmp/x.sh)",
                      "\n".join(rp(self.omarchy, "omarchy-install-elsewhere", [], repo)))
        # A file of the closure, run by a shell (with its options) or by its path: pinned and scanned (x.sh syncs).
        for code in ('bash -e -o pipefail "$OMARCHY_PATH/install/helpers/x.sh"', '"$OMARCHY_PATH/install/helpers/x.sh"'):
            with self.subTest(code):
                self.script("omarchy-install-pinned", f"{code}\nomarchy-pkg-add a")
                text = "\n".join(rp(self.omarchy, "omarchy-install-pinned", [], repo))
                self.assertIn("syncs pacman's databases (through install/helpers/x.sh)", text)
                self.assertNotIn("outside the pinned files", text)
        # How a shell runs its code: text, a file, or its input.
        self.assertEqual(catalog.shell_operand(["-ec", "pacman -Sy"]), ("c", "pacman -Sy"))
        self.assertEqual(catalog.shell_operand(["-o", "pipefail", "x.sh", "a"]), ("file", "x.sh"))
        self.assertEqual(catalog.shell_operand(["--norc", "--", "x.sh"]), ("file", "x.sh"))
        for args in ([], ["-"], ["-s", "a"], ["-es"]):
            self.assertEqual(catalog.shell_operand(args), ("input", None), args)

        # 2. An argument naming a package manager or a downloader, through a command the scan does not know.
        def finds(code):
            return catalog.command_findings(code, repo)
        for code in ("pm=pacman; firejail $pm -Sy x", "pm=/usr/bin/pacman; strace -f $pm -Sy x",
                     'pm=yay; bwrap --bind / / "$pm"', "parallel pacman -S ::: a b", "d=curl; systemd-inhibit $d -O x",
                     "g=git; firejail --quiet $g clone x"):
            with self.subTest(code):
                self.assertTrue(any("a package manager or downloader it may run" in p for p in finds(code)[3]),
                                finds(code))
        # Names as data, and Omarchy's package helpers (read in the closure): no refusal.
        for code in ("omarchy-cmd-present curl", "omarchy-pkg-add flatpak", "pgrep -x pacman", 'echo "pacman"',
                     "chmod +x ~/.local/bin/npm", "pacman -S curl", "command -v yay"):
            with self.subTest(code):
                self.assertEqual(finds(code)[3], [])
        # A plain variable as pacman's argument could hold -y: a note.
        self.assertTrue(any("from a variable ($pkg)" in n for n in finds('pacman -S --noconfirm "$pkg"')[4]))

    def test_what_pr_6s_merge_left(self):
        # The two gaps of PR #6's merge comment.
        rp = catalog.recipe_problems
        repo = {"game", "a"}
        # 1. A file run by a relative or foreign path, or found through a PATH that names a folder the pins do not cover.
        for code, found in (('cd "$OMARCHY_PATH/install" && ./hidden.sh', "runs a file outside the pinned files (./hidden.sh)"),
                            ("/tmp/x.sh", "runs a file outside the pinned files (/tmp/x.sh)"),
                            ('PATH="$OMARCHY_PATH/install:$PATH" hidden.sh',
                             "PATH set to a folder outside the pinned files ($OMARCHY_PATH/install)"),
                            ('env PATH="$OMARCHY_PATH/install:$PATH" hidden.sh',
                             "PATH set to a folder outside the pinned files ($OMARCHY_PATH/install)"),
                            ("export PATH=/tmp/bin:$PATH\nhidden.sh", "PATH set to a folder outside the pinned files (/tmp/bin)"),
                            ("PATH+=:\nhidden.sh", "PATH set to a folder outside the pinned files (the current folder)")):
            with self.subTest(code):
                self.script("omarchy-install-hidden", code)
                self.assertIn(found, "\n".join(rp(self.omarchy, "omarchy-install-hidden", [], repo)))
        # Omarchy's own PATH lines (v4.0.4) and a system program by its path: judged as before.
        self.script("omarchy-install-path", 'export PATH="$OMARCHY_PATH/bin:/usr/local/bin:/usr/bin:$PATH"\n'
                                            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin\n"
                                            "omarchy-pkg-add a")
        self.assertEqual(rp(self.omarchy, "omarchy-install-path", [], repo), [])
        self.script("omarchy-install-abs", "/usr/bin/pacman -Sy game")
        self.assertIn("syncs pacman's databases", rp(self.omarchy, "omarchy-install-abs", [], repo)[0])

        # 2. A variable or a substitution the scan cannot resolve, handed to a command it does not know: a note.
        def notes(code):
            return catalog.command_findings(code, repo)[4]
        for code, arg in (("pm=$(command -v pacman); firejail $pm -Sy", "firejail is handed $pm"),
                          ('firejail --quiet "$pm"', "firejail is handed $pm"),
                          ("gum spin --title t $pm -Sy", "gum is handed $pm"),
                          ("firejail $(command -v pacman) -Sy", "firejail is handed $(...)")):
            with self.subTest(code):
                self.assertTrue(any(arg in n for n in notes(code)), notes(code))
        self.assertTrue(any("gum is handed pacman" in p for p in catalog.command_findings("gum spin --title t pacman -Sy")[3]))
        # Not noted: the file's own functions and Omarchy's commands (read where they are written), names as data.
        for code in ('f() { echo; }\nf "$x"', 'function g { echo; }\ng "$x"', 'omarchy-notification-send "$x"',
                     'kill "$pid"', 'jq -r "$q"'):
            with self.subTest(code):
                self.assertFalse(any("is handed" in n for n in notes(code)), notes(code))

    def test_what_pr_7s_merge_left(self):
        # find's actions that run a command, and run-parts (PR #7's merge comment).
        def finds(code):
            return catalog.command_findings(code, {"game"})
        for code in (r"find /x -name a -exec bash -c 'pacman -Sy' \;", "find /x -execdir pacman -Syu {} ';'",
                     'find /x -ok pacman -Sy {} ";"', "find /x -okdir pacman -Sy {} +",
                     r"find /x -exec rm {} \; -exec pacman -Sy \;"):
            with self.subTest(code):
                self.assertTrue(finds(code)[0], "the command find runs is read: it syncs")
        self.assertTrue(finds(r"find /x -exec curl -O {} \;")[1])
        for code in (r"find /x -exec {} \;", "find /x -type f -exec sh {} +", r"find /x -execdir bash {} \;",
                     r"find /x -exec source {} \;"):
            with self.subTest(code):
                self.assertIn("runs the files it finds: they are outside the pinned files", "\n".join(finds(code)[3]))
        self.assertIn("run-parts runs every file of a folder: they are outside the pinned files", finds("run-parts /etc/x.d")[3])
        # PR #10's review: a wrapper in front of {}, a "+" that does not follow {}, run-parts with more than a listing.
        for code in (r"find /x -exec sudo {} \;", r"find /x -exec env {} \;", r"find /x -exec setsid {} \;",
                     r"find /x -exec nohup {} \;", r"find /x -exec timeout 9 {} \;", r"find /x -exec uwsm-app -- {} \;",
                     r"find /x -exec busybox sh {} \;", r"find /x -exec sudo -u root sh -c 'x' _ {} \;",
                     r"""find /x -exec sh -c '"$1"' + {} \;""", r"find /x -execdir sudo env A=1 {} +",
                     r"find /x -exec python3 -c 'x' {} \;", r"find /x -exec ./{} \;"):
            with self.subTest(code):
                self.assertIn("runs the files it finds: they are outside the pinned files", "\n".join(finds(code)[3]))
        # PR #10's re-review: a wrapper's option that takes an argument, missing from its table, put that argument in the
        # command's place (env -a rm bash {}: "rm" read as the command). A find action handed {} runs no wrapper at all,
        # with each of -exec, -execdir, -ok and -okdir.
        for action in ("-exec", "-execdir", "-ok", "-okdir"):
            for wrapped in ("env -a rm bash", "env --argv0 rm bash", "xargs -E rm bash", "sudo --prompt rm bash",
                            "doas -a rm bash", "run0 --description rm bash", "sudo chmod 644", "env rm",
                            "timeout --kill-after=1s 5 rm"):
                code = f"find /x {action} {wrapped} {{}} \\;"
                with self.subTest(code):
                    self.assertIn("runs the files it finds: they are outside the pinned files", "\n".join(finds(code)[3]))
        for code in ("run-parts -a --list /etc/x.d", "run-parts --list --report /etc/x.d", "run-parts --test",
                     "run-parts --list /etc/x.d /etc/y.d", "run-parts --regex x --list /etc/x.d"):
            with self.subTest(code):
                self.assertIn("run-parts runs every file of a folder: they are outside the pinned files", finds(code)[3])
        # Nothing run: copies, a listing, a quoted or escaped semicolon elsewhere, Omarchy's own find (browser-policy.sh).
        for code in (r"find /x -name '*.desktop' -exec cp {} /y \;", "run-parts --list /etc/x.d", "run-parts --test /etc/x.d",
                     "echo ';'", r"echo a\;b", 'find "$dir" -mindepth 1 -maxdepth 1 ! -user root -exec rm -rf -- {} +',
                     r"find /x -exec chmod 644 {} \;", "find /x -type f -exec sha256sum {} +"):
            with self.subTest(code):
                self.assertEqual(finds(code)[:4], (False, False, [], []))
        # In a recipe: refused.
        self.script("omarchy-install-find", r"find ~/.config -name x -exec pacman -Sy {} \;")
        self.assertIn("syncs pacman's databases", "\n".join(catalog.recipe_problems(self.omarchy, "omarchy-install-find", [], {"game"})))

    def test_what_pr_10s_merge_left(self):
        # The integrator's merge note of PR #10 (and grassfield #34): a command the scan does not know, handed a shell and
        # a script, a file of Omarchy's the release lacks or a script, may run it; and an interpreter's own script.
        os.makedirs(os.path.join(self.omarchy, "shell"))
        for rel, text in (("install/ok.sh", "echo ok\n"), ("install/ok.py", "print(1)\n")):
            with open(os.path.join(self.omarchy, rel), "w") as f:
                f.write(text)

        def judged(code):
            self.script("omarchy-install-runner", code)
            notes = []
            return "\n".join(catalog.recipe_problems(self.omarchy, "omarchy-install-runner", [], {"game"}, notes)), notes
        for code, problem in (
                ('chrt -f 1 bash "$OMARCHY_PATH/hidden/run.sh"', "bash runs a script outside the pinned files "
                                                                  "($OMARCHY_PATH/hidden/run.sh)"),
                ('chrt -f 1 bash "$OMARCHY_PATH/hidden/run.sh"', "chrt is handed a file outside the pinned files "
                                                                  "($OMARCHY_PATH/hidden/run.sh): it may run it"),
                ("firejail bash /tmp/x", "bash runs a script outside the pinned files (/tmp/x)"),
                ("strace -f /usr/bin/python3 -W ignore /tmp/x", "python3 runs a script outside the pinned files (/tmp/x)"),
                ('firejail /usr/bin/bash -c "pacman -Syu"', "syncs pacman's databases"),
                ('chrt -f 1 "$OMARCHY_PATH/hidden/run"', "chrt is handed a file outside the pinned files"),
                ("firejail /tmp/x.sh", "firejail is handed a script outside the pinned files (/tmp/x.sh): it may run it"),
                ("taskset 1 omarchy-missing", "taskset is handed an Omarchy command outside the pinned files "
                                              "(omarchy-missing): it may run it"),
                ('as_root() { sudo "$@"; }\nas_root bash /tmp/x', "bash runs a script outside the pinned files (/tmp/x)"),
                ("python3 /tmp/x.py", "python3 runs a script outside the pinned files (/tmp/x.py)"),
                ("python3 -u -W ignore /tmp/x.py", "python3 runs a script outside the pinned files (/tmp/x.py)"),
                ("perl ./x.pl", "perl runs a script outside the pinned files (./x.pl)"),
                ('node "$OMARCHY_PATH/hidden/x.js"', "node runs a script outside the pinned files ($OMARCHY_PATH/hidden/x.js)")):
            with self.subTest(code):
                self.assertIn(problem, judged(code)[0])
        # Read as before: a pinned script through a runner, code given as text or a module, a login shell named as data,
        # a file in the home folder, a shell with nothing after it (it reads its terminal).
        for code in ('chrt -f 1 bash "$OMARCHY_PATH/install/ok.sh"', 'python3 "$OMARCHY_PATH/install/ok.py"',
                     'python3 -c "print(1)"', 'python3 -uc "print(1)"', "python3 -m json.tool f", 'perl -ne "print" f',
                     'node -e "1"', "useradd -m -s /bin/bash u", "usermod -s /bin/zsh u", "chsh -s /bin/zsh",
                     'sed -i "s/a/b/" ~/.config/x.conf', "firejail bash"):
            with self.subTest(code):
                self.assertEqual(judged(code), ("", []))
        # One of Omarchy's folders (Omarchy's own: quickshell -p "$OMARCHY_PATH/shell"): its files are not pinned, a note.
        problems, notes = judged('systemd-cat -t s -- quickshell -n -p "$OMARCHY_PATH/shell"')
        self.assertEqual(problems, "")
        self.assertEqual(notes, ["bin/omarchy-install-runner: systemd-cat is handed Omarchy's folder shell: its files are not "
                                 "pinned; read what it does with them"])

    def test_pins(self):
        pins = catalog.pin_files(GOOD, self.omarchy)
        self.assertEqual(sorted(pins), ["bin/omarchy-install-game", "bin/omarchy-pkg-add", "bin/omarchy-pkg-aur-add",
                                        "bin/omarchy-pkg-drop", "bin/omarchy-pkg-missing", "bin/omarchy-remove-game"])
        # The AUR's two commands are pinned whether or not the catalog lists an AUR app or a setup (SD21).
        bare = dict(GOOD, apps=[a for a in GOOD["apps"] if a["source"]["kind"] in ("repo", "webapp")])
        self.assertEqual(sorted(catalog.pin_files(bare, self.omarchy)),
                         ["bin/omarchy-pkg-aur-add", "bin/omarchy-pkg-drop", "bin/omarchy-pkg-missing"])

        def found(pins):
            p = catalog.Problems()
            catalog.pin_problems(GOOD, self.omarchy, pins, p)
            return "\n".join(p.items)
        self.assertEqual(found(pins), "")
        # One byte changed in a file a setup runs: refused until a person reads it and pins it again.
        with open(os.path.join(self.omarchy, "bin", "omarchy-pkg-add"), "a") as f:
            f.write(" ")
        self.assertIn("omarchy bin/omarchy-pkg-add: differs from its pin", found(pins))
        pins = catalog.pin_files(GOOD, self.omarchy)
        # A file newly called: not pinned.
        self.script("omarchy-game-helper", "echo helping")
        self.script("omarchy-install-game", 'case $1 in\none|two)\n  omarchy-pkg-add game\n  omarchy-game-helper\n  ;;\nesac')
        text = found(pins)
        self.assertIn("omarchy bin/omarchy-game-helper: run or read by a setup or the AUR's commands, not pinned", text)
        self.assertIn("omarchy bin/omarchy-install-game: differs from its pin", text)
        pins = catalog.pin_files(GOOD, self.omarchy)
        # A pinned file gone from the checkout, and one no setup uses any more.
        os.unlink(os.path.join(self.omarchy, "bin", "omarchy-remove-game"))
        self.assertIn("omarchy bin/omarchy-remove-game: pinned but missing", found(pins))
        stale = dict(catalog.pin_files(GOOD, self.omarchy), **{"bin/omarchy-update-keyring": "0" * 64})
        self.assertIn("omarchy bin/omarchy-update-keyring: pinned but no longer run or read", found(stale))
        # A lock line that does not parse: the lock is not used (fail closed).
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("tag v4.0.4\nfile 1234 bin/x\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(ValueError):
            catalog.read_pins(f.name)

    def test_pin_command(self):
        src = Sources()
        src.setUp()
        self.addCleanup(src.tearDown)
        lock = os.path.join(src.src, "omarchy.lock")
        with open(lock, "w") as f:
            f.write("# the pinned release\ntag v4.0.4\ncommit c668141e9c42b13c80c9ca4ea108e11708c5e8a5\n")
        # 4. The checkout's commit: from .git, or from .commit as catalog-facts.sh reads it; neither, or another: refused.
        commit = os.path.join(self.omarchy, ".commit")
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "catalog.py")

        def pin():
            return subprocess.run([sys.executable, "-I", tool, "pin", "--src", src.src, "--omarchy", self.omarchy],
                                  capture_output=True, text=True)
        run = pin()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("an unknown commit (no .git, no .commit)", run.stderr)
        with open(commit, "w") as f:
            f.write("0" * 40 + "\n")
        run = pin()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("the checkout is at " + "0" * 40, run.stderr)
        with open(commit, "w") as f:
            f.write("c668141e9c42b13c80c9ca4ea108e11708c5e8a5\n")
        run = pin()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("new      bin/omarchy-pkg-add", run.stdout)
        self.assertEqual(catalog.read_pins(lock), catalog.pin_files(GOOD, self.omarchy))
        with open(lock) as f:
            self.assertTrue(f.read().startswith("# the pinned release\ntag v4.0.4\ncommit c668141"))
        self.assertIn("nothing changed", pin().stdout)
        # The scan finds something in a file a setup runs: no pin is written.
        with open(lock) as f:
            before = f.read()
        self.script("omarchy-pkg-add", 'sudo pacman -S --noconfirm --needed "$@"\neval "$EXTRA"')
        run = pin()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("eval: code made at run time", run.stderr)
        with open(lock) as f:
            self.assertEqual(f.read(), before)
        # The same in one of the AUR's two commands, which no setup of this catalog calls (SD21).
        self.script("omarchy-pkg-add", 'sudo pacman -S --noconfirm --needed "$@"')
        self.script("omarchy-pkg-drop", 'sudo pacman -Rns --noconfirm "$@"\nsudo pacman -Sy')
        run = pin()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("recipe omarchy-pkg-drop: omarchy-pkg-drop syncs pacman's databases", run.stderr)
        with open(lock) as f:
            self.assertEqual(f.read(), before)

    def test_check_env(self):
        facts = tempfile.mkdtemp()
        try:
            with open(os.path.join(facts, "repo-packages.txt"), "w") as f:
                f.write("extra paint 1-1\nextra game 1-1\n")
            with open(os.path.join(facts, "app-entries.txt"), "w") as f:
                f.write("paint /usr/share/applications/org.example.Paint.desktop\n")
            with open(os.path.join(facts, "appstream-ids.txt"), "w") as f:
                f.write("paint org.example.Paint desktop-application\ngame org.example.Game desktop-application\n")
            with open(os.path.join(facts, "flathub-ids.txt"), "w") as f:
                f.write("org.example.Flat\n")
            with open(os.path.join(facts, "aur-packages.txt"), "w") as f:
                f.write("# the AUR's web service\naur-tool 1.2-1\n")
            p = catalog.Problems()
            catalog.check_env(GOOD, facts, self.omarchy, p, catalog.pin_files(GOOD, self.omarchy))
            self.assertEqual(p.items, [])
            p = catalog.Problems()
            catalog.check_env(GOOD, facts, self.omarchy, p, {})  # nothing pinned: every file the setup runs is refused
            self.assertIn("not pinned", "\n".join(p.items))
            bad = copy.deepcopy(GOOD)
            bad["apps"][0]["id"] = "paint-app"
            bad["apps"][0]["desktopId"] = "other.desktop"
            bad["apps"][2]["source"]["packages"] = ["missing"]
            bad["apps"][3]["source"]["app"] = "org.example.Gone"
            bad["apps"].append({"id": "org.example.Cli", "source": {"kind": "repo", "repo": "core", "package": "paint"}})
            p = catalog.Problems()
            catalog.check_env(bad, facts, self.omarchy, p)
            text = "\n".join(p.items)
            self.assertIn("AppStream knows paint as org.example.Paint", text)
            self.assertIn("desktopId other.desktop is not one of paint's entries", text)
            self.assertIn("package missing is on no repository", text)
            self.assertIn("Flathub's AppStream has no app org.example.Gone", text)
            self.assertIn("[core] has no package paint", text)
            # An AUR app (SD21, SD22): a repository's name is refused (yay would install the repository's), and so is a
            # name the AUR does not know, or no AUR facts at all.
            aur = copy.deepcopy(GOOD)
            aur["apps"].append({"id": "aur-game", "source": {"kind": "aur", "package": "game"}})
            aur["apps"].append({"id": "aur-gone", "source": {"kind": "aur", "package": "aur-gone"}})
            p = catalog.Problems()
            catalog.check_env(aur, facts, self.omarchy, p)
            text = "\n".join(p.items)
            self.assertIn("app aur-game: [extra] has game: yay would install the repository's; list it as a repo app", text)
            self.assertIn("app aur-gone: the AUR has no package aur-gone", text)
            self.assertNotIn("app aur-tool", text)
            os.unlink(os.path.join(facts, "aur-packages.txt"))
            p = catalog.Problems()
            catalog.check_env(GOOD, facts, self.omarchy, p)
            self.assertEqual(p.items, ["app aur-tool: no AUR facts (aur-packages.txt) to check it against"])
            # The AUR's two commands are scanned whatever the catalog lists: one that syncs, or one Omarchy lacks, is
            # refused.
            self.script("omarchy-pkg-drop", 'sudo pacman -Rns --noconfirm "$@"\nsudo pacman -Sy')
            os.unlink(os.path.join(self.omarchy, "bin", "omarchy-pkg-aur-add"))
            bare = dict(GOOD, apps=[a for a in GOOD["apps"] if a["source"]["kind"] in ("repo", "webapp")])
            p = catalog.Problems()
            catalog.check_env(bare, facts, self.omarchy, p)
            text = "\n".join(p.items)
            self.assertIn("AUR command omarchy-pkg-drop: omarchy-pkg-drop syncs pacman's databases", text)
            self.assertIn("AUR command omarchy-pkg-aur-add: omarchy-pkg-aur-add is not in the pinned Omarchy release", text)
        finally:
            shutil.rmtree(facts)


@unittest.skipUnless(IN_CONTAINER, "throwaway keys are made only inside a test container (CLAUDE.md)")
class Signature(unittest.TestCase):
    """Signs with a throwaway key and verifies as the Store does: gpgv, VALIDSIG's argument 10, trusted, not revoked."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.keys = [cls.make_key(f"Grassfield test {i} <test{i}@grassfield.invalid>") for i in (1, 2)]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home)

    @classmethod
    def make_key(cls, uid):
        env = catalog.child_env(cls.home)
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-gen-key", uid,
                        "ed25519", "sign", "1d"],
                       check=True, env=env, capture_output=True)
        out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys", uid], check=True, env=env,
                             capture_output=True, text=True).stdout
        return next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:"))

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.keyring = tempfile.mkdtemp()
        src = Sources()
        src.setUp()
        self.addCleanup(src.tearDown)
        p = catalog.Problems()
        self.path = catalog.build(src.src, "stable", 1793095200, self.out, p)
        self.assertIsNotNone(self.path, p.items)
        self.set_keyring(trusted=[self.keys[0]])

    def tearDown(self):
        shutil.rmtree(self.out)
        shutil.rmtree(self.keyring)

    def set_keyring(self, trusted, revoked=(), keys=None):
        env = catalog.child_env(self.home)
        exported = subprocess.run(["gpg", "--batch", "--export"] + list(keys or self.keys), check=True, env=env,
                                  capture_output=True).stdout
        with open(os.path.join(self.keyring, "grassfield.gpg"), "wb") as f:
            f.write(exported)
        with open(os.path.join(self.keyring, "grassfield-trusted"), "w") as f:
            f.write("".join(f"{k}:4:\n" for k in trusted))
        with open(os.path.join(self.keyring, "grassfield-revoked"), "w") as f:
            f.write("".join(f"{k}\n" for k in revoked))

    def verify(self, channel="stable", min_serial=0):
        p = catalog.Problems()
        catalog.verify(self.out, self.keyring, channel, min_serial, p)
        return "\n".join(p.items)

    def test_good_signature(self):
        catalog.sign(self.path, self.home, self.keys[0])
        self.assertEqual(self.verify(), "")

    def test_refusals(self):
        catalog.sign(self.path, self.home, self.keys[1])
        self.assertIn("which grassfield-trusted does not list", self.verify())
        catalog.sign(self.path, self.home, self.keys[0])
        self.set_keyring(trusted=[self.keys[0]], revoked=[self.keys[0]])
        self.assertIn("grassfield-revoked does", self.verify())
        self.set_keyring(trusted=[self.keys[0]])
        self.assertIn("not the channel it is for", self.verify(channel="beta"))
        self.assertIn("lower than the one already accepted", self.verify(min_serial=1793095201))
        self.set_keyring(trusted=[], keys=[self.keys[0]])
        self.assertIn("no trusted key", self.verify())

    def test_signed_but_not_json(self):
        with open(self.path, "wb") as f:
            f.write(b"\xff not json")
        catalog.sign(self.path, self.home, self.keys[0])
        self.assertIn("signed, but not UTF-8 JSON", self.verify())

    def test_hand_written_keyring_lists(self):
        # A revoked or trusted entry in lower case or with spaces still counts (the review's minor 3).
        catalog.sign(self.path, self.home, self.keys[0])
        with open(os.path.join(self.keyring, "grassfield-trusted"), "w") as f:
            f.write(f"{self.keys[0].lower()}:4: \n")
        self.assertEqual(self.verify(), "")
        with open(os.path.join(self.keyring, "grassfield-revoked"), "w") as f:
            f.write(f"  {self.keys[0].lower()}  \n")
        self.assertIn("grassfield-revoked does", self.verify())

    def test_what_a_fetch_can_leave(self):
        catalog.sign(self.path, self.home, self.keys[0])
        with open(self.path, "rb") as f:
            data = f.read()
        with open(self.path + ".sig", "rb") as f:
            sig = f.read()
        cases = {
            "a truncated catalog": (data[:len(data) // 2], sig, "bad or missing signature"),
            "a truncated .sig": (data, sig[:len(sig) // 2], "bad or missing signature"),
            "an empty .sig": (data, b"", "bad or missing signature"),
        }
        for why, (body, signature, expect) in cases.items():
            with self.subTest(why):
                with open(self.path, "wb") as f:
                    f.write(body)
                with open(self.path + ".sig", "wb") as f:
                    f.write(signature)
                self.assertIn(expect, self.verify())
        os.unlink(self.path + ".sig")
        self.assertIn("missing, or its .sig is", self.verify())

    def test_signer_not_in_the_keyring(self):
        # The second key signs; grassfield.gpg holds only the first: gpgv cannot check it at all.
        catalog.sign(self.path, self.home, self.keys[1])
        self.set_keyring(trusted=[self.keys[0], self.keys[1]], keys=[self.keys[0]])
        self.assertIn("bad or missing signature", self.verify())

    def test_two_signers(self):
        # One signature file holding two signatures by two trusted keys: which one vouches for it is unknown.
        sig = self.path + ".sig"
        subprocess.run(["gpg", "--batch", "--no-tty", "--yes", "--homedir", self.home, "--local-user", self.keys[0] + "!",
                        "--local-user", self.keys[1] + "!", "--detach-sign", "--output", sig, self.path],
                       check=True, env=catalog.child_env(self.home), capture_output=True)
        self.set_keyring(trusted=self.keys)
        self.assertIn("signatures by more than one key", self.verify())

    def test_a_signed_message_is_not_a_signature(self):
        # The catalog signed as a message of its own (gpg --sign), given as its .sig: refused.
        subprocess.run(["gpg", "--batch", "--no-tty", "--yes", "--homedir", self.home, "--local-user", self.keys[0] + "!",
                        "--sign", "--output", self.path + ".sig", self.path],
                       check=True, env=catalog.child_env(self.home), capture_output=True)
        self.assertIn("bad or missing signature", self.verify())

    def test_unreadable_revoked_list_refuses_everything(self):
        catalog.sign(self.path, self.home, self.keys[0])
        with open(os.path.join(self.keyring, "grassfield-revoked"), "w") as f:
            f.write(f"0x{self.keys[0]}\n")
        self.assertIn("keyring files cannot be read", self.verify())

    def test_deep_signed_json(self):
        with open(self.path, "w") as f:
            f.write("[" * 200000 + "]" * 200000)
        catalog.sign(self.path, self.home, self.keys[0])
        self.assertIn("signed, but not UTF-8 JSON", self.verify())

    def test_oversize_catalog(self):
        with open(self.path, "wb") as f:
            f.write(b" " * (catalog.MAX_CATALOG + 1))
        catalog.sign(self.path, self.home, self.keys[0])
        self.assertIn(f"more than {catalog.MAX_CATALOG} bytes", self.verify())

    def test_sign_failure_is_one_line(self):
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "catalog.py")
        run = subprocess.run([sys.executable, "-I", tool, "sign", "--homedir", self.home, "--key", "F" * 40, self.path],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        self.assertIn("CalledProcessError", run.stderr)

    def test_changed_file_and_icon(self):
        catalog.sign(self.path, self.home, self.keys[0])
        icons = os.listdir(os.path.join(self.out, "catalog"))
        with open(os.path.join(self.out, "catalog", icons[0]), "ab") as f:
            f.write(b"x")
        self.assertIn("does not match the hash", self.verify())
        with open(self.path, "ab") as f:
            f.write(b" ")
        self.assertIn("bad or missing signature", self.verify())


if __name__ == "__main__":
    unittest.main()
