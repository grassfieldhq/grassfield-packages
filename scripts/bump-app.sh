#!/usr/bin/env bash
# Move a bundled app's PKGBUILD to a new pinned commit of its main, or verify the pin it has (README.md, "Bundled apps").
#
#   bump-app.sh grassfield-sanaga|grassfield-notes COMMIT     rewrite <app>/PKGBUILD for COMMIT (40 hex digits)
#   bump-app.sh --verify grassfield-sanaga|grassfield-notes   recompute the checksum and the version from the network
#
# A bump changes four things together, so that none can drift from the others: _commit, _rev (the commits up to it, from
# the app's own history), _cargover (Cargo.toml's version at it) and sha256sums (the SHA-256 of GitHub's archive of that
# commit). pkgrel goes back to 1 (the commit makes pkgver new). The commit must be on the app's main and a descendant of
# the pinned one: the publisher refuses a package older than the published one (tools/publish.py). Nothing is built, signed
# or published here: the diff goes to a pull request, and the reviewer runs `--verify` to see the same numbers.
# Needs git, curl, bsdtar and network; no root, no makepkg, no cargo. Exit 0 done (or already pinned), 1 refused, 2 usage.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
usage() { echo "usage: bump-app.sh grassfield-sanaga|grassfield-notes COMMIT | bump-app.sh --verify grassfield-sanaga|grassfield-notes" >&2; exit 2; }
die() { echo "bump-app.sh: $*" >&2; exit 1; }
verify=0
[[ ${1:-} != --verify ]] || { verify=1; shift; }
app_pkg=${1:-} commit=${2:-}
case $app_pkg in grassfield-sanaga | grassfield-notes) ;; *) usage ;; esac
if ((verify)); then [[ $# == 1 ]] || usage; else [[ $# == 2 && $commit =~ ^[0-9a-f]{40}$ ]] || usage; fi
pkgbuild=$here/$app_pkg/PKGBUILD
[[ -f $pkgbuild ]] || die "$pkgbuild is missing"
field() { bash -c 'source "$1" >/dev/null 2>&1; printf %s "${!2}"' _ "$pkgbuild" "$1"; }
app=$(field _app) pinned=$(field _commit) pinned_rev=$(field _rev) pinned_ver=$(field _cargover) pinned_sum=$(field sha256sums)
[[ $app =~ ^[a-z][a-z0-9-]*$ && $pinned =~ ^[0-9a-f]{40}$ && $pinned_rev =~ ^[0-9]+$ ]] || die "cannot read $pkgbuild's pin"
if ((verify)); then commit=$pinned; fi
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo=https://github.com/grassfieldhq/$app.git

# The history without file contents: enough for the count and the ancestry.
git clone --quiet --bare --filter=blob:none "$repo" "$work/repo.git" || die "cannot clone $repo"
git -C "$work/repo.git" cat-file -e "$commit^{commit}" 2>/dev/null || die "$commit is not a commit of $app"
git -C "$work/repo.git" merge-base --is-ancestor "$commit" refs/heads/main || die "$commit is not on $app's main"
if ((!verify)); then
  git -C "$work/repo.git" merge-base --is-ancestor "$pinned" "$commit" || die "$commit is not a descendant of the pinned $pinned (the publisher refuses an older package)"
fi
rev=$(git -C "$work/repo.git" rev-list --count "$commit")
curl --fail --silent --show-error --location --output "$work/src.tar.gz" "https://github.com/grassfieldhq/$app/archive/$commit.tar.gz" ||
  die "cannot download the archive of $commit"
sum=$(sha256sum "$work/src.tar.gz" | cut -d' ' -f1)
ver=$(bsdtar -xOf "$work/src.tar.gz" "$app-$commit/Cargo.toml" | sed -n 's/^version = "\(.*\)"$/\1/p' | head -n 1)
[[ $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Cargo.toml's version '$ver' is not X.Y.Z (a pkgver cannot hold a pre-release suffix)"
echo "$app $commit: Cargo.toml $ver, $rev commits, sha256 $sum"

if ((verify)); then
  [[ $ver == "$pinned_ver" && $rev == "$pinned_rev" && $sum == "$pinned_sum" ]] ||
    die "$pkgbuild says $pinned_ver, $pinned_rev commits, $pinned_sum: they are not the network's"
  echo "ok: $pkgbuild is the pin it says"
  exit 0
fi
if [[ $commit == "$pinned" ]]; then echo "already pinned: nothing changed"; exit 0; fi
sed -i -e "s/^_cargover=.*/_cargover=$ver/" -e "s/^_rev=.*/_rev=$rev/" -e "s/^_commit=.*/_commit=$commit/" \
  -e "s/^pkgrel=.*/pkgrel=1/" -e "s/^sha256sums=.*/sha256sums=('$sum')/" "$pkgbuild"
echo "rewritten: $pkgbuild (was $pinned_ver, $pinned_rev commits, ${pinned:0:7}); review the diff, then commit it in a pull request"
