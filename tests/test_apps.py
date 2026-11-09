"""The bundled apps (grassfield ADR-0055): grassfield-sanaga/ and grassfield-notes/, their pins, their names against the
channel's name rules, build-channel.sh building and reusing them, and scripts/app-check.sh, the reuse rule.

Static checks over the PKGBUILDs and scripts, plus app-check.sh on small fake packages made with bsdtar. Nothing here
builds a package, signs anything or needs the network (the real build is CI's build job; scripts/bump-app.sh --verify
recomputes the pins from the network).
"""
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import publish  # noqa: E402

APPS = ("grassfield-sanaga", "grassfield-notes")
HAVE_BSDTAR = shutil.which("bsdtar") is not None


def pkgbuild_vars(app, *names):
    """Variables of an app's PKGBUILD, sourced by bash (arrays joined by newlines)."""
    script = 'source "$1/PKGBUILD" >/dev/null 2>&1; shift; for v in "$@"; do eval "printf \'%s\\n\' \\"\\${$v[@]}\\""; done'
    out = subprocess.run(["bash", "-c", script, "_", str(ROOT / app)] + list(names), check=True, capture_output=True,
                         text=True).stdout
    return out


def var(app, name):
    return pkgbuild_vars(app, name).rstrip("\n")


def text(path):
    return (ROOT / path).read_text()


class Pins(unittest.TestCase):
    """The source is one commit by its full SHA with a real checksum, never a tag, a branch or SKIP."""

    def test_the_commit_is_a_full_sha_and_the_source_is_its_archive(self):
        pins = {"grassfield-sanaga": "a9e0e561bfc8105efa5d9d56844c1c18034d04fd",
                "grassfield-notes": "2daf1c887a93e7a0931626194546bb88b0aeffe8"}
        for app in APPS:
            with self.subTest(app):
                commit = var(app, "_commit")
                self.assertRegex(commit, r"^[0-9a-f]{40}$")
                self.assertEqual(commit, pins[app], "the owner's pin of 2026-11-09 (a bump changes it on purpose)")
                source = pkgbuild_vars(app, "source").strip()
                self.assertEqual(len(source.splitlines()), 1)
                self.assertRegex(source, rf"^{app}-{commit}\.tar\.gz::https://github\.com/grassfieldhq/[a-z-]+/archive/{commit}\.tar\.gz$")
                self.assertNotRegex(source, r"git\+|#tag=|#branch=|#commit=")

    def test_the_checksum_is_a_sha256_not_skip(self):
        for app in APPS:
            with self.subTest(app):
                sums = pkgbuild_vars(app, "sha256sums").split()
                self.assertEqual(len(sums), 1)
                self.assertRegex(sums[0], r"^[0-9a-f]{64}$")
                body = text(f"{app}/PKGBUILD")
                self.assertNotRegex(body, r"(?m)^[a-z0-9]*sums=.*SKIP")
                for other in ("md5sums", "sha1sums", "b2sums", "sha512sums"):
                    self.assertNotRegex(body, rf"^{other}=", other)

    def test_pkgver_is_the_cargo_version_the_commit_count_and_the_short_sha(self):
        for app in APPS:
            with self.subTest(app):
                cargo, rev, commit = var(app, "_cargover"), var(app, "_rev"), var(app, "_commit")
                self.assertRegex(cargo, r"^[0-9]+\.[0-9]+\.[0-9]+$")
                self.assertRegex(rev, r"^[1-9][0-9]*$")
                self.assertEqual(var(app, "pkgver"), f"{cargo}.r{rev}.g{commit[:7]}")
                self.assertRegex(var(app, "pkgrel"), r"^[1-9][0-9]*$")
                # Arch's rules for a pkgver: no hyphen, no colon, no space.
                self.assertRegex(var(app, "pkgver"), r"^[0-9A-Za-z._+]+$")

    def test_the_build_is_locked_then_offline_with_tests(self):
        for app in APPS:
            with self.subTest(app):
                body = text(f"{app}/PKGBUILD")
                self.assertIn("cargo fetch --locked", body)
                self.assertIn("cargo build --frozen --release", body)
                self.assertIn("cargo test --frozen --release", body)
                self.assertRegex(body, r"(?m)^check\(\) \{")
                self.assertNotIn("--no-default-features", body)
                self.assertRegex(var(app, "options"), r"!lto")
                self.assertIn("!debug", var(app, "options"))  # a -debug package would join the channel
                # prepare() refuses a PKGBUILD whose Cargo version is not the source's: a bump cannot half-apply.
                self.assertIn('[[ $v == "$_cargover" ]]', body)

    def test_runtime_and_build_dependencies(self):
        sanaga = pkgbuild_vars("grassfield-sanaga", "depends").split()
        for needed in ("gtk4", "webkitgtk-6.0", "bubblewrap", "xdg-dbus-proxy", "gst-libav", "gst-plugins-bad",
                       "gst-plugins-good", "libsecret", "wayland", "libxkbcommon", "libglvnd"):
            self.assertIn(needed, sanaga)
        notes = pkgbuild_vars("grassfield-notes", "depends").split()
        for needed in ("wayland", "libxkbcommon", "libglvnd"):  # eframe's winit and glow open these at run time
            self.assertIn(needed, notes)
        for app in APPS:  # `rust` by name: `cargo` has two providers (rust, rustup) and --noconfirm may pick rustup
            self.assertIn("rust", pkgbuild_vars(app, "makedepends").split())


class Contract(unittest.TestCase):
    """The names and files the two agents agreed: grassfield-desktop depends on `sanaga` and grassfield-notes."""

    def test_sanaga_is_grassfield_sanaga_providing_and_conflicting_with_sanaga(self):
        self.assertEqual(var("grassfield-sanaga", "pkgname"), "grassfield-sanaga")
        self.assertEqual(var("grassfield-sanaga", "pkgdesc"), "Sanaga, the Grassfield web browser")
        self.assertEqual(pkgbuild_vars("grassfield-sanaga", "provides").split(), ["sanaga"])
        self.assertEqual(pkgbuild_vars("grassfield-sanaga", "conflicts").split(), ["sanaga"])
        self.assertEqual(pkgbuild_vars("grassfield-sanaga", "replaces").split(), [])
        self.assertEqual(var("grassfield-notes", "pkgname"), "grassfield-notes")
        for app in APPS:
            self.assertNotRegex(text(f"{app}/PKGBUILD"), r"(?m)^replaces=")  # ADR-0033 b.6

    def test_the_files_installed(self):
        sanaga = text("grassfield-sanaga/PKGBUILD")
        notes = text("grassfield-notes/PKGBUILD")
        for body, binary, desktop, license_ in ((sanaga, "sanaga", "sanaga.desktop", "$pkgname/LICENSE"),
                                                (notes, "grassfield-notes", "grassfield-notes.desktop", "$pkgname/LICENSE")):
            self.assertIn(f'"$pkgdir/usr/bin/{binary}"', body)
            self.assertIn(f'"$pkgdir/usr/share/applications/{desktop}"', body)
            self.assertIn(f"/usr/share/icons/hicolor/", body)
            self.assertIn(f'"$pkgdir/usr/share/licenses/{license_}"', body)
            self.assertIn(f"/apps/{binary}.png", body)
        self.assertIn("/hicolor/scalable/apps/sanaga.svg", sanaga)
        self.assertIn("SANAGA_DISTRO=grassfield", sanaga)  # the codecs come with the package (packaging/DISTRIBUTIONS.md)

    def test_both_package_files_pass_the_channels_name_checks_unchanged(self):
        """build-channel.sh (grassfield-*), check-tree.sh (^grassfield-), sign-release.sh (PACKAGE) and publish.py."""
        build = text("scripts/build-channel.sh")
        self.assertIn("[[ $name == grassfield-* ]]", build)
        check = text("scripts/check-tree.sh")
        self.assertIn("grep -v '^grassfield-'", check)
        package = re.search(r"^PACKAGE='(.*)'$", text("scripts/sign-release.sh"), re.M).group(1)
        for app in APPS:
            with self.subTest(app):
                name = var(app, "pkgname")
                filename = f"{name}-{var(app, 'pkgver')}-{var(app, 'pkgrel')}-x86_64.pkg.tar.zst"
                self.assertTrue(name.startswith("grassfield-"))
                # sign-release.sh's regular expression, evaluated by bash as the script does.
                ok = subprocess.run(["bash", "-c", '[[ $1 =~ $2 ]]', "_", filename, package]).returncode
                self.assertEqual(ok, 0, f"{filename} against {package}")
                self.assertTrue(publish.PACKAGE_FILE.match(filename))
                self.assertTrue(publish.PACKAGE_FILE.match(filename + ".sig"))
                # check-tree.sh: the name line of the database's desc, filtered by `grep -v '^grassfield-'`.
                left = subprocess.run(["bash", "-c", "grep -v '^grassfield-'", "_"], input=name + "\n", text=True,
                                      capture_output=True).stdout
                self.assertEqual(left, "")


class BuildChannel(unittest.TestCase):
    """scripts/build-channel.sh: both apps in the one clean container, before grassfield-desktop, signed, in every release."""

    def setUp(self):
        self.script = text("scripts/build-channel.sh")

    def test_it_names_both_apps_and_builds_them_before_the_desktop(self):
        self.assertIn("apps=(grassfield-sanaga grassfield-notes)", self.script)
        self.assertLess(self.script.index('for a in "${apps[@]}"; do build_app "$a"; done'),
                        self.script.index('step "makepkg (grassfield\'s packaging/arch/PKGBUILD)"'))
        # Built by makepkg -s as the builder user (the same container, the same pacman.conf), then signed.
        self.assertRegex(self.script, r"runuser -u builder -- env SRCDEST=/build/srcdest PKGDEST=\"\$work\" makepkg -sc")
        self.assertIn('sign "$pkg"', self.script)

    def test_every_release_build_holds_them(self):
        self.assertIn("shipped=(\"$keyring_pkg\")", self.script)
        self.assertIn("shipped+=(\"$pkg\")", self.script)
        # The three places the keyring package is handled: the name checks, the printed list, the release build's files.
        self.assertIn('for f in "${built[@]}" "${shipped[@]}"; do\n  info=', self.script)
        self.assertIn('printf \'%s\\n\' "${built[@]##*/}" "${shipped[@]##*/}"', self.script)
        self.assertIn('for f in "${built[@]}" "${shipped[@]}"; do cp "$f" "$f.sig" "$out/"; done', self.script)
        self.assertNotRegex(self.script, r'"\$keyring_pkg"; do')  # nothing handles the keyring alone any more
        self.assertIn('echo "apps ${app_versions[*]}"', self.script)

    def test_reuse_needs_the_signature_and_the_same_pkgbuild(self):
        body = self.script[self.script.index("build_app() {"):self.script.index('step "bundled apps')]
        self.assertIn('old=$(find "$tree" -type f -name "${pkg##*/}" -print -quit)', body)
        self.assertIn('[[ $signer == "$key" ]]', body)
        # Reused or built, the package is checked against the folder's PKGBUILD.
        self.assertEqual(body.count('scripts/app-check.sh'), 2)
        self.assertIn("a changed PKGBUILD is a new pkgrel", body)
        # A build with no pin refuses before downloading anything.
        self.assertIn("is not pinned by a full commit and SHA-256 checksums", body)

    def test_the_pin_check_of_build_channel_rejects_skip(self):
        pin = re.search(r"bash -c '(source \"\$1/PKGBUILD\".*?)' _ \"\$work\"", self.script, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            def run(body):
                pathlib.Path(tmp, "PKGBUILD").write_text(body)
                return subprocess.run(["bash", "-c", pin, "_", tmp]).returncode
            good = f"_commit={'a' * 40}\nsha256sums=('{'b' * 64}')\n"
            self.assertEqual(run(good), 0)
            self.assertNotEqual(run(f"_commit={'a' * 40}\nsha256sums=('SKIP')\n"), 0)
            self.assertNotEqual(run(f"_commit=a9e0e56\nsha256sums=('{'b' * 64}')\n"), 0)
            self.assertNotEqual(run(f"_commit={'a' * 40}\nsha256sums=('{'b' * 64}' 'SKIP')\n"), 0)


@unittest.skipUnless(HAVE_BSDTAR, "needs bsdtar (libarchive)")
class AppCheck(unittest.TestCase):
    """scripts/app-check.sh on small fake packages: the reuse rule."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = pathlib.Path(self.tmp, "grassfield-notes")
        self.app.mkdir()
        shutil.copy(ROOT / "grassfield-notes" / "PKGBUILD", self.app / "PKGBUILD")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def package(self, pkgbuild_sum=None, pkgver=None, name="grassfield-notes"):
        pkgbuild = self.app / "PKGBUILD"
        pkgbuild_sum = pkgbuild_sum or hashlib.sha256(pkgbuild.read_bytes()).hexdigest()
        pkgver = pkgver or f"{var('grassfield-notes', 'pkgver')}-{var('grassfield-notes', 'pkgrel')}"
        d = pathlib.Path(self.tmp, "pkg")
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        (d / ".PKGINFO").write_text(f"pkgname = {name}\npkgver = {pkgver}\n")
        (d / ".BUILDINFO").write_text(f"format = 2\npkgname = {name}\npkgbuild_sha256sum = {pkgbuild_sum}\n")
        out = pathlib.Path(self.tmp, "p.pkg.tar.zst")
        subprocess.run(["bsdtar", "--zstd", "-cf", str(out), "-C", str(d), ".PKGINFO", ".BUILDINFO"], check=True)
        return out

    def check(self, pkg):
        return subprocess.run([str(ROOT / "scripts" / "app-check.sh"), str(pkg), str(self.app)], capture_output=True, text=True)

    def test_the_package_of_this_pkgbuild_is_reusable(self):
        r = self.check(self.package())
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_a_changed_pkgbuild_is_refused_until_pkgrel_changes(self):
        pkg = self.package()
        with open(self.app / "PKGBUILD", "a") as f:
            f.write("# a change\n")
        r = self.check(pkg)
        self.assertEqual(r.returncode, 1)
        self.assertIn("a changed PKGBUILD is a new pkgrel", r.stderr)

    def test_another_version_or_name_is_refused(self):
        self.assertEqual(self.check(self.package(pkgver="1.0.0.r1.gabcdef0-1")).returncode, 1)
        self.assertEqual(self.check(self.package(name="grassfield-sanaga")).returncode, 1)

    def test_an_unpinned_pkgbuild_is_refused(self):
        for old, new in (("sha256sums=('", "sha256sums=('SKIP' '"), ("_commit=2daf1c88", "_commit=2daf1c8\n#")):
            with self.subTest(new):
                shutil.copy(ROOT / "grassfield-notes" / "PKGBUILD", self.app / "PKGBUILD")
                body = (self.app / "PKGBUILD").read_text().replace(old, new, 1)
                (self.app / "PKGBUILD").write_text(body)
                r = self.check(self.package())
                self.assertEqual(r.returncode, 1, r.stderr)

    def test_usage(self):
        self.assertEqual(subprocess.run([str(ROOT / "scripts" / "app-check.sh")], capture_output=True).returncode, 2)


class Bump(unittest.TestCase):
    """scripts/bump-app.sh and the README's rule (the network part is run by the reviewer: --verify)."""

    def test_the_script_names_both_apps_and_refuses_what_is_not_a_full_descendant_commit(self):
        body = text("scripts/bump-app.sh")
        self.assertIn("grassfield-sanaga | grassfield-notes", body)
        self.assertIn("^[0-9a-f]{40}$", body)
        self.assertIn("is not on $app's main", body)
        self.assertIn("is not a descendant of the pinned", body)
        for field in ("_commit", "_rev", "_cargover", "sha256sums", "pkgrel"):
            self.assertRegex(body, rf'-e "s/\^{field}=')
        self.assertTrue(os.access(ROOT / "scripts" / "bump-app.sh", os.X_OK))

    def test_a_bad_commit_is_a_usage_error_before_any_network(self):
        for args in (["grassfield-sanaga", "a9e0e56"], ["grassfield-sanaga"], ["grassfield-other", "a" * 40], []):
            with self.subTest(args):
                r = subprocess.run([str(ROOT / "scripts" / "bump-app.sh")] + args, capture_output=True, text=True)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage", r.stderr)

    def test_the_readme_states_the_rule_and_the_one_off_removal(self):
        readme = text("README.md")
        self.assertIn("Bundled apps", readme)
        self.assertIn("scripts/bump-app.sh", readme)
        self.assertIn("pacman -Rns sanaga", readme)
        self.assertIn("reviewed", readme)


class SmokeTest(unittest.TestCase):
    def test_the_smoke_test_installs_the_apps_through_grassfield_desktops_depends(self):
        body = text("tests/smoke.sh")
        self.assertIn("grassfield-sanaga", body)
        self.assertIn("grassfield-notes", body)
        self.assertIn("Installed as a dependency for another package", body)
        self.assertIn("/usr/share/applications/sanaga.desktop", body)
        self.assertIn("pacman -Rns --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-sanaga grassfield-notes", body)


if __name__ == "__main__":
    unittest.main()
