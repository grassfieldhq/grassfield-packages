#!/usr/bin/env bash
# A bundled app's package against its folder in git (grassfield-sanaga/, grassfield-notes/): the gate between the container
# that built it (third-party build code ran there, and could write the package file) and everything that signs, installs or
# ships it, and the reuse rule of build-channel.sh, the way keyring-check.sh is grassfield-keyring's (README.md, "Bundled
# apps").
#
#   app-check.sh PACKAGE APP_DIR
#
# Same only if:
#   - APP_DIR's PKGBUILD is pinned (scripts/pin-check.sh: one full commit, one real SHA-256, no per-architecture array, no
#     install=, no replaces=);
#   - its paths are EXACTLY the app's own: .PKGINFO, .BUILDINFO, .MTREE; usr/bin/<the app's binary> alone; usr/share/
#     applications/<its .desktop> alone; its hicolor icons (<binary>.png or .svg under hicolor/<size>/apps/); its metainfo
#     file if it has one; and usr/share/licenses/<pkgname>/ with what is below. No .INSTALL (no scriptlet), no other binary
#     (it would sit in PATH of the desktop's build and of a client's root commands), no hook, no usr/share/doc, no file
#     elsewhere;
#   - every member is a regular file or a folder, owned by root, with no setuid, setgid or sticky bit, and no group- or
#     world-writable mode, and carries no pax extension of any kind: no extended attribute (security.capability: pacman
#     restores file capabilities from the archive with no install script), no ACL, no file flag. `bsdtar -tv` cannot see
#     those, so the members are read by scripts/pkg-members.py (Python's tarfile on the zstd stream, which shows the pax
#     headers). Where python3 is absent (sign-release.sh prepare runs in a bare, network-less container) the decompressed
#     stream is scanned for the names of such headers instead, a cruder test that refuses at least as much;
#   - its .PKGINFO names APP_DIR's package at the PKGBUILD's pkgver-pkgrel with ONE line for each single-valued key (repo-add
#     keeps the last one: a second pkgver line would publish another version), holds only makepkg's descriptive and dependency
#     fields (no replaces, groups, backup...), and its depend, optdepend, provides and conflict lines are the PKGBUILD's;
#   - its .BUILDINFO records the SHA-256 of that very PKGBUILD (makepkg writes it: pkgbuild_sha256sum). The PKGBUILD holds
#     the pinned commit and the checksum of the source, so equal PKGBUILD bytes are an equal pin. Any other change to the
#     PKGBUILD is a new pkgrel. (.BUILDINFO is written by the untrusted side: a process check, not proof of origin.)
# The package is read with bsdtar, zstd and Python's tarfile, and its two files by plain text matching: nothing in it is
# evaluated, extracted or run. Exit 0 the same, 1 not (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 2 && -f $1 && -f $2/PKGBUILD ]] || { echo "usage: app-check.sh PACKAGE APP_DIR (an app folder with its PKGBUILD)" >&2; exit 2; }
pkg=$1 src=$2
self=$(cd "$(dirname "$0")" && pwd)
fail() { echo "app-check.sh: ${pkg##*/}: $*" >&2; exit 1; }
"$self/pin-check.sh" "$src" || fail "$src/PKGBUILD is not pinned"
read -r name ver < <(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf "%s %s-%s\n" "$pkgname" "$pkgver" "$pkgrel"' _ "$src")
[[ -n ${name:-} && -n ${ver:-} ]] || fail "cannot read $src/PKGBUILD"
case $name in
  grassfield-sanaga) bin=sanaga meta=site.grassfield.Sanaga.metainfo.xml ;;
  grassfield-notes) bin=grassfield-notes meta="" ;;
  *) fail "$name is not a bundled app" ;;
esac

# The paths: exactly the app's own.
verbose=$(bsdtar -tvf "$pkg" 2>/dev/null) || fail "unreadable"
list=$(bsdtar -tf "$pkg" 2>/dev/null) || fail "unreadable"
icon="^usr/share/icons/hicolor/(scalable|[0-9]+x[0-9]+(@2)?)/(apps/($bin\.(png|svg))?)?$"
while IFS= read -r p; do
  ok=0
  case $p in
    .PKGINFO | .BUILDINFO | .MTREE | usr/ | usr/bin/ | usr/share/ | usr/share/applications/ | usr/share/icons/ | usr/share/icons/hicolor/ | usr/share/licenses/ | usr/share/metainfo/ | "usr/bin/$bin" | "usr/share/applications/$bin.desktop" | "usr/share/licenses/$name/" | "usr/share/licenses/$name/"*) ok=1 ;;
  esac
  [[ $p =~ $icon ]] && ok=1
  [[ -n $meta && $p == "usr/share/metainfo/$meta" ]] && ok=1
  ((ok)) || fail "a path that is not this app's (only usr/bin/$bin, usr/share/applications/$bin.desktop, its hicolor icons, its licences${meta:+, usr/share/metainfo/$meta}; no .INSTALL, no usr/share/doc): $p"
  [[ $p != *..* ]] || fail "a path with '..': $p"
done <<<"$list"
! grep -qE ' -> | link to ' <<<"$verbose" || fail "a link among its entries: $(grep -m1 -E ' -> | link to ' <<<"$verbose")"
bad=$(awk '$1 !~ /^[-d][r-][w-][x-][r-]-[x-][r-]-[x-]$/ || $3 != "root" || $4 != "root" { print $1, $3, $4, $9 }' <<<"$verbose" | head -n 1)
[[ -z $bad ]] || fail "not a regular file or folder, not owned by root, a setuid, setgid or sticky bit, or a group- or world-writable mode: $bad"
grep -qx "usr/bin/$bin" <<<"$list" && grep -qx "usr/share/applications/$bin.desktop" <<<"$list" || fail "no usr/bin/$bin or no usr/share/applications/$bin.desktop"

# The members, as a tar parser sees them (pax headers: xattrs, ACLs, file flags).
if [[ -z ${APP_CHECK_NO_PYTHON:-} ]] && command -v python3 >/dev/null; then  # APP_CHECK_NO_PYTHON: for the test of the other branch
  python3 -I "$self/pkg-members.py" "$pkg" || fail "a member the parser refuses (see above)"
else
  magic=$(zstd -dc -- "$pkg" 2>/dev/null | head -c 512 | tail -c +258 | head -c 5 || true)
  [[ $magic == ustar ]] || fail "not a tar stream of the ustar or pax family"
  ! zstd -dc -- "$pkg" 2>/dev/null | LC_ALL=C grep -aqE 'SCHILY\.|LIBARCHIVE\.|security\.|system\.posix_acl|\.xattr\.' ||
    fail "a pax header or a name that sets an extended attribute, an ACL or file flags (no python3 here: the stream was scanned)"
fi

# .PKGINFO: the name and version once each, the field names, the dependency lines.
info=$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null) || fail "no .PKGINFO"
! grep -qE '`|\$\(' <<<"$info" || fail ".PKGINFO holds a command substitution"
for k in pkgname pkgbase pkgver pkgdesc url builddate packager size arch; do
  n=$(grep -c "^$k = " <<<"$info" || true)
  [[ $n -le 1 ]] || fail ".PKGINFO repeats $k ($n lines; repo-add keeps the last one)"
done
[[ $(grep -c '^pkgname = ' <<<"$info") == 1 && $(grep -c '^pkgver = ' <<<"$info") == 1 && $(grep -c '^arch = ' <<<"$info") == 1 ]] ||
  fail ".PKGINFO needs exactly one pkgname, pkgver and arch"
grep -Fqx "pkgname = $name" <<<"$info" && grep -Fqx "pkgver = $ver" <<<"$info" && grep -Fqx "arch = x86_64" <<<"$info" ||
  fail "not $name $ver for x86_64 ($src/PKGBUILD)"
! grep -q '^pkgbase = ' <<<"$info" || grep -Fqx "pkgbase = $name" <<<"$info" || fail "pkgbase is not $name"
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
