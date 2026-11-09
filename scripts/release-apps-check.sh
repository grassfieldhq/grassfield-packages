#!/usr/bin/env bash
# The bundled apps of one release build (releases/<channel>/<version>/), checked as sign-release.sh prepare needs them:
#
#   release-apps-check.sh RELEASE_DIR
#
# Packages are selected by the pkgname in their .PKGINFO (the last line wins, as in repo-add), never by file name. Every
# package named grassfield-sanaga or grassfield-notes must be the only one of its name and pass scripts/app-check.sh against
# its folder in git, so a published package of the same file name that replaced a new build cannot hide a changed
# PKGBUILD (review of PR #22). And a release whose grassfield-desktop depends on an app (grassfield-sanaga or sanaga for the
# browser, grassfield-notes) must hold it: publish.py accepts a package missing from a newer release, which would drop
# the app from the channel and make every client's -Syu fail on the desktop's dependency. A release with no desktop or no
# such dependency (a ref from before ADR-0055) needs neither. Exit 0, 1 refused (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 1 && -d $1 ]] || { echo "usage: release-apps-check.sh RELEASE_DIR" >&2; exit 2; }
here=$(cd "$(dirname "$0")/.." && pwd)
die() { echo "release-apps-check.sh: $*" >&2; exit 1; }
cd "$1" || exit 2
shopt -s nullglob
declare -A found
desktop_info=""
for f in ./*.pkg.tar.zst; do
  info=$(bsdtar -xOf "$f" .PKGINFO 2>/dev/null) || die "${f#./}: no .PKGINFO"
  n=$(sed -n 's/^pkgname = //p' <<<"$info" | tail -n 1)
  case $n in
    grassfield-sanaga | grassfield-notes)
      [[ -z ${found[$n]:-} ]] || die "${1} holds more than one $n"
      found[$n]=$f
      "$here/scripts/app-check.sh" "$f" "$here/$n" || die "${f#./} is not what $n/PKGBUILD builds (a changed PKGBUILD is a new pkgrel)"
      echo "${f#./}: $n/PKGBUILD's package" ;;
    grassfield-desktop) desktop_info=$info ;;
  esac
done
for app in grassfield-sanaga grassfield-notes; do
  [[ -z $desktop_info ]] && break
  case $app in
    grassfield-sanaga) pattern='^depend = (grassfield-sanaga|sanaga)([<>=].*)?$' ;;
    *) pattern='^depend = grassfield-notes([<>=].*)?$' ;;
  esac
  if grep -qE "$pattern" <<<"$desktop_info" && [[ -z ${found[$app]:-} ]]; then
    die "grassfield-desktop depends on $app, which this release does not hold"
  fi
done
exit 0
