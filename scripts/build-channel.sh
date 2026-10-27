#!/usr/bin/env bash
# Build one Grassfield release: its release build for each channel it goes to, and a channel tree of the [grassfield]
# repository made from them (grassfield ADR-0033 e, f, g, h.2; ADR-0037 g).
#
#   build-channel.sh --source DIR --ref REF --tree DIR --gnupghome DIR --key FPR [--keyring DIR] [--pkgrel N]
#
#   --source DIR   a grassfield checkout with its history; it is cloned, nothing in it changes
#   --ref REF      the tag (or, for tests, the commit) to build; its VERSION decides the channels
#   --tree DIR     written in place (layout below); read for the current snapshots and for a grassfield-keyring built
#                  before
#   --gnupghome DIR, --key FPR
#                  a throwaway signing key, without a passphrase: builds and tests only. The project's key never meets a
#                  build (ADR-0033 b.7, review M1): the release job signs the tested release build in a container that
#                  runs no build (sign-release.sh). This script refuses to start while GRASSFIELD_SIGNING_KEY or
#                  GRASSFIELD_SIGNING_PASSPHRASE is set.
#   --keyring DIR  grassfield-keyring's sources (default: keyring/ here, keyless until O11; the tests pass their own)
#   --pkgrel N     GRASSFIELD_PKGREL: a rebuild of the same VERSION (O7), whose notes say "Rebuilt for Hyprland X.Y.Z"
#
# Runs only as root inside a throwaway Arch container (it refuses elsewhere): it replaces pacman.conf with Omarchy
# stable's package set (build/pacman.conf, ADR-0033 f), installs the build dependencies, creates the user `builder` and
# runs makepkg of grassfield's own packaging/arch/PKGBUILD (ADR-0023, the one build definition), after building and
# installing grassfield-keyring, which grassfield-desktop depends on.
#
# The tree:
#   releases/<channel>/<packages version>/   the release build, what the channel's one serialized publisher reads
#                                            (ADR-0037 g: each tag is built once, its packages, databases and notes kept
#                                            where the publisher reads them, never under the pointer): the packages and
#                                            their .sig, and grassfield.db, grassfield.files and grassfield-notes.json with
#                                            their .sig, a database of this release alone (the publisher takes it as is)
#   <channel>/x86_64/                        the channel as the hosting serves it (ADR-0033 g, h.2), for CI's artifacts
#                                            and the tests, made from the release builds by the channel's one publisher
#                                            (tools/publish.py, ADR-0037 g) in its local store:
#     <package>.pkg.tar.zst and .sig           immutable names: a file name never changes content
#     snap/<id>/grassfield.db, .files,         never a package older than the current snapshot's; the current
#       grassfield-notes.json, each with .sig, snapshot's other files kept (the catalog)
#       manifest.json
#     pointer                                  {"snapshot": "<id>"}, written last, only if it has not moved
#   build-<id>.txt                           the ref, commit, versions, Hyprland, the plugin's ABI stamp, pacman -Q
# A suffixed VERSION (-betaN, -rcN) goes to beta only (O15); a plain one to stable and beta, whose snapshot keeps a
# grassfield-desktop that is not older (macOS model, P4). Only packages named grassfield-* without replaces= enter (b.6).
# The release notes come from the ref's packaging/release-notes/<VERSION>.{en,fr}.txt (O9; en required), followed by the
# channel's earlier releases from the ref's own tags (notes.py --history). grassfield-keyring is built once per version:
# every release's database names it and a package file name never changes content, so one already in the tree is used
# again with its signature (the published one, once publishing is enabled).
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
source_dir="" ref="" tree="" gnupghome="" key="" keyring=$here/keyring pkgrel=""
usage() {
  echo "usage: build-channel.sh --source DIR --ref REF --tree DIR --gnupghome DIR --key FPR [--keyring DIR] [--pkgrel N]" >&2
  exit 2
}
die() {
  echo "build-channel.sh: $*" >&2
  exit 1
}
step() { printf '\n== %s\n' "$*"; }

while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --source) source_dir=$2 ;;
    --ref) ref=$2 ;;
    --tree) tree=$2 ;;
    --gnupghome) gnupghome=$2 ;;
    --key) key=$2 ;;
    --keyring) keyring=$2 ;;
    --pkgrel) pkgrel=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $source_dir && -n $ref && -n $tree && -n $gnupghome && -n $key ]] || usage
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "build-channel.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
[[ -z ${GRASSFIELD_SIGNING_KEY+x}${GRASSFIELD_SIGNING_PASSPHRASE+x} ]] ||
  { echo "build-channel.sh: refused: the project's key never meets a build; sign the tested release build with sign-release.sh" >&2; exit 2; }
[[ -z $pkgrel || $pkgrel =~ ^[1-9][0-9]*$ ]] || die "--pkgrel must be a positive integer"
[[ $key =~ ^[0-9A-F]{40}$ ]] || die "--key must be a full fingerprint (40 upper-case hex digits)"
mkdir -p /build "$tree"
log=/build/build.log
: >"$log"

sign() { # file -> file.sig, detached and binary, by the throwaway key
  gpg --homedir "$gnupghome" --batch --no-tty --pinentry-mode loopback --passphrase '' --local-user "$key!" --detach-sign \
    --no-armor --yes --output "$1.sig" "$1" 2>>"$log" </dev/null || die "cannot sign $1 (see $log)"
}

step "the package set of an Omarchy stable machine (build/pacman.conf)"
install -m644 "$here/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux; } >>"$log" 2>&1 || die "pacman-key (see $log)"
pacman -Syu --noconfirm --needed base-devel git diffutils >>"$log" 2>&1 || die "pacman -Syu base-devel git diffutils (see $log)"
id -u builder >/dev/null 2>&1 || useradd -m builder
printf 'builder ALL=(root) NOPASSWD: /usr/bin/pacman\n' >/etc/sudoers.d/90-builder
chmod 440 /etc/sudoers.d/90-builder
gpg --homedir "$gnupghome" --batch --no-tty --list-secret-keys "$key" >/dev/null 2>&1 || die "no secret key $key in $gnupghome"

step "grassfield at $ref"
rm -rf /build/src /build/pkgs /build/keyring /build/unsigned
git config --global --add safe.directory '*'   # the source is another user's checkout, mounted read-only
git clone --quiet --no-local --no-checkout "$source_dir" /build/src
git -C /build/src -c advice.detachedHead=false checkout --quiet --detach "$ref" || die "cannot check $ref out"
commit=$(git -C /build/src rev-parse HEAD)
version=$(tr -d '[:space:]' </build/src/VERSION)
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(beta|rc)[1-9][0-9]*)?$ ]] || die "VERSION '$version' is not X.Y.Z, X.Y.Z-betaN or X.Y.Z-rcN (ADR-0033 e)"
# A tag names its VERSION: vX.Y.Z[-betaN|-rcN].
[[ ! $ref =~ ^v[0-9] || $ref == "v$version" ]] || die "tag $ref does not match VERSION $version"
if [[ $version == *-* ]]; then channels=(beta); else channels=(stable beta); fi
committed_rel=$(cd /build/src/packaging/arch && env -u GRASSFIELD_PKGREL bash -c 'source ./PKGBUILD >/dev/null 2>&1; printf %s "$pkgrel"')
full=${version//-/}-${pkgrel:-$committed_rel}
echo "commit $commit, VERSION $version, packages $full, channels ${channels[*]}"
notes=()
if [[ -z $pkgrel ]]; then
  n=/build/src/packaging/release-notes/$version
  [[ -f $n.en.txt ]] || die "$n.en.txt is missing: every release has notes (ADR-0033 g, O9)"
  notes=(--en "$n.en.txt")
  [[ -f $n.fr.txt ]] && notes+=(--fr "$n.fr.txt")
fi

step "grassfield-keyring"
cp -a "$keyring" /build/keyring
chown -R builder: /build/keyring
kv=$(cd /build/keyring && bash -c 'source ./PKGBUILD >/dev/null 2>&1; printf %s-%s "$pkgver" "$pkgrel"')
keyring_pkg=/build/keyring/grassfield-keyring-$kv-any.pkg.tar.zst
reused=$(find "$tree" -type f -name "${keyring_pkg##*/}" -print -quit)
if [[ -n $reused ]]; then
  [[ -f $reused.sig ]] || die "$reused has no signature"
  cp "$reused" "$reused.sig" /build/keyring/
  signer=$(gpg --homedir "$gnupghome" --batch --no-tty --status-fd 1 --verify "$keyring_pkg.sig" "$keyring_pkg" 2>>"$log" |
    awk '$2 == "VALIDSIG" { print $12 }' || true)
  [[ $signer == "$key" ]] || die "$reused is not signed by $key"
  for f in grassfield.gpg grassfield-trusted grassfield-revoked; do
    bsdtar -xOf "$keyring_pkg" "usr/share/grassfield/pacman-keyring/$f" | cmp -s - "/build/keyring/$f" ||
      die "keyring/$f is not what grassfield-keyring $kv holds: a changed keyring is a new pkgver (keyring/PKGBUILD)"
  done
  echo "grassfield-keyring $kv: the one built before, used again ($reused)"
else
  (cd /build/keyring && runuser -u builder -- makepkg -f --noconfirm >>"$log" 2>&1) || die "makepkg grassfield-keyring (see $log)"
  [[ -f $keyring_pkg ]] || die "makepkg did not write ${keyring_pkg##*/}"
  sign "$keyring_pkg"
fi
# makepkg -s below must find grassfield-desktop's dependency; this keyring's install trusts nothing here (no grassfield.conf).
# Installed from a copy without its .sig: pacman checks a signature found beside a file, and the build machine does not
# trust the signing key.
mkdir -p /build/unsigned && cp "$keyring_pkg" /build/unsigned/
pacman -U --noconfirm "/build/unsigned/${keyring_pkg##*/}" >>"$log" 2>&1 || die "pacman -U grassfield-keyring (see $log)"
# The trust anchor (ADR-0033 g): the key this ref pins is in the keyring it ships with.
pinned=$(sed -n 's/^GRASSFIELD_SIGNING_FINGERPRINT=//p' /build/src/packaging/pacman/repository.conf 2>/dev/null || true)
if [[ -n $pinned ]]; then
  grep -q "^$pinned:" /build/keyring/grassfield-trusted || die "the pinned key $pinned is not in grassfield-keyring's trusted list"
  kh=$(mktemp -d)
  gpg --homedir "$kh" --batch --no-tty --with-colons --show-keys /build/keyring/grassfield.gpg 2>/dev/null |
    awk -F: '$1=="pub"{p=1;next} $1=="fpr"&&p{print $10} {p=0}' | grep -qx "$pinned" || die "the pinned key $pinned is not in grassfield.gpg"
  rm -rf "$kh"
  echo "trust anchor: $pinned is in grassfield-keyring"
else
  echo "trust anchor: this ref pins no key yet (owner decision O11): nothing to check"
fi

step "makepkg (grassfield's packaging/arch/PKGBUILD)"
mkdir -p /build/srcdest /build/pkgs
chown -R builder: /build/src /build/srcdest /build/pkgs
env_args=(SRCDEST=/build/srcdest PKGDEST=/build/pkgs)
[[ -n $pkgrel ]] && env_args+=(GRASSFIELD_PKGREL="$pkgrel")
(cd /build/src/packaging/arch && runuser -u builder -- env "${env_args[@]}" makepkg -s --noconfirm --needed >>"$log" 2>&1) ||
  { tail -n 30 "$log"; die "makepkg failed (see $log)"; }
mapfile -t built < <(ls /build/pkgs/*.pkg.tar.zst)
for f in "${built[@]}" "$keyring_pkg"; do
  info=$(bsdtar -xOf "$f" .PKGINFO)
  name=$(sed -n 's/^pkgname = //p' <<<"$info")
  [[ $name == grassfield-* ]] || die "$(basename "$f"): $name is not named grassfield-* (ADR-0033 b.6)"
  ! grep -q '^replaces = ' <<<"$info" || die "$(basename "$f"): replaces= is not allowed in the channel (ADR-0033 b.6)"
done
for f in "${built[@]}"; do sign "$f"; done
printf '%s\n' "${built[@]##*/}" "${keyring_pkg##*/}"
hyprland=$(pacman -Q hyprland 2>/dev/null | awk '{print $2}') || true
[[ -n $hyprland ]] || die "hyprland is not installed after makepkg -s: no version for the build record and the rebuild notes"
# A pkgrel rebuild (O7) says which Hyprland it was rebuilt for: the one makepkg -s installed, without its pkgrel.
[[ -z $pkgrel ]] || notes=(--rebuilt-for "${hyprland%-*}")

release_build() { # channel -> releases/<channel>/<packages version>/, a database of this release alone
  local c=$1 out=$tree/releases/$1/$full work f
  [[ ! -e $out ]] || die "$out exists already: each release is built once"
  mkdir -p "$out"
  for f in "${built[@]}" "$keyring_pkg"; do cp "$f" "$f.sig" "$out/"; done
  work=$(mktemp -d /build/db.XXXXXX)
  # Without --include-sigs, repo-add records no signature: pacman fetches each package's .sig beside it. The databases
  # are signed below, by the same key.
  (cd "$out" && repo-add --quiet "$work/grassfield.db.tar.gz" ./*.pkg.tar.zst) >>"$log" 2>&1 || die "repo-add $c (see $log)"
  cp -L "$work/grassfield.db.tar.gz" "$out/grassfield.db"
  cp -L "$work/grassfield.files.tar.gz" "$out/grassfield.files"
  rm -rf "$work"
  python3 -I "$here/scripts/notes.py" --channel "$c" --version "$full" --date "$(date -u +%F)" "${notes[@]}" \
    --history /build/src >"$out/grassfield-notes.json" || die "release notes for $c"
  for f in grassfield.db grassfield.files grassfield-notes.json; do sign "$out/$f"; done
  echo "$c: release build $full ($(python3 -I -c 'import json, sys; print(" ".join(r["version"] for r in json.load(open(sys.argv[1]))["releases"]))' "$out/grassfield-notes.json") in its notes)"
}

# The publisher checks every release file against a keyring folder: for this tree, the key that signed it (a throwaway
# one; the real publisher checks against grassfield-keyring's files, the project's key).
treekeys=$(mktemp -d)
gpg --homedir "$gnupghome" --batch --no-tty --export "$key" >"$treekeys/grassfield.gpg" 2>>"$log"
printf '%s:4:\n' "$key" >"$treekeys/grassfield-trusted"
: >"$treekeys/grassfield-revoked"
publish() { # channel: the channel's one publisher on this tree (tools/publish.py, ADR-0037 g), from its release builds
  local c=$1 out rc=0
  out=$(python3 -I "$here/tools/publish.py" --store "$tree" --channel "$c" --releases "$tree/releases/$c" \
    --keyring-dir "$treekeys" 2>&1) || rc=$?
  printf '%s\n' "$out" | sed "s/^/$c: /"
  ((rc == 0)) || die "$c: tools/publish.py exit $rc"
  [[ $out =~ snapshot\ ([0-9]{8}T[0-9]{6}Z-[0-9a-f]{12})\ \( ]] && updated+=("$c:${BASH_REMATCH[1]}")
  return 0
}

step "the release builds"
for c in "${channels[@]}"; do release_build "$c"; done
step "the channels"
updated=()
for c in "${channels[@]}"; do publish "$c"; done
abi=$(bsdtar -xOf /build/pkgs/grassfield-compositor-*.pkg.tar.zst usr/lib/grassfield/grassfield-compositor.abi 2>/dev/null | head -n 1 || true)
{
  echo "ref $ref"
  echo "commit $commit"
  echo "version $version"
  echo "packages $full"
  echo "keyring $kv${reused:+ (built before)}"
  echo "releases ${channels[*]/%//$full}"
  echo "snapshots ${updated[*]:-none}"
  echo "signing-key $key"
  echo "hyprland $hyprland"
  echo "plugin-abi ${abi:-unknown}"
  echo "package-set:"
  pacman -Q
} >"$tree/build-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}.txt"
echo "done: ${updated[*]:-no channel changed}"
