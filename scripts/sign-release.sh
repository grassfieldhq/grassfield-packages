#!/usr/bin/env bash
# A tested release build signed with the project's key, for the channel's publisher (grassfield ADR-0033 b.7, g; ADR-0037
# g). Two steps in two containers, so the key never meets anything that reads package contents (review M1: repo-add
# evaluates each .PKGINFO line, so a crafted package runs code where repo-add runs):
#
#   sign-release.sh prepare --release DIR --keyring DIR [--published DIR]      a container WITHOUT the key
#   sign-release.sh sign --release DIR --gnupghome DIR --key FPR               a container with the key, gpg only
#
#   --release DIR    releases/<channel>/<version>/ as build-channel.sh wrote it and the test job installed it
#   --keyring DIR    grassfield-keyring's sources in this repository (keyring/): the keys the release may be signed by
#   --published DIR  the channel's package files already published, each with its .sig
#
# prepare: a package already published under the same name is used as it is, with its signature, which must be by a key
# keyring/ trusts (a package file name never changes content: grassfield-keyring, which every release names); the
# release's grassfield-keyring must hold exactly keyring/'s files (a build cannot add a trusted key); repo-add makes the
# database again (without --include-sigs it records no signature: pacman fetches each .sig beside its package); every
# signature that sign must make is removed (the build's throwaway ones, the databases' and the notes').
# sign: only gpg runs. The release folder must hold nothing but regular files named grassfield.db, grassfield.files,
# grassfield-notes.json or grassfield-*.pkg.tar.zst, or those names with .sig; each such file without a .sig gets one by
# --key. It reads no file's content but to sign it. A passphrase, when the key has one, comes from
# GRASSFIELD_SIGNING_PASSPHRASE.
# Then check-tree.sh --trusted --keyring-src keyring/ checks the folder as a client would, its exact contents and its
# keyring, in a container without the key, before anything is uploaded. Runs only as root inside a throwaway container.
# Exit 0, 1 refused or failed, 2 usage.
set -euo pipefail
mode=${1:-} release="" gnupghome="" key="" published="" keyring=""
usage() {
  echo "usage: sign-release.sh prepare --release DIR --keyring DIR [--published DIR]" >&2
  echo "       sign-release.sh sign --release DIR --gnupghome DIR --key FPR" >&2
  exit 2
}
die() { echo "sign-release.sh: $*" >&2; exit 1; }
[[ $mode == prepare || $mode == sign ]] || usage
shift
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --release) release=$2 ;;
    --gnupghome) gnupghome=$2 ;;
    --key) key=$2 ;;
    --published) published=$2 ;;
    --keyring) keyring=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -d $release ]] || usage
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "sign-release.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
META='^grassfield(\.db|\.files|-notes\.json)$'
PACKAGE='^grassfield-[a-z0-9@_+][a-z0-9@._+-]*-(x86_64|any)\.pkg\.tar\.zst$'

if [[ $mode == prepare ]]; then
  [[ -d $keyring && -z $gnupghome && -z $key ]] || usage
  [[ -z ${GRASSFIELD_SIGNING_KEY+x}${GRASSFIELD_SIGNING_PASSPHRASE+x} ]] ||
    die "refused: prepare reads package contents (repo-add); it runs where the key is not"
  cd "$release"
  for f in grassfield.db grassfield.files grassfield-notes.json; do [[ -f $f ]] || die "$release has no $f"; done
  mapfile -t packages < <(ls ./*.pkg.tar.zst 2>/dev/null)
  ((${#packages[@]})) || die "$release holds no package"
  trusted() { # file: file.sig is by a key keyring/ trusts and does not revoke
    local primary
    primary=$(gpgv --keyring "$(realpath "$keyring/grassfield.gpg")" --status-fd 1 "$1.sig" "$1" 2>/dev/null |
      awk '$2 == "VALIDSIG" { print $12 }') || return 1
    [[ -n $primary ]] && grep -q "^$primary:" "$keyring/grassfield-trusted" && ! grep -q "^$primary" "$keyring/grassfield-revoked"
  }
  for f in "${packages[@]}"; do
    b=${f#./}
    [[ $b =~ $PACKAGE ]] || die "$b is not a package name of the channel"
    if [[ -n $published && -f $published/$b ]]; then
      cp "$published/$b" "$published/$b.sig" . || die "$published/$b has no signature"
      trusted "$b" || die "the published $b is not signed by a key keyring/ trusts"
      echo "$b: the published file and its signature"
    else
      rm -f "$b.sig"
    fi
  done
  # The keyring this release ships is the one in git, byte for byte (review minor 2).
  k=$(ls ./grassfield-keyring-*.pkg.tar.zst 2>/dev/null | head -n 1)
  [[ -n $k ]] || die "$release holds no grassfield-keyring"
  kx=$(mktemp -d)
  bsdtar -xf "$k" -C "$kx" usr/share/grassfield/pacman-keyring || die "cannot read $k"
  for f in grassfield.gpg grassfield-trusted grassfield-revoked; do
    [[ $(sha256sum <"$kx/usr/share/grassfield/pacman-keyring/$f") == "$(sha256sum <"$keyring/$f")" ]] ||
      die "${k#./}: $f is not keyring/$f"
  done
  [[ $(ls "$kx/usr/share/grassfield/pacman-keyring" | wc -l) == 3 ]] || die "${k#./} holds other files than keyring/'s three"
  rm -rf "$kx"
  work=$(mktemp -d)
  repo-add --quiet "$work/grassfield.db.tar.gz" "${packages[@]}" >/dev/null || die "repo-add"
  cp -L "$work/grassfield.db.tar.gz" grassfield.db
  cp -L "$work/grassfield.files.tar.gz" grassfield.files
  rm -rf "$work"
  rm -f grassfield.db.sig grassfield.files.sig grassfield-notes.json.sig
  echo "prepared: $release"
  exit 0
fi

# sign: gpg only, on names checked against the allowlist.
[[ -n $gnupghome && $key =~ ^[0-9A-F]{40}$ && -z $published && -z $keyring ]] || usage
shopt -s nullglob dotglob
todo=()
for f in "$release"/*; do
  b=${f##*/}
  [[ -f $f && ! -L $f ]] || die "$b is not a regular file"
  n=${b%.sig}
  [[ $n =~ $META || $n =~ $PACKAGE ]] || die "$b is not a name a release build holds"
  [[ $b == *.sig ]] && { [[ -f ${f%.sig} ]] || die "$b signs no file"; continue; }
  [[ -e $f.sig ]] || todo+=("$f")
done
for f in "$release"/grassfield.db "$release"/grassfield.files "$release"/grassfield-notes.json; do
  [[ -f $f ]] || die "$release has no ${f##*/}"
done
for f in "${todo[@]}"; do
  pass=()
  [[ -n ${GRASSFIELD_SIGNING_PASSPHRASE:-} ]] && pass=(--pinentry-mode loopback --passphrase-fd 0)
  printf '%s' "${GRASSFIELD_SIGNING_PASSPHRASE:-}" |
    gpg --homedir "$gnupghome" --batch --no-tty "${pass[@]}" --local-user "$key!" --detach-sign --no-armor \
      --output "$f.sig" "$f" 2>/dev/null || die "cannot sign ${f##*/}"
  echo "${f##*/}: signed"
done
echo "signed by $key: $release"
