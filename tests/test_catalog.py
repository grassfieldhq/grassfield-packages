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
        icon = next(a for a in obj["apps"] if a["id"] == "example-mail")["icon"]
        self.assertEqual(list(icons), [icon["sha256"]])
        self.assertEqual(icon["bytes"], len(png(64, 64)))

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
        self.script("omarchy-pkg-aur-add", 'yay -S --noconfirm --needed "$@"')
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
            p = catalog.Problems()
            catalog.check_env(GOOD, facts, self.omarchy, p)
            self.assertEqual(p.items, [])
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
