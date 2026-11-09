#!/usr/bin/env bash
# A bundled app's package against its folder in git (grassfield-sanaga/, grassfield-notes/): the gate between the container
# that built it (third-party build code ran there) and everything that signs, installs or ships it, and the reuse rule of
# build-channel.sh, the way keyring-check.sh is grassfield-keyring's (README.md, "Bundled apps").
#
#   app-check.sh PACKAGE APP_DIR
#
# Same only if:
#   - APP_DIR's PKGBUILD is pinned (scripts/pin-check.sh: one full commit, one real SHA-256, no per-architecture array, no
#     install=, no replaces=);
#   - its paths are .PKGINFO, .BUILDINFO, .MTREE and, under usr/, only bin/, share/applications/, share/icons/,
#     share/licenses/, share/metainfo/ and share/doc/: no .INSTALL (no scriptlet), nothing for libalpm hooks, no file outside
#     those folders, each a regular file or a folder (no link, no setuid or sticky bit), with the app's binary and its
#     .desktop file present;
#   - its .PKGINFO names APP_DIR's package at the PKGBUILD's pkgver-pkgrel, holds only makepkg's descriptive and dependency
#     fields (no replaces, groups, backup...), and its depend, optdepend, provides and conflict lines are the PKGBUILD's;
#   - its .BUILDINFO records the SHA-256 of that very PKGBUILD (makepkg writes it: pkgbuild_sha256sum). The PKGBUILD holds
#     the pinned commit and the checksum of the source, so equal PKGBUILD bytes are an equal pin. Any other change to the
#     PKGBUILD is a new pkgrel.
# The package is read with bsdtar and its two files by plain text matching: nothing in it is evaluated or run. Exit 0 the
# same, 1 not (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 2 && -f $1 && -f $2/PKGBUILD ]] || { echo "usage: app-check.sh PACKAGE APP_DIR (an app folder with its PKGBUILD)" >&2; exit 2; }
pkg=$1 src=$2
self=$(cd "$(dirname "$0")" && pwd)
fail() { echo "app-check.sh: ${pkg##*/}: $*" >&2; exit 1; }
"$self/pin-check.sh" "$src" || fail "$src/PKGBUILD is not pinned"
read -r name ver < <(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf "%s %s-%s\n" "$pkgname" "$pkgver" "$pkgrel"' _ "$src")
[[ -n ${name:-} && -n ${ver:-} ]] || fail "cannot read $src/PKGBUILD"
case $name in
  grassfield-sanaga) bin=sanaga ;;
  grassfield-notes) bin=grassfield-notes ;;
  *) fail "$name is not a bundled app" ;;
esac

# The contents: the allowlist of paths, and only regular files and folders.
verbose=$(bsdtar -tvf "$pkg" 2>/dev/null) || fail "unreadable"
list=$(bsdtar -tf "$pkg" 2>/dev/null) || fail "unreadable"
while IFS= read -r p; do
  case $p in
    .PKGINFO | .BUILDINFO | .MTREE | usr/ | usr/bin/ | usr/share/) ;;
    usr/bin/*) [[ $p =~ ^usr/bin/[^/]+$ ]] || fail "a folder or file below usr/bin/: $p" ;;
    usr/share/applications/* | usr/share/icons/* | usr/share/licenses/* | usr/share/metainfo/* | usr/share/doc/*) ;;
    *) fail "a path outside the allowed ones (usr/bin, usr/share/{applications,icons,licenses,metainfo,doc}, no .INSTALL): $p" ;;
  esac
  [[ $p != *..* ]] || fail "a path with '..': $p"
done <<<"$list"
! grep -qE ' -> | link to ' <<<"$verbose" || fail "a link among its entries: $(grep -m1 -E ' -> | link to ' <<<"$verbose")"
bad=$(awk '$1 !~ /^[-d][r-][w-][x-][r-][w-][x-][r-][w-][x-]$/ { print $1, $9 }' <<<"$verbose" | head -n 1)
[[ -z $bad ]] || fail "not regular files and folders, or a setuid, setgid or sticky bit: $bad"
grep -qx "usr/bin/$bin" <<<"$list" && grep -qx "usr/share/applications/$bin.desktop" <<<"$list" || fail "no usr/bin/$bin or no usr/share/applications/$bin.desktop"

# .PKGINFO: the name and version, the field names, the dependency lines.
info=$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null) || fail "no .PKGINFO"
grep -Fqx "pkgname = $name" <<<"$info" && grep -Fqx "pkgver = $ver" <<<"$info" || fail "not $name $ver ($src/PKGBUILD)"
other=$(grep -vE '^(#.*|)$' <<<"$info" |
  grep -vE '^(pkgname|pkgbase|xdata|pkgver|pkgdesc|url|builddate|packager|size|arch|license|depend|optdepend|makedepend|checkdepend|provides|conflict|pkgtype) = ' || true)
[[ -z $other ]] || fail ".PKGINFO holds more than the allowed fields: $(head -n 1 <<<"$other")"
expected=$(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1
  for e in "${depends[@]}"; do printf "depend = %s\n" "$e"; done
  for e in "${optdepends[@]}"; do printf "optdepend = %s\n" "$e"; done
  for e in "${provides[@]}"; do printf "provides = %s\n" "$e"; done
  for e in "${conflicts[@]}"; do printf "conflict = %s\n" "$e"; done' _ "$src" | LC_ALL=C sort)
actual=$(grep -E '^(depend|optdepend|provides|conflict) = ' <<<"$info" | LC_ALL=C sort)
[[ $actual == "$expected" ]] || fail "its dependency lines are not $src/PKGBUILD's: $(LC_ALL=C comm -3 <(echo "$expected") <(echo "$actual") | tr -s '\n\t' '  ')"

# .BUILDINFO: built from this very PKGBUILD.
build=$(bsdtar -xOf "$pkg" .BUILDINFO 2>/dev/null) || fail "no .BUILDINFO"
grep -Fqx "pkgbuild_sha256sum = $(sha256sum <"$src/PKGBUILD" | cut -d' ' -f1)" <<<"$build" ||
  fail "built from another PKGBUILD than $src/PKGBUILD: a changed PKGBUILD is a new pkgrel"
exit 0
