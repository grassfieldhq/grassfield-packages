#!/usr/bin/env bash
# Sign a tested release build with the project's key, for the channel's publisher (grassfield ADR-0033 b.7, g; ADR-0037 g).
#
#   sign-release.sh --release DIR --gnupghome DIR --key FPR [--published DIR]
#
#   --release DIR    releases/<channel>/<version>/ as build-channel.sh wrote it and the test job installed it, signed by the
#                    build's throwaway key; signed again here, in place
#   --published DIR  the channel's package files already published: a package file name never changes content, so one
#                    found there is used as it is, with its signature (grassfield-keyring, which every release names)
# The packages keep the bytes the test job installed; each gets a signature by --key, the database is made again by
# repo-add (a published package may replace a built one; without --include-sigs it records no signature, pacman fetches
# each .sig beside its package), and grassfield.db, grassfield.files and grassfield-notes.json are signed by --key. A
# passphrase, when the key has one, comes from GRASSFIELD_SIGNING_PASSPHRASE. It runs no build code and installs nothing
# (gpg, repo-add and bsdtar of the image), so the key never meets a build (review M1). Runs only as root inside a
# throwaway container (repo-add). Exit 0 signed, 1 failed, 2 usage.
set -euo pipefail
release="" gnupghome="" key="" published=""
usage() { echo "usage: sign-release.sh --release DIR --gnupghome DIR --key FPR [--published DIR]" >&2; exit 2; }
die() { echo "sign-release.sh: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --release) release=$2 ;;
    --gnupghome) gnupghome=$2 ;;
    --key) key=$2 ;;
    --published) published=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -d $release && -n $gnupghome && $key =~ ^[0-9A-F]{40}$ ]] || usage
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "sign-release.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }

sign() {
  local pass=()
  [[ -n ${GRASSFIELD_SIGNING_PASSPHRASE:-} ]] && pass=(--pinentry-mode loopback --passphrase-fd 0)
  printf '%s' "${GRASSFIELD_SIGNING_PASSPHRASE:-}" |
    gpg --homedir "$gnupghome" --batch --no-tty "${pass[@]}" --local-user "$key!" --detach-sign --no-armor --yes \
      --output "$1.sig" "$1" 2>/dev/null || die "cannot sign $1"
}
signer() { # the primary key that made file.sig, if valid
  gpg --homedir "$gnupghome" --batch --no-tty --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | awk '$2 == "VALIDSIG" { print $12 }' || true
}

cd "$release"
for f in grassfield.db grassfield.files grassfield-notes.json; do [[ -f $f ]] || die "$release has no $f"; done
mapfile -t packages < <(ls ./*.pkg.tar.zst 2>/dev/null)
((${#packages[@]})) || die "$release holds no package"
for f in "${packages[@]}"; do
  b=${f#./}
  if [[ -n $published && -f $published/$b ]]; then
    cp "$published/$b" "$published/$b.sig" . || die "$published/$b has no signature"
    [[ $(signer "$b") == "$key" ]] || die "the published $b is not signed by $key"
    echo "$b: the published file and its signature"
  else
    sign "$b"
    echo "$b: signed"
  fi
done
work=$(mktemp -d)
repo-add --quiet "$work/grassfield.db.tar.gz" "${packages[@]}" >/dev/null || die "repo-add"
cp -L "$work/grassfield.db.tar.gz" grassfield.db
cp -L "$work/grassfield.files.tar.gz" grassfield.files
rm -rf "$work"
for f in grassfield.db grassfield.files grassfield-notes.json; do sign "$f"; done
echo "signed by $key: $release"
