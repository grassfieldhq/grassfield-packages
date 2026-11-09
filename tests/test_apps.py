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


def code(body):
    """A script without its comment lines: what runs, not what is said about it."""
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


class PinCheck(unittest.TestCase):
    """scripts/pin-check.sh: one full commit, one real SHA-256, nothing that could bring other bytes or code."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = pathlib.Path(self.tmp, "app")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_check(self, extra="", app="grassfield-notes", sub=None):
        shutil.rmtree(self.app, ignore_errors=True)
        self.app.mkdir()
        body = (ROOT / app / "PKGBUILD").read_text()
        for old, new in (sub or {}).items():
            self.assertIn(old, body)
            body = body.replace(old, new, 1)
        (self.app / "PKGBUILD").write_text(body + extra)
        return subprocess.run([str(ROOT / "scripts" / "pin-check.sh"), str(self.app)], capture_output=True, text=True)

    def test_both_real_pkgbuilds_are_pinned(self):
        for app in APPS:
            self.assertEqual(self.run_check(app=app).returncode, 0, app)

    def test_every_way_to_bring_other_bytes_or_code_is_refused(self):
        sha = "b" * 64
        cases = {
            "SKIP": ({"sha256sums=('": "sha256sums=('SKIP' '"}, ""),
            "a short commit": ({"_commit=2daf1c88": "_commit=2daf1c8\n#"}, ""),
            # Mutant M4 of the review: makepkg honours the architecture-suffixed arrays.
            "a per-architecture git source": ("", "source_x86_64=('extra::git+https://example.invalid/x#branch=main')\n"
                                                  "sha256sums_x86_64=('SKIP')\n"),
            "a per-architecture checksum alone": ("", "sha256sums_x86_64=('SKIP')\n"),
            "a second source": ("", "source+=('other.tar.gz::https://example.invalid/o.tar.gz')\n"),
            "another checksum algorithm": ("", f"b2sums=('{'0' * 128}')\n"),
            "a git source in place of the archive": ({'"$pkgname-$_commit.tar.gz::https://github.com/grassfieldhq/$_app/archive/$_commit.tar.gz"': '"git+https://github.com/grassfieldhq/$_app.git#commit=$_commit"'}, ""),
            "another host": ({'.tar.gz::https://github.com/grassfieldhq/$_app': '.tar.gz::https://github.com/someone/$_app'}, ""),
            "an install script": ("", "install=app.install\n"),
            "replaces": ("", "replaces=(sanaga)\n"),
        }
        for why, (sub, extra) in cases.items():
            with self.subTest(why):
                r = self.run_check(extra, sub=sub if sub else None)
                self.assertEqual(r.returncode, 1, r.stderr)

    def test_a_per_architecture_array_is_refused_for_sanaga_too(self):
        self.assertEqual(self.run_check("source_aarch64=('x')\n", app="grassfield-sanaga").returncode, 1)


def fake_package(out, app, pkgbuild=None, extra_paths=(), extra_info="", pkgbuild_sum=None, drop=(), symlink=None,
                 mode=None):
    """A package as makepkg would write it for an app folder of this repository, from its real PKGBUILD's values, with
    the changes a test asks for. Returns its path."""
    pkgbuild = pathlib.Path(pkgbuild or ROOT / app / "PKGBUILD")
    name = var(app, "pkgname")
    ver = f"{var(app, 'pkgver')}-{var(app, 'pkgrel')}"
    binary = "sanaga" if app == "grassfield-sanaga" else "grassfield-notes"
    d = pathlib.Path(out, f"root-{app}-{os.urandom(3).hex()}")
    d.mkdir(parents=True)
    files = {f"usr/bin/{binary}": "#!/bin/sh\n", f"usr/share/applications/{binary}.desktop": "[Desktop Entry]\n",
             f"usr/share/licenses/{name}/LICENSE": "MIT\n", f"usr/share/icons/hicolor/48x48/apps/{binary}.png": "png"}
    for p in extra_paths:
        files[p] = "x"
    for p in drop:
        files.pop(p, None)
    for p, content in files.items():
        f = d / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        f.chmod(0o755 if p.startswith("usr/bin/") else 0o644)
    for p in sorted(d.rglob("*")):
        if p.is_dir():
            p.chmod(0o755)
    if symlink:
        (d / symlink).parent.mkdir(parents=True, exist_ok=True)
        os.symlink("/etc/passwd", d / symlink)
    if mode:
        (d / mode[0]).chmod(mode[1])
    deps = [f"depend = {x}" for x in pkgbuild_vars(app, "depends").split()]
    opt = [f"optdepend = {x}" for x in pkgbuild_vars(app, "optdepends").splitlines() if x]
    prov = [f"provides = {x}" for x in pkgbuild_vars(app, "provides").split()]
    conf = [f"conflict = {x}" for x in pkgbuild_vars(app, "conflicts").split()]
    info = "\n".join([f"pkgname = {name}", f"pkgbase = {name}", f"pkgver = {ver}", "pkgdesc = x", "arch = x86_64",
                      "license = MIT", "builddate = 1", "packager = t", "size = 4"] + deps + opt + prov + conf) + "\n"
    (d / ".PKGINFO").write_text(info + extra_info)
    digest = pkgbuild_sum or hashlib.sha256(pkgbuild.read_bytes()).hexdigest()
    (d / ".BUILDINFO").write_text(f"format = 2\npkgname = {name}\npkgbuild_sha256sum = {digest}\n")
    (d / ".MTREE").write_text("#mtree\n")
    package = pathlib.Path(out, f"{name}-{ver}-x86_64.pkg.tar.zst")
    top = sorted(x.name for x in d.iterdir())
    subprocess.run(["bsdtar", "--zstd", "-cf", str(package), "-C", str(d)] + top, check=True)
    shutil.rmtree(d)
    return package


@unittest.skipUnless(HAVE_BSDTAR, "needs bsdtar (libarchive)")
class AppCheck(unittest.TestCase):
    """scripts/app-check.sh on small fake packages: what may be signed, installed and reused."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, pkg, app="grassfield-notes"):
        return subprocess.run([str(ROOT / "scripts" / "app-check.sh"), str(pkg), str(ROOT / app)], capture_output=True, text=True)

    def test_the_package_of_this_pkgbuild_passes(self):
        for app in APPS:
            r = self.check(fake_package(self.tmp, app), app)
            self.assertEqual((r.returncode, r.stderr), (0, ""), app)

    def test_a_changed_pkgbuild_is_refused_until_pkgrel_changes(self):
        r = self.check(fake_package(self.tmp, "grassfield-notes", pkgbuild_sum="0" * 64))
        self.assertEqual(r.returncode, 1)
        self.assertIn("a changed PKGBUILD is a new pkgrel", r.stderr)

    def test_paths_that_could_run_code_or_leave_the_app_are_refused(self):
        cases = {
            "an install script": dict(extra_paths=[".INSTALL"]),
            "a libalpm hook": dict(extra_paths=["usr/share/libalpm/hooks/evil.hook"]),
            "a file in /etc": dict(extra_paths=["etc/pacman.d/hook"]),
            "a unit under usr/lib": dict(extra_paths=["usr/lib/systemd/system/x.service"]),
            "a folder under usr/bin": dict(extra_paths=["usr/bin/dir/x"]),
            "a link": dict(symlink="usr/share/doc/link"),
            "a setuid binary": dict(mode=("usr/bin/grassfield-notes", 0o4755)),
            "no binary": dict(drop=["usr/bin/grassfield-notes"]),
            "no desktop file": dict(drop=["usr/share/applications/grassfield-notes.desktop"]),
        }
        for why, kw in cases.items():
            with self.subTest(why):
                r = self.check(fake_package(self.tmp, "grassfield-notes", **kw))
                self.assertEqual(r.returncode, 1, r.stderr)

    def test_pkginfo_fields_and_dependency_lines_are_the_pkgbuilds(self):
        for why, extra in (("replaces", "replaces = pacman\n"), ("a group", "group = base\n"), ("a backup file", "backup = etc/x\n"),
                           ("another dependency", "depend = evil\n"), ("another provides", "provides = pacman\n")):
            with self.subTest(why):
                r = self.check(fake_package(self.tmp, "grassfield-notes", extra_info=extra))
                self.assertEqual(r.returncode, 1, r.stderr)

    def test_another_version_or_name_is_refused(self):
        pkg = fake_package(self.tmp, "grassfield-notes")
        self.assertEqual(self.check(pkg, "grassfield-sanaga").returncode, 1)

    def test_an_unpinned_pkgbuild_is_refused(self):
        app = pathlib.Path(self.tmp, "grassfield-notes")
        shutil.copytree(ROOT / "grassfield-notes", app)
        body = (app / "PKGBUILD").read_text() + "sha256sums_x86_64=('SKIP')\n"
        (app / "PKGBUILD").write_text(body)
        pkg = fake_package(self.tmp, "grassfield-notes", pkgbuild=app / "PKGBUILD")
        r = subprocess.run([str(ROOT / "scripts" / "app-check.sh"), str(pkg), str(app)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_usage(self):
        self.assertEqual(subprocess.run([str(ROOT / "scripts" / "app-check.sh")], capture_output=True).returncode, 2)


@unittest.skipUnless(HAVE_BSDTAR, "needs bsdtar (libarchive)")
class AppIngest(unittest.TestCase):
    """scripts/app-ingest.sh: the one package build-channel.sh ships. Reuse and the fresh path, run for real."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.apps, self.tree, self.out = (self.tmp / n for n in ("apps", "tree", "out"))
        for d in (self.apps, self.tree, self.out):
            d.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ingest(self, app="grassfield-notes"):
        return subprocess.run([str(ROOT / "scripts" / "app-ingest.sh"), app, str(self.apps), str(self.tree), str(self.out)],
                              capture_output=True, text=True)

    def test_a_package_from_the_apps_folder_is_taken_after_the_check(self):
        pkg = fake_package(self.apps, "grassfield-notes")
        r = self.ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("built "))
        self.assertTrue((self.out / pkg.name).is_file())
        self.assertFalse((self.out / (pkg.name + ".sig")).exists())

    def test_nothing_in_the_apps_folder_and_nothing_in_the_tree_is_refused(self):
        r = self.ingest()
        self.assertEqual(r.returncode, 1)
        self.assertIn("build it first with scripts/build-app.sh", r.stderr)

    def test_a_package_that_fails_the_check_is_never_taken(self):
        fake_package(self.apps, "grassfield-notes", extra_paths=[".INSTALL"])
        r = self.ingest()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_link_in_place_of_the_package_is_not_followed(self):
        pkg = fake_package(self.tmp, "grassfield-notes")
        os.symlink(pkg, self.apps / pkg.name)
        self.assertEqual(self.ingest().returncode, 1)

    def test_the_package_already_in_the_tree_is_reused_with_its_signature(self):
        # A release build of an earlier tag holds it; the apps folder holds nothing (the tree stands in for it).
        pkg = fake_package(self.tree, "grassfield-notes")
        (self.tree / (pkg.name + ".sig")).write_bytes(b"sig")
        r = self.ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("reused "))
        self.assertEqual((self.out / pkg.name).read_bytes(), pkg.read_bytes())
        self.assertEqual((self.out / (pkg.name + ".sig")).read_bytes(), b"sig")

    def test_reuse_wins_over_a_newer_build_of_the_same_name(self):
        reused = fake_package(self.tree, "grassfield-notes")
        (self.tree / (reused.name + ".sig")).write_bytes(b"sig")
        fake_package(self.apps, "grassfield-notes")  # different bytes (builddate is the same, the order of entries not)
        r = self.ingest()
        self.assertTrue(r.stdout.startswith("reused "), r.stdout)
        self.assertEqual((self.out / reused.name).read_bytes(), reused.read_bytes())

    def test_a_reused_package_without_its_signature_is_refused(self):
        fake_package(self.tree, "grassfield-notes")
        r = self.ingest()
        self.assertEqual(r.returncode, 1)
        self.assertIn("has no signature", r.stderr)

    def test_a_reused_package_of_another_pkgbuild_is_refused_not_replaced(self):
        # Same name, built from a PKGBUILD that is no longer this one: a changed PKGBUILD is a new pkgrel.
        pkg = fake_package(self.tree, "grassfield-notes", pkgbuild_sum="1" * 64)
        (self.tree / (pkg.name + ".sig")).write_bytes(b"sig")
        fake_package(self.apps, "grassfield-notes")
        r = self.ingest()
        self.assertEqual(r.returncode, 1)
        self.assertIn("a changed PKGBUILD is a new pkgrel", r.stderr)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_the_sanaga_package_goes_the_same_way(self):
        pkg = fake_package(self.apps, "grassfield-sanaga")
        r = self.ingest("grassfield-sanaga")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.out / pkg.name).is_file())


class Isolation(unittest.TestCase):
    """Review of PR #22, finding 1: a crate's build code must not reach the build that the project's key signs."""

    def setUp(self):
        self.channel = text("scripts/build-channel.sh")
        self.app = code(text("scripts/build-app.sh"))
        self.workflow = text(".github/workflows/build.yml")

    def test_build_channel_never_builds_or_runs_an_app(self):
        # Neither makepkg nor cargo nor a run of anything from the apps appears in its app handling.
        block = code(self.channel[self.channel.index("# The bundled apps (ADR-0055)"):self.channel.index('step "makepkg (grassfield\'s packaging')])
        self.assertNotRegex(block, r"makepkg|cargo|runuser|bsdtar -x")
        self.assertIn("app-ingest.sh", block)
        # Installed only after the check (app-ingest.sh runs app-check.sh), and with the scriptlets off.
        self.assertIn("pacman -U --noscriptlet --noconfirm", block)
        self.assertNotRegex(block, r"pacman -U --noconfirm")
        self.assertIn('--apps) apps_dir=$2', self.channel)
        self.assertIn("--no-apps", self.channel)

    def test_the_app_container_has_no_sudoers_entry_and_a_fresh_environment(self):
        self.assertNotIn("90-builder", self.app.replace("rm -f /etc/sudoers.d/90-builder", ""))
        self.assertNotRegex(self.app, r"NOPASSWD|printf 'builder ALL")
        self.assertIn("rm -f /etc/sudoers.d/90-builder", self.app)
        self.assertIn('! runuser -u builder -- sudo -n true', self.app)  # refuses the build if builder could sudo
        # The dependencies come first, as root; makepkg (without -s: it never calls pacman) after, as builder.
        self.assertLess(self.app.index("pacman -S --noconfirm --needed"), self.app.index("makepkg -c --noconfirm"))
        self.assertNotRegex(self.app, r"makepkg -[a-z]*s[a-z]* ")
        self.assertIn("env -i HOME=/home/builder", self.app)
        # Only the package leaves; the pin and the checks come before any third-party code.
        self.assertIn("install -m644 \"${built[0]}\" \"$out/\"", self.app)
        self.assertLess(self.app.index("pin-check.sh"), self.app.index("makepkg -c --noconfirm"))
        self.assertLess(self.app.index("bump-app.sh\" --verify"), self.app.index("makepkg -c --noconfirm"))

    def test_the_containers_share_no_home_srcdest_or_writable_folder(self):
        steps = re.findall(r"docker run[^\n]*\\\n[^\n]*", self.workflow)
        app_run = next(s for s in steps if "build-app.sh" in s)
        desktop_run = next(s for s in steps if "-v \"$PWD/grassfield:/grassfield:ro\"" in s)
        # Different container invocations, each with its own filesystem: HOME (/home/builder) and SRCDEST (/build/srcdest)
        # live inside each and are shared by none; the only writable mount of an app container is its own out folder.
        self.assertIsNot(app_run, desktop_run)
        mounts = re.findall(r'-v "([^"]+)"', app_run)
        self.assertEqual(sorted(m.split(":", 1)[1] for m in mounts), ["/out", "/packages:ro"])
        self.assertNotIn("/home", app_run + desktop_run)
        self.assertNotIn("/build/srcdest", app_run + desktop_run)
        self.assertNotIn("--network host", app_run)
        # The desktop's container sees the apps read-only, and the channel script is told to take them.
        self.assertIn('"$PWD/apps/all:/apps:ro"', desktop_run)
        self.assertIn("--apps /apps", self.workflow)
        # The app step comes before the desktop's, and the desktop's container has no build-app.sh in it.
        self.assertLess(self.workflow.index("/packages/scripts/build-app.sh"), self.workflow.index("/packages/scripts/build-channel.sh"))
        self.assertNotIn("build-app.sh", desktop_run)

    def test_the_build_job_still_builds_the_ref_in_its_own_step(self):
        self.assertIn('-e REF -e PKGREL', self.workflow)

    def test_the_network_limit_is_stated_not_claimed(self):
        self.assertIn("The network stays on", text("scripts/build-app.sh"))
        self.assertIn("not a barrier for a build script or a test", text("scripts/build-app.sh"))


class BuildChannel(unittest.TestCase):
    """scripts/build-channel.sh: both apps in every release build, signed, before the desktop."""

    def setUp(self):
        self.script = text("scripts/build-channel.sh")

    def test_it_names_both_apps_and_takes_them_before_the_desktop(self):
        self.assertIn("apps=(grassfield-sanaga grassfield-notes)", self.script)
        self.assertLess(self.script.index('for a in "${apps[@]}"; do ingest_app "$a"; done'),
                        self.script.index('step "makepkg (grassfield\'s packaging/arch/PKGBUILD)"'))
        self.assertIn('sign "$pkg"', self.script)

    def test_every_release_build_holds_them(self):
        self.assertIn("shipped=(\"$keyring_pkg\")", self.script)
        self.assertIn("shipped+=(\"$pkg\")", self.script)
        self.assertIn('for f in "${built[@]}" "${shipped[@]}"; do\n  info=', self.script)
        self.assertIn('printf \'%s\\n\' "${built[@]##*/}" "${shipped[@]##*/}"', self.script)
        self.assertIn('for f in "${built[@]}" "${shipped[@]}"; do cp "$f" "$f.sig" "$out/"; done', self.script)
        self.assertNotRegex(self.script, r'"\$keyring_pkg"; do')
        self.assertIn('echo "apps ${app_versions[*]}"', self.script)

    def test_a_reused_package_is_checked_against_the_key_and_the_pkgbuild(self):
        body = self.script[self.script.index("ingest_app() {"):self.script.index("mkdir -p /build/apps\n")]
        self.assertIn('[[ $signer == "$key" ]]', body)
        self.assertIn("app-ingest.sh", body)  # which runs app-check.sh on a reused and on a fresh package (AppIngest)

    def test_the_apps_are_never_a_secret_boundary(self):
        self.assertIn("GRASSFIELD_SIGNING_KEY", self.script)


class SignRelease(unittest.TestCase):
    """Review of PR #22, finding 4: a published package must still be the PKGBUILD's."""

    def test_prepare_checks_the_apps_it_ships_against_git(self):
        body = text("scripts/sign-release.sh")
        prepare = body[body.index("if [[ $mode == prepare ]]"):body.index("# sign: gpg only")]
        self.assertIn('"$self/app-check.sh" "${found[0]}" "$self/../$app"', prepare)
        # After the published package replaced the new build, before repo-add reads it.
        self.assertLess(prepare.index("the published file and its signature"), prepare.index("app-check.sh"))
        self.assertLess(prepare.index("app-check.sh"), prepare.index("repo-add --quiet"))

    def test_the_apps_names_pass_the_signers_allowlist_as_they_did(self):
        package = re.search(r"^PACKAGE='(.*)'$", text("scripts/sign-release.sh"), re.M).group(1)
        for name in APPS:
            ok = subprocess.run(["bash", "-c", '[[ $1 =~ $2 ]]', "_", f"{name}-1.0.0.r24.g2daf1c8-1-x86_64.pkg.tar.zst", package]).returncode
            self.assertEqual(ok, 0)


class Bump(unittest.TestCase):
    """scripts/bump-app.sh and the README's rule; CI runs --verify (catalog.yml, build-app.sh)."""

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

    def test_ci_checks_the_pin_against_the_network(self):
        catalog_yml = text(".github/workflows/catalog.yml")
        self.assertIn("scripts/bump-app.sh --verify", catalog_yml)
        self.assertIn("grassfield-sanaga grassfield-notes", catalog_yml)
        self.assertIn('"$here/scripts/bump-app.sh" --verify "$app"', text("scripts/build-app.sh"))  # the signing path too

    def test_the_readme_states_the_rule_and_the_one_off_removal(self):
        readme = text("README.md")
        self.assertIn("Bundled apps", readme)
        self.assertIn("scripts/bump-app.sh", readme)
        self.assertIn("pacman -Rns sanaga", readme)
        self.assertIn("reviewed", readme)
        self.assertTrue("makepkg checks no checksum of a git source" not in readme)
        for app in APPS:
            self.assertNotIn("makepkg checks no\n# checksum of a git source", text(f"{app}/PKGBUILD"))


class SmokeTest(unittest.TestCase):
    def test_the_smoke_test_installs_the_apps_through_grassfield_desktops_depends(self):
        body = text("tests/smoke.sh")
        self.assertIn("grassfield-sanaga", body)
        self.assertIn("grassfield-notes", body)
        self.assertIn("Installed as a dependency for another package", body)
        self.assertIn("/usr/share/applications/sanaga.desktop", body)
        self.assertIn("pacman -Rns --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-sanaga grassfield-notes", body)

    def run_fn(self, answer):
        """smoke.sh's only_provided_by, against a fake `pacman -Qq NAME` that prints `answer` (a package that PROVIDES the
        name is what pacman -Q answers with, as `pacman -Q sh` prints bash)."""
        fn = re.search(r"^only_provided_by\(\) \{.*\}$", text("tests/smoke.sh"), re.M).group(0)
        script = f'pacman() {{ printf "%s\\n" "{answer}"; }}\n{fn}\nonly_provided_by sanaga grassfield-sanaga'
        return subprocess.run(["bash", "-c", script]).returncode

    def test_sanaga_must_be_answered_by_grassfield_sanaga_alone(self):
        self.assertEqual(self.run_fn("grassfield-sanaga"), 0)  # the positive case
        self.assertNotEqual(self.run_fn("sanaga"), 0)  # a real package named sanaga (the conflict the package declares)
        self.assertNotEqual(self.run_fn("bash"), 0)  # some other provider
        self.assertNotEqual(self.run_fn(""), 0)  # nothing installed
        self.assertNotIn("! pacman -Q sanaga", text("tests/smoke.sh"))


class Licenses(unittest.TestCase):
    """Review of PR #22, finding 11: the third-party licence list each package ships (the legal review is the owner's)."""

    def test_both_packages_list_their_crates_and_the_fonts_licences(self):
        for app in APPS:
            body = text(f"{app}/PKGBUILD")
            self.assertIn("cargo tree --frozen --offline", body)
            self.assertIn("THIRD-PARTY-LICENSES.txt", body)
            self.assertIn('_licenses "$pkgdir/usr/share/licenses/$pkgname"', body)
            self.assertIn("OFL", body)
            self.assertNotIn("cargo-license", body)  # no new tool

    @unittest.skipUnless(shutil.which("cargo") and shutil.which("rustc"), "needs cargo (the CI container has none)")
    def test_the_listing_runs_on_a_small_crate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dep = pathlib.Path(tmp, "dep")
            (dep / "src").mkdir(parents=True)
            (dep / "Cargo.toml").write_text('[package]\nname = "fontdep"\nversion = "0.3.1"\nedition = "2021"\nlicense = "OFL-1.1"\n')
            (dep / "src/lib.rs").write_text("")
            app = pathlib.Path(tmp, "app")
            (app / "src").mkdir(parents=True)
            (app / "Cargo.toml").write_text('[package]\nname = "app"\nversion = "1.0.0"\nedition = "2021"\nlicense = "MIT"\n'
                                             '[dependencies]\nfontdep = { path = "../dep" }\n')
            (app / "src/main.rs").write_text("fn main() {}\n")
            subprocess.run(["cargo", "generate-lockfile", "--offline"], cwd=app, check=True, capture_output=True)
            out = pathlib.Path(tmp, "out")
            script = f'pkgname=x pkgver=1; source <(sed -n "/^_licenses() {{/,/^}}$/p" {ROOT}/grassfield-notes/PKGBUILD); _licenses "{out}"'
            subprocess.run(["bash", "-c", script], cwd=app, check=True, capture_output=True)
            listing = (out / "THIRD-PARTY-LICENSES.txt").read_text()
            self.assertIn("fontdep 0.3.1  OFL-1.1", listing)
            self.assertIn("app 1.0.0  MIT", listing)


if __name__ == "__main__":
    unittest.main()
