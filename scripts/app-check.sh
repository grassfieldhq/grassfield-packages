#!/usr/bin/env bash
# A bundled app's package against its folder in git (grassfield-sanaga/, grassfield-notes/): the reuse rule of
# build-channel.sh, the way keyring-check.sh is grassfield-keyring's (README.md, "Bundled apps").
#
#   app-check.sh PACKAGE APP_DIR
#
# A package already built (in the tree, or published) stands for APP_DIR's PKGBUILD only if:
#   - its .PKGINFO names APP_DIR's package at the PKGBUILD's pkgver-pkgrel, and its .BUILDINFO records the SHA-256 of that
#     very PKGBUILD (makepkg writes it: pkgbuild_sha256sum). The PKGBUILD holds the pinned commit and the checksum of the
#     source, so equal PKGBUILD bytes are an equal pin. Any other change to the PKGBUILD is a new pkgrel;
#   - the PKGBUILD itself is pinned: _commit is 40 hex digits and every sha256sums entry is 64 hex digits (never SKIP).
# The package is read with bsdtar and its two files by plain text matching: nothing in it is evaluated. Exit 0 the same,
# 1 not (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 2 && -f $1 && -f $2/PKGBUILD ]] || { echo "usage: app-check.sh PACKAGE APP_DIR (an app folder with its PKGBUILD)" >&2; exit 2; }
pkg=$1 src=$2
fail() { echo "app-check.sh: ${pkg##*/}: $*" >&2; exit 1; }
read -r name ver commit < <(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf "%s %s-%s %s\n" "$pkgname" "$pkgver" "$pkgrel" "$_commit"' _ "$src")
[[ -n ${name:-} && -n ${ver:-} ]] || fail "cannot read $src/PKGBUILD"
[[ $commit =~ ^[0-9a-f]{40}$ ]] || fail "$src/PKGBUILD pins no full commit (_commit '$commit')"
sums=$(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf "%s\n" "${sha256sums[@]}"' _ "$src")
[[ -n $sums ]] && ! grep -qvE '^[0-9a-f]{64}$' <<<"$sums" || fail "$src/PKGBUILD has a checksum that is not a SHA-256 (SKIP?)"
info=$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null) || fail "no .PKGINFO"
grep -qx "pkgname = $name" <<<"$info" && grep -qx "pkgver = $ver" <<<"$info" || fail "not $name $ver ($src/PKGBUILD)"
build=$(bsdtar -xOf "$pkg" .BUILDINFO 2>/dev/null) || fail "no .BUILDINFO"
grep -qx "pkgbuild_sha256sum = $(sha256sum <"$src/PKGBUILD" | cut -d' ' -f1)" <<<"$build" ||
  fail "built from another PKGBUILD than $src/PKGBUILD: a changed PKGBUILD is a new pkgrel"
exit 0
