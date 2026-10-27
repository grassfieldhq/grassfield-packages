#!/usr/bin/env bash
# Build one Grassfield release into the channel tree of the [grassfield] repository (grassfield ADR-0033 e, f, g, h.2).
#
#   build-channel.sh --source DIR --ref REF --tree DIR --gnupghome DIR --key FPR [--keyring DIR] [--pkgrel N]
#
#   --source DIR   a grassfield checkout with its history; it is cloned, nothing in it changes
#   --ref REF      the tag (or, for tests, the commit) to build; its VERSION decides the channels
#   --tree DIR     the channel tree: read for the current snapshots, written in place (layout below)
#   --gnupghome DIR, --key FPR
#                  the signing key: a throwaway one in builds and tests, so CI artifacts are never signed by the project's
#                  key; the owner's key only in the signing job, after M5 (ADR-0033 b.7). A passphrase, when the key has
#                  one, comes from GRASSFIELD_SIGNING_PASSPHRASE.
#   --keyring DIR  grassfield-keyring's sources (default: keyring/ here, keyless until O11; the tests pass their own)
#   --pkgrel N     GRASSFIELD_PKGREL: a rebuild of the same VERSION (O7), whose notes say "Rebuilt for Hyprland X.Y.Z"
#
# Runs only as root inside a throwaway Arch container (it refuses elsewhere): it replaces pacman.conf with Omarchy
# stable's package set (build/pacman.conf, ADR-0033 f), installs the build dependencies, creates the user `builder` and
# runs makepkg of grassfield's own packaging/arch/PKGBUILD (ADR-0023, the one build definition), after building and
# installing grassfield-keyring, which grassfield-desktop depends on.
#
# The tree, per channel (stable, beta), as the hosting serves it (ADR-0033 g, h.2):
#   <channel>/x86_64/<package>.pkg.tar.zst and .sig    immutable names: a file name never changes content
#   <channel>/x86_64/snap/<id>/grassfield.db and .sig, grassfield.files and .sig, grassfield-notes.json and .sig
#   <channel>/x86_64/pointer                           the current snapshot's id, written last (the edge rule's pointer)
#   build-<id>.txt                                     the ref, commit, versions, Hyprland, the plugin's ABI stamp, pacman -Q
# A suffixed VERSION (-betaN, -rcN) goes to beta only (O15); a plain one to stable, and to beta unless beta already holds
# a grassfield-desktop that is not older (macOS model; repo-add --prevent-downgrade, P4). Only packages named
# grassfield-* without replaces= enter (b.6). The release notes come from the ref's packaging/release-notes/
# <VERSION>.{en,fr}.txt (O9; en required).
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
[[ -z $pkgrel || $pkgrel =~ ^[1-9][0-9]*$ ]] || die "--pkgrel must be a positive integer"
[[ $key =~ ^[0-9A-F]{40}$ ]] || die "--key must be a full fingerprint (40 upper-case hex digits)"
mkdir -p /build "$tree"
log=/build/build.log
: >"$log"

sign() { # file -> file.sig, detached and binary, by the signing key
  local pass=()
  [[ -n ${GRASSFIELD_SIGNING_PASSPHRASE:-} ]] && pass=(--pinentry-mode loopback --passphrase-fd 0)
  printf '%s' "${GRASSFIELD_SIGNING_PASSPHRASE:-}" |
    gpg --homedir "$gnupghome" --batch --no-tty "${pass[@]}" --local-user "$key!" --detach-sign --no-armor --yes \
      --output "$1.sig" "$1" 2>>"$log" || die "cannot sign $1 (see $log)"
}

step "the package set of an Omarchy stable machine (build/pacman.conf)"
install -m644 "$here/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux; } >>"$log" 2>&1 || die "pacman-key (see $log)"
pacman -Syu --noconfirm --needed base-devel git >>"$log" 2>&1 || die "pacman -Syu base-devel git (see $log)"
id -u builder >/dev/null 2>&1 || useradd -m builder
printf 'builder ALL=(root) NOPASSWD: /usr/bin/pacman\n' >/etc/sudoers.d/90-builder
chmod 440 /etc/sudoers.d/90-builder
gpg --homedir "$gnupghome" --batch --no-tty --list-secret-keys "$key" >/dev/null 2>&1 || die "no secret key $key in $gnupghome"

step "grassfield at $ref"
rm -rf /build/src /build/pkgs /build/keyring
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
if [[ -n $pkgrel ]]; then
  notes=(--rebuilt-for "$(pacman -Q hyprland | awk '{print $2}' | sed 's/-[^-]*$//')")
else
  n=/build/src/packaging/release-notes/$version
  [[ -f $n.en.txt ]] || die "$n.en.txt is missing: every release has notes (ADR-0033 g, O9)"
  notes=(--en "$n.en.txt")
  [[ -f $n.fr.txt ]] && notes+=(--fr "$n.fr.txt")
fi

step "grassfield-keyring"
cp -a "$keyring" /build/keyring
chown -R builder: /build/keyring
(cd /build/keyring && runuser -u builder -- makepkg -f --noconfirm >>"$log" 2>&1) || die "makepkg grassfield-keyring (see $log)"
keyring_pkg=$(ls /build/keyring/grassfield-keyring-*-any.pkg.tar.zst)
# makepkg -s below must find grassfield-desktop's dependency; this keyring's install trusts nothing here (no grassfield.conf).
pacman -U --noconfirm "$keyring_pkg" >>"$log" 2>&1 || die "pacman -U grassfield-keyring (see $log)"
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
  sign "$f"
done
printf '%s\n' "${built[@]##*/}" "${keyring_pkg##*/}"

# The grassfield-desktop version of a snapshot's database ("" when none).
desktop_version() {
  bsdtar -xOf "$1" 2>/dev/null | awk '/^%NAME%$/ { getline n } /^%VERSION%$/ { getline v; if (n == "grassfield-desktop") { print v; exit } }'
}

publish() { # channel
  local c=$1 dir=$tree/$1/x86_64 prev cur id snap work f b
  local -a add=()
  mkdir -p "$dir/snap"
  prev=$(cat "$dir/pointer" 2>/dev/null || true)
  [[ -z $prev || -d $dir/snap/$prev ]] || die "$dir/pointer names a missing snapshot ($prev)"
  if [[ -n $prev ]]; then
    cur=$(desktop_version "$dir/snap/$prev/grassfield.db")
    if [[ -n $cur ]] && (($(vercmp "$cur" "$full") >= 0)); then
      echo "$c: already holds grassfield-desktop $cur, not older than $full: unchanged"
      return 0
    fi
  fi
  for f in "${built[@]}" "$keyring_pkg"; do
    b=${f##*/}
    if [[ -e $dir/$b ]]; then
      cmp -s "$f" "$dir/$b" && continue
      # The keyring of an unchanged pkgver is rebuilt by every run: the published file of that name stays.
      [[ $f == "$keyring_pkg" ]] && continue
      die "$dir/$b exists with other content: a package file name never changes content (bump the pkgrel)"
    fi
    cp "$f" "$f.sig" "$dir/"
    add+=("$dir/$b")
  done
  work=$(mktemp -d /build/db.XXXXXX)
  if [[ -n $prev ]]; then
    cp "$dir/snap/$prev/grassfield.db" "$work/grassfield.db.tar.gz"
    cp "$dir/snap/$prev/grassfield.files" "$work/grassfield.files.tar.gz"
  fi
  # repo-add records each package's .sig in the database; the databases are signed below, by the same key.
  if ((${#add[@]})); then
    repo-add --quiet --prevent-downgrade "$work/grassfield.db.tar.gz" "${add[@]}" >>"$log" 2>&1 || die "repo-add $c (see $log)"
  fi
  id=$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}
  snap=$dir/snap/$id
  [[ ! -e $snap ]] || die "snapshot $snap exists already"
  mkdir "$snap"
  cp -L "$work/grassfield.db.tar.gz" "$snap/grassfield.db"
  cp -L "$work/grassfield.files.tar.gz" "$snap/grassfield.files"
  python3 -I "$here/scripts/notes.py" --channel "$c" --version "$full" --date "$(date -u +%F)" "${notes[@]}" \
    ${prev:+--previous "$dir/snap/$prev/grassfield-notes.json"} >"$snap/grassfield-notes.json" || die "release notes for $c"
  for f in grassfield.db grassfield.files grassfield-notes.json; do sign "$snap/$f"; done
  rm -rf "$work"
  printf '%s\n' "$id" >"$dir/pointer.new"
  mv -f "$dir/pointer.new" "$dir/pointer"
  echo "$c: snapshot $id (grassfield-desktop $full)"
  updated+=("$c:$id")
}

step "the channels"
updated=()
for c in "${channels[@]}"; do publish "$c"; done
abi=$(bsdtar -xOf /build/pkgs/grassfield-compositor-*.pkg.tar.zst usr/lib/grassfield/grassfield-compositor.abi 2>/dev/null | head -n 1 || true)
{
  echo "ref $ref"
  echo "commit $commit"
  echo "version $version"
  echo "packages $full"
  echo "snapshots ${updated[*]:-none}"
  echo "signing-key $key"
  echo "hyprland $(pacman -Q hyprland | awk '{print $2}')"
  echo "plugin-abi ${abi:-unknown}"
  echo "package-set:"
  pacman -Q
} >"$tree/build-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}.txt"
echo "done: ${updated[*]:-no channel changed}"
