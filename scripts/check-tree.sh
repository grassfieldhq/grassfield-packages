#!/usr/bin/env bash
# Check a channel tree against the contract before it is tested or published (grassfield ADR-0033 b.6, g, h.2).
#
#   check-tree.sh --tree DIR --keyring FILE
#
#   --keyring FILE  the public key(s) that signed the tree, as `gpg --export` writes them (a throwaway key for CI and test
#                   builds, the project's keyring once it exists)
# For each <channel>/x86_64 with a pointer, the snapshot it names, and for each release build releases/<channel>/<version>
# (what the channel's publisher reads, ADR-0037 g): grassfield.db, grassfield.files and grassfield-notes.json, each with a
# valid signature; every package the database names is beside the packages (the channel folder, the release build) with
# the SHA-256 the database records and a valid signature, is named grassfield-* and replaces nothing; the notes are
# version 1 of that channel, at most 64 KiB and 20 releases, `en` everywhere, and their first release is the database's
# grassfield-desktop (and a release build's version). No symbolic link anywhere. Reads only. Exit 0 all PASS, 1 a FAIL,
# 2 usage.
set -uo pipefail

tree="" keyring=""
while (($#)); do
  case $1 in
    --tree) tree=${2:-} ;;
    --keyring) keyring=${2:-} ;;
    *) echo "usage: check-tree.sh --tree DIR --keyring FILE" >&2; exit 2 ;;
  esac
  shift 2 || { echo "usage: check-tree.sh --tree DIR --keyring FILE" >&2; exit 2; }
done
[[ -d $tree && -s $keyring ]] || { echo "usage: check-tree.sh --tree DIR --keyring FILE" >&2; exit 2; }
fails=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; fails=$((fails + 1)); }
verify() { gpgv --keyring "$(realpath "$keyring")" "$1.sig" "$1" >/dev/null 2>&1; }

links=$(find "$tree" -type l | head -n 3)
[[ -z $links ]] && ok "no symbolic link in the tree" || bad "symbolic links (repo-add's links are never published): $links"
# label, the folder of grassfield.db and the rest, the folder of the packages, the channel, the expected version or ""
check_set() {
  local l=$1 meta=$2 pkgs=$3 c=$4 want=$5 f desc desktop sum
  for f in grassfield.db grassfield.files grassfield-notes.json; do
    if [[ -f $meta/$f && -f $meta/$f.sig ]] && verify "$meta/$f"; then ok "$l: $f signed"; else bad "$l: $f or its signature missing or invalid"; fi
  done
  desc=$(bsdtar -xOf "$meta/grassfield.db" 2>/dev/null)
  mapfile -t files < <(awk '/^%FILENAME%$/ { getline f } /^%SHA256SUM%$/ { getline s; print f, s }' <<<"$desc")
  ((${#files[@]})) || bad "$l: the database names no package"
  for f in "${files[@]}"; do
    sum=${f#* } f=${f%% *}
    if [[ -f $pkgs/$f && -f $pkgs/$f.sig ]] && verify "$pkgs/$f" && [[ $(sha256sum <"$pkgs/$f") == "$sum  -" ]]; then
      ok "$l: $f signed, the database's SHA-256"
    else
      bad "$l: $f, its signature or the SHA-256 the database records missing or invalid"
    fi
  done
  names=$(awk '/^%NAME%$/ { getline; print }' <<<"$desc" | grep -v '^grassfield-' || true)
  [[ -z $names ]] && ok "$l: every package is named grassfield-*" || bad "$l: packages not named grassfield-*: $names"
  grep -qx '%REPLACES%' <<<"$desc" && bad "$l: a package declares replaces=" || ok "$l: no package declares replaces="
  desktop=$(awk '/^%NAME%$/ { getline n } /^%VERSION%$/ { getline v; if (n == "grassfield-desktop") { print v; exit } }' <<<"$desc")
  [[ -z $want || $desktop == "$want" ]] || bad "$l: grassfield-desktop $desktop in the database of release build $want"
  python3 -I - "$meta/grassfield-notes.json" "$c" "$desktop" <<'PY' && ok "$l: notes valid, newest release $desktop" || bad "$l: notes invalid"
import json, os, sys
path, channel, desktop = sys.argv[1:4]
if os.path.getsize(path) > 65536:
    sys.exit("larger than 64 KiB")
d = json.loads(open(path, "rb").read().decode("utf-8"))
r = d.get("releases")
assert d.get("version") == 1 and d.get("channel") == channel and isinstance(r, list) and 0 < len(r) <= 20
assert all(isinstance(x.get("notes", {}).get("en"), str) and len(x["notes"]["en"]) <= 8000 for x in r)
assert r[0]["version"] == desktop, (r[0]["version"], desktop)
PY
}

channels=0
for dir in "$tree"/stable/x86_64 "$tree"/beta/x86_64; do
  [[ -f $dir/pointer ]] || continue
  channels=$((channels + 1))
  c=$(basename "$(dirname "$dir")")
  id=$(cat "$dir/pointer")
  if [[ ! $id =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ || ! -d $dir/snap/$id ]]; then
    bad "$c: the pointer names no snapshot ($id)"
    continue
  fi
  check_set "$c $id" "$dir/snap/$id" "$dir" "$c" ""
done
for rel in "$tree"/releases/*/*/; do
  [[ -d $rel ]] || continue
  channels=$((channels + 1))
  rel=${rel%/} c=$(basename "$(dirname "$rel")")
  [[ $c =~ ^(stable|beta)$ ]] || { bad "release build of no channel: $rel"; continue; }
  check_set "release build $c/${rel##*/}" "$rel" "$rel" "$c" "${rel##*/}"
done
((channels)) || bad "no channel with a pointer and no release build in $tree"
echo "check-tree: $fails failure(s)"
((fails == 0))
