#!/usr/bin/env bash
# A grassfield-keyring package against keyring/ in git: the whole package, not only its three files, so that a build cannot
# add a trusted key, an install script or any other path (grassfield ADR-0033 b.2, b.8; review of PR #3).
#
#   keyring-check.sh PACKAGE KEYRING_DIR
#
# Same only if:
#   - its paths are exactly .BUILDINFO, .INSTALL, .MTREE, .PKGINFO and usr/share/grassfield/pacman-keyring/ with
#     grassfield.gpg, grassfield-trusted and grassfield-revoked (and the folders above them), each a regular file or a
#     folder: no symbolic or hard link (bsdtar -xO reads a link as an empty file, and an empty grassfield-revoked pointed
#     elsewhere would let a local user change what pacman-key --populate revokes);
#   - those three files are KEYRING_DIR's byte for byte, and .INSTALL is KEYRING_DIR/grassfield-keyring.install;
#   - .PKGINFO names grassfield-keyring at KEYRING_DIR/PKGBUILD's pkgver-pkgrel and holds nothing but makepkg's
#     descriptive fields (no depends, provides, conflicts, replaces, backup, groups or anything else).
# The package is read with bsdtar and its .PKGINFO by plain text matching: nothing in it is evaluated. Used by
# sign-release.sh prepare and check-tree.sh --keyring-src. Exit 0 same, 1 not (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 2 && -f $1 && -f $2/PKGBUILD && -f $2/grassfield-keyring.install ]] ||
  { echo "usage: keyring-check.sh PACKAGE KEYRING_DIR (a keyring/ with its PKGBUILD)" >&2; exit 2; }
pkg=$1 src=$2
fail() { echo "keyring-check.sh: ${pkg##*/}: $*" >&2; exit 1; }
k=usr/share/grassfield/pacman-keyring
expected=$(printf '%s\n' .BUILDINFO .INSTALL .MTREE .PKGINFO usr/ usr/share/ usr/share/grassfield/ "$k/" \
  "$k/grassfield-revoked" "$k/grassfield-trusted" "$k/grassfield.gpg" | LC_ALL=C sort)
list=$(bsdtar -tf "$pkg" 2>/dev/null | LC_ALL=C sort) || fail "unreadable"
[[ $list == "$expected" ]] ||
  fail "not keyring/'s paths: $(LC_ALL=C comm -3 <(echo "$expected") <(echo "$list") | tr -s '\n\t' '  ')"
# Each entry's type, from the first character of `bsdtar -tv`: "-" a regular file, "d" a folder; never a link.
verbose=$(bsdtar -tvf "$pkg" 2>/dev/null) || fail "unreadable"
! grep -qE ' -> | link to ' <<<"$verbose" || fail "a link among its entries: $(grep -m1 -E ' -> | link to ' <<<"$verbose")"
typed=$(awk '{ print substr($1, 1, 1) " " $9 }' <<<"$verbose" | LC_ALL=C sort)
[[ $typed == "$(sed 's|^\(.*/\)$|d \1|; t; s|^|- |' <<<"$expected" | LC_ALL=C sort)" ]] ||
  fail "not regular files and folders only: $(grep -vE '^[-d]' <<<"$typed" | head -n 1)"
same() { [[ $(bsdtar -xOf "$pkg" "$1" 2>/dev/null | sha256sum) == "$(sha256sum <"$2")" ]]; }
for f in grassfield.gpg grassfield-trusted grassfield-revoked; do
  same "$k/$f" "$src/$f" || fail "$f is not keyring/$f"
done
same .INSTALL "$src/grassfield-keyring.install" || fail ".INSTALL is not keyring/grassfield-keyring.install"
ver=$(sed -n 's/^pkgver=\([0-9A-Za-z._+]*\)$/\1/p' "$src/PKGBUILD")-$(sed -n 's/^pkgrel=\([1-9][0-9]*\)$/\1/p' "$src/PKGBUILD")
info=$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null) || fail "no .PKGINFO"
other=$(grep -vE '^(#.*|)$' <<<"$info" |
  grep -vE '^(pkgname|pkgbase|xdata|pkgver|pkgdesc|url|builddate|packager|size|arch|license) = ' || true)
[[ -z $other ]] || fail ".PKGINFO holds more than makepkg's descriptive fields: $(head -n 1 <<<"$other")"
grep -qx 'pkgname = grassfield-keyring' <<<"$info" && grep -qx "pkgver = $ver" <<<"$info" ||
  fail "not grassfield-keyring $ver (keyring/PKGBUILD)"
exit 0
