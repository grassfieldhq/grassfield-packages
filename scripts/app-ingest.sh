#!/usr/bin/env bash
# Which package of a bundled app build-channel.sh ships, and the gate every candidate passes (README.md, "Bundled apps").
#
#   app-ingest.sh NAME APPS_DIR TREE OUT
#
# NAME is grassfield-sanaga or grassfield-notes. The package file this repository's PKGBUILD names (NAME-<pkgver>-<pkgrel>-
# x86_64.pkg.tar.zst) is taken, copied to OUT, after scripts/app-check.sh passed it (pinned PKGBUILD, allowed paths only,
# no scriptlet, its dependency lines, built from this very PKGBUILD):
#   - from TREE if a release build or channel there holds that name (the way grassfield-keyring is reused; the caller checks
#     its signature, which needs the key): "reused <path>", and its .sig is copied too, a missing .sig is refused;
#   - otherwise from APPS_DIR, where scripts/build-app.sh left it, from another container than this build's: "built <path>".
# Neither: refused (an app is never built here: its third-party build code runs only in build-app.sh's own container).
# Only the one file of that exact name is read, never anything else of APPS_DIR. Exit 0, 1 refused, 2 usage.
set -uo pipefail
[[ $# == 4 && -d $2 && -d $3 && -d $4 ]] || { echo "usage: app-ingest.sh NAME APPS_DIR TREE OUT (three folders)" >&2; exit 2; }
name=$1 apps=$2 tree=$3 out=$4
here=$(cd "$(dirname "$0")/.." && pwd)
die() { echo "app-ingest.sh: $*" >&2; exit 1; }
[[ -f $here/$name/PKGBUILD ]] || die "$name is not a bundled app"
av=$(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf %s-%s "$pkgver" "$pkgrel"' _ "$here/$name")
file=$name-$av-x86_64.pkg.tar.zst
old=$(find "$tree" -type f -name "$file" -print -quit)
if [[ -n $old ]]; then
  [[ -f $old.sig ]] || die "$old has no signature"
  "$here/scripts/app-check.sh" "$old" "$here/$name" || die "$old is not what $name/PKGBUILD builds: a changed PKGBUILD is a new pkgrel ($name/PKGBUILD)"
  cp "$old" "$old.sig" "$out/" || die "cannot copy $old"
  echo "reused $old"
else
  new=$apps/$file
  [[ -f $new && ! -L $new ]] || die "$file is not in $apps: build it first with scripts/build-app.sh (its own container)"
  "$here/scripts/app-check.sh" "$new" "$here/$name" || die "$file is not what $name/PKGBUILD builds"
  cp "$new" "$out/" || die "cannot copy $new"
  echo "built $new"
fi
