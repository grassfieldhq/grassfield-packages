#!/usr/bin/env bash
# Make a bundled app's package canonical before anything signs, publishes or installs it (README.md, "Bundled apps"; third and
# fourth reviews of grassfield-packages PR #22).
#
#   app-repack.sh --app NAME --in PACKAGE --out DIR
#
# Why: the package file came out of a container that ran third-party code, and that code could write it. Every parser we
# write differs from libarchive's somewhere, and pacman uses libarchive. So we do not predict what pacman will see: the
# signed artifact is rebuilt from a tree that libarchive itself extracted and that the filesystem itself describes, with
# .PKGINFO and .BUILDINFO WRITTEN FROM OUR PKGBUILD (the original ones are only compared), in the form makepkg's
# create_package gives.
#
# Runs in its own throwaway container with no network and nothing mounted but this repository (read-only), the package
# (read-only) and --out. It starts as root and does only this as root: copy the file, drop every privilege and capability
# (setpriv: uid and gid 65534, no groups, no capabilities, no_new_privs), and install the one result file into --out. Everything
# that parses the untrusted file (zstd, bsdtar, find, getfattr) runs unprivileged. The steps of that second stage:
#   0. which format is parsed: zstd alone decompresses the file to a plain one (under a size cap), and that must BE a tar: a
#      valid checksum on the first 512-byte header and "ustar" at offset 257 (so libarchive's tar reader is the highest
#      bidder and no cpio, zip, 7-Zip or further compression is ever handed to it); GNU tar must list the same members.
#      Before any libarchive call the first header's name must itself be one of the app's paths (no signature read at offset 0 can
#      be one; uuencode, found by a line scan, is refused by the next check). Then libarchive's own report on that file must be an uncompressed POSIX ustar or pax tar (it decides on decompression
#      before the format: a first block that is both a tar and a gzip header would be read as gzip and cpio), and GNU tar must
#      read it with exit status 0.
#   1. `bsdtar -tf` lists the members: no path twice (.PKGINFO included), every path one of the app's own, with every segment
#      of only [A-Za-z0-9._@+-] (scripts/app-lib.sh: no space, control byte, newline or invalid UTF-8 in a name); the owners and
#      modes libarchive prints are root:root, plain, no setuid, setgid or sticky bit, no group or world write.
#   2. bsdtar extracts it, never -P, into an empty folder: `-p` first (modes), then --no-xattrs --no-acls --no-fflags (bsdtar's
#      -p switches those three on again when it comes AFTER them), --no-same-owner (an unprivileged user cannot chown).
#   3. The tree is checked on the filesystem itself: only regular files and folders, no setuid, setgid or sticky bit and no
#      group or world write, `getfattr -R -d -m -` prints nothing, only the allowed paths, one .PKGINFO and one .BUILDINFO.
#   4. .PKGINFO is generated from `makepkg --printsrcinfo` of OUR PKGBUILD (name, version, arch, description, url, licence,
#      depends, optdepends, provides, conflicts) plus the measured size and the build date; the original .PKGINFO is compared
#      with it and any difference, or a control byte or invalid UTF-8 in it, refuses the package. .BUILDINFO is regenerated
#      with the fields app-check needs; the original must be clean text whose pkgbuild_sha256sum is our PKGBUILD's. Modes
#      become 0755/0644, mtimes the build date, .MTREE is regenerated (`bsdtar --format=mtree`, makepkg's options), and the
#      archive is made as makepkg does (its file order, `bsdtar --no-fflags -cnf`) with the owner set at creation (--uid 0 --gid 0
#      --uname root --gname root: nothing chowns), then zstd on one thread (equal input gives equal bytes).
#   5. Proof: the new package is extracted again with xattrs, ACLs and flags ENABLED: no attribute appears and the tree is the
#      canonical one; its listing is all root:root; scripts/app-check.sh passes it.
# The libarchive version used is printed. The container has no network, so that libarchive (and zstd) are the ones in the
# pinned image: the pin must be refreshed for their security updates (README.md, "Bundled apps"). Only the file written to
# --out goes on (to the signer, repo-add and the desktop's container). Exit 0, 1 refused or failed, 2 usage.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
app="" in="" out="" stage=root work="" name_in=""
usage() { echo "usage: app-repack.sh --app grassfield-sanaga|grassfield-notes --in PACKAGE --out DIR" >&2; exit 2; }
die() { echo "app-repack.sh: ${name_in:-${in##*/}}: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --app) app=$2 ;; --in) in=$2 ;; --out) out=$2 ;;
    --stage) stage=$2 ;; --work) work=$2 ;; --name) name_in=$2 ;;  # the unprivileged stage's own arguments
    *) usage ;;
  esac
  shift 2
done
export LC_ALL=C
# shellcheck source=app-lib.sh
source "$here/scripts/app-lib.sh"
app_names "$app" || usage
[[ -f $in && ! -L $in && -d $out ]] || usage
av=$(bash -c 'source "$1/PKGBUILD" >/dev/null 2>&1; printf %s-%s "$pkgver" "$pkgrel"' _ "$here/$app")
file=$app-$av-x86_64.pkg.tar.zst

if [[ $stage == root ]]; then
  [[ (-f /.dockerenv && $EUID == 0) || -n ${FAKEROOTKEY:-} ]] ||
    { echo "app-repack.sh: refused: runs only as root inside a throwaway container (tests: under fakeroot)" >&2; exit 2; }
  [[ ${in##*/} == "$file" ]] || die "the file is not named $file ($app/PKGBUILD's version)"
  echo "libarchive: $(bsdtar --version | head -n 1); zstd: $(zstd --version | head -n 1)"
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  if [[ -n ${FAKEROOTKEY:-} || $EUID != 0 ]]; then
    # A test as a user: the same second stage, with nothing to drop.
    "$0" --stage user --app "$app" --in "$in" --name "$file" --work "$work" --out "$work"
  else
    chown 65534:65534 "$work"
    chmod 700 "$work"
    install -o 65534 -g 65534 -m 600 "$in" "$work/input.pkg"
    rc=0
    setpriv --reuid=65534 --regid=65534 --clear-groups --inh-caps=-all --bounding-set=-all --no-new-privs \
      env -i PATH=/usr/bin:/usr/local/bin LC_ALL=C HOME="$work" TMPDIR="$work" \
      "$0" --stage user --app "$app" --in "$work/input.pkg" --name "$file" --work "$work" --out "$work" || rc=$?
    # Whatever the unprivileged stage left running (it could race the install below, or outlive this script in the signing
    # container) is killed before root reads anything it wrote.
    pkill -KILL -u 65534 || true
    # (A zombie is no process that can act: in a container whose PID 1 reaps nothing an exited child of the stage stays listed
    # as Z, and must not refuse every later repack.)
    # The list is read in full before it is searched: `ps | grep -q` under pipefail takes ps's SIGPIPE status when grep stops at
    # the first match, and the test would then pass on exactly the case it must refuse.
    survivors=$(ps -u 65534 -o stat= 2>/dev/null || true)
    if grep -q '^[^Z]' <<<"$survivors"; then die "a process of the unprivileged user survives"; fi
    ((rc == 0)) || exit "$rc"
  fi
  [[ -f $work/$file && ! -L $work/$file ]] || die "the unprivileged stage wrote no $file"
  install -m644 "$work/$file" "$out/$file"
  echo "repacked $file $(sha256sum <"$out/$file" | cut -d' ' -f1)"
  exit 0
fi

# ---- the unprivileged stage: everything that parses the untrusted file ----
[[ $stage == user && -d $work ]] || usage
mkdir "$work/tree" "$work/proof" "$work/pb"
tree=$work/tree

# 0. Which format gets parsed at all. libarchive reads whatever its readers bid highest for (cpio, zip, 7-Zip, ISO, RAR...,
# and compressed forms of them), so a package is decompressed here, by zstd alone, to a plain file, and that file must BE a
# tar: a size that is a multiple of 512 under a cap, a first 512-byte block whose checksum is valid and whose magic at offset 257
# is "ustar" (a valid tar header makes the tar reader the highest bidder), so nothing else, and no further compression, is ever
# handed to libarchive. GNU tar must then agree with libarchive about the members (step 1b).
[[ $(head -c 4 "$in" | od -An -tx1 | tr -d ' \n') == 28b52ffd ]] || die "not a zstd frame"
limit=$((1 << 30))
plain=$work/plain.tar
set +e
zstd -d -q --no-progress -c -- "$in" 2>/dev/null | head -c "$limit" >"$plain"
zstd_status=${PIPESTATUS[0]}
set -e
size=$(stat -c %s "$plain")
((size < limit)) || die "decompresses to $limit bytes or more: refused"
((zstd_status == 0)) || die "zstd cannot decompress it (exit status $zstd_status)"
((size >= 1024 && size % 512 == 0)) || die "not a plain tar behind the zstd frame (decompressed size $size)"
[[ $(head -c 262 "$plain" | tail -c 5) == ustar ]] || die "the decompressed file is not a tar of the ustar or pax family (no ustar magic at offset 257)"
want=$(head -c 154 "$plain" | tail -c 6)
have=$(od -An -v -tu1 -N512 "$plain" | awk '{ for (i = 1; i <= NF; i++) { n++; v = $i; if (n > 148 && n <= 156) v = 32; s += v } } END { print s }')
[[ $want =~ ^[0-7]{6}$ ]] && ((8#$want == have)) || die "the first tar header's checksum is not valid: not a tar archive"

# Before ANY libarchive call: the first header's name field (bytes 0-99, up to the NUL) must be one of the app's own paths. No filter
# or format signature that libarchive looks for at offset 0 (gzip, bzip2, xz, lzma, lzip, lz4, zstd, lzop, compress, rpm, cpio,
# zip, 7-Zip...) can also be a valid first member name such as .BUILDINFO or usr/. This check does NOT rule out the uuencode filter:
# its bidder scans lines for "begin " instead of reading a fixed offset, and a first header of printable bytes followed by a
# "begin 644" line does win it (review of the uuencode LOW). libarchive's footer then reads "Compression: uu", and the footer check
# below, which accepts only "Compression: none", refuses the file.
first=$(head -c 100 "$plain" | tr '\0' '\n' | head -n 1)
app_path_ok "$app" "$first" || die "the first member's name is not one of this app's paths (not a package of ours: $(printf %q "${first:0:40}"))"
# libarchive decides on decompression before it looks at the format, so a first block that is both a tar header and a gzip header
# can be gunzipped and read as cpio: ask libarchive itself what it sees in the plain file, and refuse anything but a POSIX
# ustar or pax tar with no compression; GNU tar must read the file as a tar too (exit status 0).
footer=$(bsdtar -tvvf "$plain" 2>&1 | tail -n 1)
[[ $footer =~ ^Archive\ Format:\ (POSIX\ pax\ interchange\ format|POSIX\ ustar\ format),\ +Compression:\ none$ ]] ||
  die "libarchive does not read the plain file as an uncompressed POSIX tar: $footer"
gnu=$(tar -tf "$plain" 2>/dev/null) || die "GNU tar cannot read the plain file as a tar (a polyglot libarchive reads as something else)"

# 1. The members, as libarchive lists them.
list=$(bsdtar -tf "$plain") || die "unreadable"
dups=$(printf '%s\n' "$list" | sort | uniq -d)
[[ -z $dups ]] || die "a path listed twice: $(head -n 1 <<<"$dups")"
while IFS= read -r p; do
  app_path_ok "$app" "$p" || die "a path that is not this app's, or with a character outside [A-Za-z0-9._@+-]: $p"
done <<<"$list"
# 1b. An independent reader, GNU tar, lists the same members (a tar polyglot that libarchive reads as something else fails here).
[[ $(sort <<<"$gnu") == "$(printf '%s\n' "$list" | sort)" ]] || die "GNU tar and libarchive do not list the same members"
bad=$(bsdtar -tvf "$plain" | awk '$1 !~ /^[-d][r-][w-][x-][r-]-[x-][r-]-[x-]$/ || $3 != "root" || $4 != "root" { print $1, $3, $4, $9 }' | head -n 1)
[[ -z $bad ]] || die "not a regular file or folder, not owned by root, a setuid, setgid or sticky bit, or a group- or world-writable mode: $bad"

# 2. Extracted by libarchive: -p BEFORE the --no-* flags (after them it would switch xattrs, ACLs and flags back on).
bsdtar -x -f "$plain" -C "$tree" -p --no-xattrs --no-acls --no-fflags --no-same-owner || die "bsdtar cannot extract it"

# 3. The tree, on the filesystem itself.
cd "$tree"
[[ -z $(find . -mindepth 1 ! -type f ! -type d -print -quit) ]] || die "not only regular files and folders: $(find . -mindepth 1 ! -type f ! -type d -print -quit)"
[[ -z $(find . -perm /7022 -print -quit) ]] || die "a setuid, setgid or sticky bit, or a group- or world-writable mode: $(find . -perm /7022 -print -quit)"
[[ -z $(getfattr -R -h -d -m - . 2>&1) ]] || die "extended attributes on the extracted tree"
find . -mindepth 1 -print0 >"$work/paths0"
while IFS= read -r -d '' p; do
  p=${p#./}
  [[ -d ./$p ]] && p+=/
  app_path_ok "$app" "$p" || die "a path that is not this app's, or with a character outside [A-Za-z0-9._@+-]: $p"
done <"$work/paths0"
[[ -f .PKGINFO && -f .BUILDINFO && -f usr/bin/$bin && -f usr/share/applications/$bin.desktop ]] || die "no .PKGINFO, .BUILDINFO, binary or .desktop file"

# 4a. The text files of the original are only compared, never carried over.
clean_text() { # file: UTF-8, and no control byte but the newline
  iconv -f UTF-8 -t UTF-8 "$1" >/dev/null 2>&1 && ! tr -d '\n' <"$1" | grep -q '[[:cntrl:]]'
}
clean_text .PKGINFO || die ".PKGINFO is not plain UTF-8 text (a control byte or an invalid sequence)"
clean_text .BUILDINFO || die ".BUILDINFO is not plain UTF-8 text (a control byte or an invalid sequence)"
cp "$here/$app/PKGBUILD" "$work/pb/PKGBUILD"
# (env -u: a test under fakeroot, where makepkg would refuse a faked root)
srcinfo=$(cd "$work/pb" && env -u FAKEROOTKEY -u LD_PRELOAD makepkg --printsrcinfo) || die "makepkg --printsrcinfo of $app/PKGBUILD failed"
val() { sed -n "s/^\t$1 = //p" <<<"$srcinfo"; }
name=$(sed -n 's/^pkgname = //p' <<<"$srcinfo" | head -n 1)
ver=$(val pkgver | head -n 1)-$(val pkgrel | head -n 1)
[[ $name == "$app" && $ver == "$av" ]] || die "the PKGBUILD names $name $ver, not $app $av"
epoch=$(sed -n 's/^builddate = //p' .PKGINFO | head -n 1)
[[ $epoch =~ ^[0-9]{1,10}$ && $epoch -le 4102444800 ]] || die ".PKGINFO has no sensible numeric builddate"
size=$(find . -type f ! -name .PKGINFO ! -name .BUILDINFO ! -name .MTREE -printf '%s\n' | awk '{ s += $1 } END { print s + 0 }')
generated_fields() {
  printf 'pkgname = %s\n' "$name"
  printf 'pkgver = %s\n' "$ver"
  printf 'pkgdesc = %s\n' "$(val pkgdesc | head -n 1)"
  printf 'url = %s\n' "$(val url | head -n 1)"
  printf 'arch = x86_64\n'
  val license | sed 's/^/license = /'
  val provides | sed 's/^/provides = /'
  val conflicts | sed 's/^/conflict = /'
  val depends | sed 's/^/depend = /'
  val optdepends | sed 's/^/optdepend = /'
}
compared='pkgname|pkgver|pkgdesc|url|arch|license|provides|conflict|depend|optdepend'
grep -E "^($compared) = " .PKGINFO | sort >"$work/pkginfo.original"
generated_fields | grep -E "^($compared) = " | sort >"$work/pkginfo.generated"
cmp_lists() { [[ $(<"$work/pkginfo.original") == "$(<"$work/pkginfo.generated")" ]]; }
cmp_lists || die ".PKGINFO is not what $app/PKGBUILD says: $(comm -3 "$work/pkginfo.generated" "$work/pkginfo.original" | tr -s '\n\t' '  ' | cut -c1-300)"
other=$(grep -vE '^(#.*|)$' .PKGINFO | grep -vE "^($compared|pkgbase|xdata|builddate|packager|size|makedepend|checkdepend|pkgtype) = " || true)
[[ -z $other ]] || die ".PKGINFO holds a field that is not allowed: $(head -n 1 <<<"$other")"
pkgbuild_sum=$(sha256sum <"$here/$app/PKGBUILD" | cut -d' ' -f1)
[[ $(grep -c '^pkgbuild_sha256sum = ' .BUILDINFO) == 1 ]] && grep -Fqx "pkgbuild_sha256sum = $pkgbuild_sum" .BUILDINFO ||
  die ".BUILDINFO was not built from $app/PKGBUILD (a changed PKGBUILD is a new pkgrel)"

# 4b. The canonical form, as makepkg's create_package makes it, with .PKGINFO and .BUILDINFO written here.
rm -f .MTREE
{
  echo "# Generated by app-repack.sh from $app/PKGBUILD"
  printf 'pkgname = %s\npkgbase = %s\nxdata = pkgtype=pkg\n' "$name" "$name"
  generated_fields | grep -E '^(pkgver|pkgdesc|url) = '
  printf 'builddate = %s\npackager = Grassfield\nsize = %s\n' "$epoch" "$size"
  generated_fields | grep -vE '^(pkgname|pkgver|pkgdesc|url) = '
} >.PKGINFO
printf 'format = 2\npkgname = %s\npkgbase = %s\npkgver = %s\npkgarch = x86_64\npkgbuild_sha256sum = %s\npackager = Grassfield\nbuilddate = %s\n' \
  "$name" "$name" "$ver" "$pkgbuild_sum" "$epoch" >.BUILDINFO
find . -type d -exec chmod 0755 {} +
find . -type f -exec chmod 0644 {} +
chmod 0755 "usr/bin/$bin"
find . -exec touch -h -d "@$epoch" {} +
list_package_files() {
  (
    export LC_COLLATE=C
    shopt -s dotglob globstar
    printf '%s\0' **/*
  )
}
owner_opts=(--uid 0 --gid 0 --uname root --gname root)
list_package_files | LANG=C bsdtar -cnf - --format=mtree --no-xattrs --no-acls "${owner_opts[@]}" \
  --options='!all,use-set,type,uid,gid,mode,time,size,sha256,link' --null --files-from - --exclude .MTREE | gzip -c -f -n >.MTREE
touch -d "@$epoch" .MTREE
list_package_files | LANG=C bsdtar --no-fflags --no-xattrs --no-acls --no-read-sparse "${owner_opts[@]}" -cnf - --null --files-from - |
  zstd -q -c -T1 -3 -- >"$work/$file"

# 5. The proof: extracted again with xattrs, ACLs and flags enabled, nothing appears; the tree is the canonical one.
cd "$work"
bsdtar -x -f "$work/$file" -C "$work/proof" --xattrs --acls --fflags --no-same-owner -p || die "the repacked package does not extract"
[[ -z $(getfattr -R -h -d -m - "$work/proof" 2>&1) ]] || die "the repacked package carries extended attributes"
fmt='%p %y %m\n'
[[ $(cd "$tree" && find . -mindepth 1 -printf "$fmt" | sort) == "$(cd "$work/proof" && find . -mindepth 1 -printf "$fmt" | sort)" ]] ||
  die "the repacked package extracts to another tree than the one checked"
[[ $(cd "$tree" && find . -type f -print0 | sort -z | xargs -0 sha256sum) == "$(cd "$work/proof" && find . -type f -print0 | sort -z | xargs -0 sha256sum)" ]] ||
  die "the repacked package has other file contents than the tree checked"
[[ $(bsdtar -tf "$work/$file" | sort -u | wc -l) == "$(bsdtar -tf "$work/$file" | wc -l)" ]] || die "the repacked package lists a path twice"
[[ -z $(bsdtar -tvf "$work/$file" | awk '$3 != "root" || $4 != "root" { print $9 }') ]] || die "the repacked package has a member not owned by root"
"$here/scripts/app-check.sh" "$work/$file" "$here/$app" || die "the repacked package fails app-check.sh"
