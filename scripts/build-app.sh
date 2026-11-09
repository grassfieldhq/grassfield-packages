#!/usr/bin/env bash
# Build one bundled app (grassfield-sanaga or grassfield-notes) in its OWN throwaway container and hand on the one
# .pkg.tar.zst, nothing else (README.md, "Bundled apps"; review of grassfield-packages PR #22).
#
#   build-app.sh --app NAME --out DIR
#
# Why a container of its own: an app's build runs third-party code as an unprivileged user (800+ crates' build.rs and
# proc-macros, the app's tests and the binaries package() runs). It must not share a user, a HOME, a SRCDEST, a pacman or a
# sudoers line with the build that makepkg-s grassfield-desktop and whose package the project's key signs: one bad crate
# could write ~/.config/pacman/makepkg.conf, which makepkg sources as bash. So:
#   - the dependencies are installed here AS ROOT first (pacman -S of the PKGBUILD's depends, makedepends, checkdepends);
#   - then makepkg (without -s: it never calls pacman) runs as `builder`, who has NO sudoers entry, in a fresh HOME with a
#     scrubbed environment (nothing of the CI job's);
#   - only the package file leaves, through --out; build-channel.sh (another container) takes it through
#     scripts/app-ingest.sh and scripts/app-check.sh before it signs or installs anything (no scriptlet, allowed paths only).
# Before anything is built: scripts/pin-check.sh (the PKGBUILD's pin) and `bump-app.sh --verify` (the pin is on the app's
# main and the archive's checksum is the one the PKGBUILD says; this container has the network).
# The network stays on: pacman, `cargo fetch --locked` in prepare() and the source download need it, and one container
# cannot cut it for cargo alone (unshare needs privileges Docker does not give). `--frozen` makes cargo itself offline
# but is not a barrier for a build script or a test. The container holds no secret and no key and is gone afterwards.
# Runs only as root inside a throwaway Arch container (it refuses elsewhere). Exit 0, 1 failed, 2 usage.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
app="" out=""
usage() { echo "usage: build-app.sh --app grassfield-sanaga|grassfield-notes --out DIR" >&2; exit 2; }
die() { echo "build-app.sh: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in --app) app=$2 ;; --out) out=$2 ;; *) usage ;; esac
  shift 2
done
case $app in grassfield-sanaga | grassfield-notes) ;; *) usage ;; esac
[[ -d $out ]] || usage
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "build-app.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
[[ -z ${GRASSFIELD_SIGNING_KEY+x}${GRASSFIELD_SIGNING_PASSPHRASE+x} ]] || { echo "build-app.sh: refused: no key meets a build" >&2; exit 2; }
log=/build.log
mkdir -p /build/srcdest /build/pkgs
: >"$log"

echo "== the package set of an Omarchy stable machine (build/pacman.conf), as build-channel.sh has it"
install -m644 "$here/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux; } >>"$log" 2>&1 || die "pacman-key (see $log)"
"$here/scripts/omarchy-trust.sh" 2>>"$log" || die "cannot trust [omarchy]'s signer (see $log)"
pacman -Syu --noconfirm --needed base-devel git diffutils ttf-dejavu >>"$log" 2>&1 || { tail -n 20 "$log"; die "pacman -Syu (see $log)"; }
mkdir -p /etc/makepkg.conf.d
printf 'COMPRESSZST=(zstd -c -T0 -3 -)\n' >/etc/makepkg.conf.d/grassfield.conf

echo "== the pin of $app"
"$here/scripts/pin-check.sh" "$here/$app" || die "$app/PKGBUILD is not pinned"
"$here/scripts/bump-app.sh" --verify "$app" || die "the pin of $app is not the network's (on the app's main, this checksum)"

echo "== dependencies, as root, before any third-party code runs"
mapfile -t deps < <(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf "%s\n" "${depends[@]}" "${makedepends[@]}" "${checkdepends[@]}"' _ "$here/$app")
pacman -S --noconfirm --needed "${deps[@]}" >>"$log" 2>&1 || { tail -n 20 "$log"; die "pacman -S ${deps[*]} (see $log)"; }

echo "== makepkg as builder: no sudoers entry, a fresh HOME, a scrubbed environment"
id -u builder >/dev/null 2>&1 || useradd -m builder
rm -f /etc/sudoers.d/90-builder
# Nothing lets builder become root while cargo runs: no sudoers line names it or a group it is in.
if command -v sudo >/dev/null; then
  ! runuser -u builder -- sudo -n true 2>/dev/null || die "builder can sudo: refused"
fi
cp -a "$here/$app" /build/app
chown -R builder: /build/app /build/srcdest /build/pkgs
(cd /build/app && runuser -u builder -- env -i HOME=/home/builder PATH=/usr/local/bin:/usr/bin LANG=C.UTF-8 \
  SRCDEST=/build/srcdest PKGDEST=/build/pkgs makepkg -c --noconfirm 2>&1 | tee -a "$log" | tail -n 25) || die "makepkg $app failed (see $log)"

mapfile -t built < <(ls /build/pkgs/*.pkg.tar.zst)
((${#built[@]} == 1)) || die "makepkg wrote ${#built[@]} packages, one expected: ${built[*]##*/}"
"$here/scripts/app-check.sh" "${built[0]}" "$here/$app" || die "the package is not $app/PKGBUILD's"
install -m644 "${built[0]}" "$out/"
echo "done: ${built[0]##*/}"
