#!/usr/bin/env bash
# Check a channel tree against the contract before it is tested or published (grassfield ADR-0033 b.6, g, h.2).
#
#   check-tree.sh --tree DIR (--keyring FILE | --trusted [--keyring-src DIR])
#
#   --keyring FILE  the public key(s) that signed the tree, as `gpg --export` writes them: CI and test builds, signed by a
#                   throwaway key while the grassfield-keyring they carry holds no key (U23)
#   --trusted       as a client checks it (ADR-0033 b.2, d.8): each set's signatures by a key of the grassfield-keyring
#                   package its own database names, whose primary is in that keyring's grassfield-trusted and not in its
#                   grassfield-revoked (gpgv's VALIDSIG argument 10). For the project's key: the release job, the tests
#                   whose keyring carries their key
#   --keyring-src DIR  with --trusted: that grassfield-keyring package must be DIR's (keyring/ in git), the whole package:
#                   its paths, its three files and install script byte for byte, its .PKGINFO (scripts/keyring-check.sh)
# For each <channel>/x86_64 with a pointer ({"snapshot": "<id>"}), the snapshot it names, and for each release build
# releases/<channel>/<version> (what the channel's publisher reads, ADR-0037 g): grassfield.db, grassfield.files and
# grassfield-notes.json, each with a valid signature; a snapshot's manifest.json names each of its files with its SHA-256;
# every package the database names is beside the packages (the channel folder, the release build) with the SHA-256 the
# database records and a valid signature, is named grassfield-* and replaces nothing, and grassfield-desktop depends on
# grassfield-keyring (grassfield ADR-0033 O22: it carries the key that verifies the updates); the notes are version 1
# of that channel, at most 64 KiB and 20 releases, `en` everywhere, and their first release is the database's
# grassfield-desktop (and a release build's version). A release build holds nothing else: the packages its database
# names, the three files, and their .sig (what is uploaded). No symbolic link anywhere. Reads only. Exit 0 all PASS,
# 1 a FAIL, 2 usage.
set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
usage() { echo "usage: check-tree.sh --tree DIR (--keyring FILE | --trusted [--keyring-src DIR])" >&2; exit 2; }
tree="" keyring="" trusted="" src=""
while (($#)); do
  case $1 in
    --tree) tree=${2:-}; shift ;;
    --keyring) keyring=${2:-}; shift ;;
    --trusted) trusted=1 ;;
    --keyring-src) src=${2:-}; shift ;;
    *) usage ;;
  esac
  shift
done
[[ -d $tree && (-s $keyring && -z $trusted || -z $keyring && -n $trusted) ]] || usage
[[ -z $src || -n $trusted && -f $src/PKGBUILD ]] || usage
[[ -z $keyring ]] || keyring=$(realpath "$keyring")
fails=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; fails=$((fails + 1)); }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
allowed="" denied=""
verify() { # file: file.sig is good, and with --trusted its primary key is trusted and not revoked
  local primary
  primary=$(gpgv --keyring "$keyring" --status-fd 1 "$1.sig" "$1" 2>/dev/null | awk '$2 == "VALIDSIG" { print $12 }') || return 1
  [[ -n $primary ]] || return 1
  [[ -z $trusted ]] || { grep -qx "$primary" <<<"$allowed" && ! grep -qx "$primary" <<<"$denied"; }
}
keyring_of() { # label, the database, the folder of its packages: the keys that set's grassfield-keyring trusts
  local f k=$work/keyring
  f=$(bsdtar -xOf "$2" 2>/dev/null | awk '/^%FILENAME%$/ { getline; if ($0 ~ /^grassfield-keyring-/) print }' | head -n 1)
  rm -rf "$k" && mkdir -p "$k"
  if [[ -z $f || ! -f $3/$f ]] || ! bsdtar -xf "$3/$f" -C "$k" usr/share/grassfield/pacman-keyring 2>/dev/null; then
    bad "$1: no grassfield-keyring to check its signatures with"
    keyring=/dev/null allowed="" denied=""
    return
  fi
  k=$k/usr/share/grassfield/pacman-keyring
  keyring=$k/grassfield.gpg
  if [[ -n $src ]]; then
    local why
    if why=$("$here/scripts/keyring-check.sh" "$3/$f" "$src" 2>&1); then
      ok "$1: its grassfield-keyring is $src's, the whole package"
    else
      bad "$1: its grassfield-keyring is not $src's: refused ($why)"; keyring=/dev/null allowed="" denied=""; return
    fi
  fi
  allowed=$(sed -n 's/^\([0-9A-F]\{40\}\):.*/\1/p' "$k/grassfield-trusted")
  denied=$(sed -n 's/^\([0-9A-F]\{40\}\).*/\1/p' "$k/grassfield-revoked")
  [[ -n $allowed ]] && ok "$1: signatures checked with its grassfield-keyring ($f, $(wc -l <<<"$allowed") trusted key(s))" ||
    bad "$1: its grassfield-keyring ($f) trusts no key"
}

links=$(find "$tree" -type l | head -n 3)
[[ -z $links ]] && ok "no symbolic link in the tree" || bad "symbolic links (repo-add's links are never published): $links"
# label, the folder of grassfield.db and the rest, the folder of the packages, the channel, the expected version or ""
check_set() {
  local l=$1 meta=$2 pkgs=$3 c=$4 want=$5 f desc desktop sum
  [[ -z $trusted ]] || keyring_of "$l" "$meta/grassfield.db" "$pkgs"
  for f in grassfield.db grassfield.files grassfield-notes.json; do
    if [[ -f $meta/$f && -f $meta/$f.sig ]] && verify "$meta/$f"; then ok "$l: $f signed"; else bad "$l: $f or its signature missing, invalid or not by a trusted key"; fi
  done
  desc=$(bsdtar -xOf "$meta/grassfield.db" 2>/dev/null)
  mapfile -t files < <(awk '/^%FILENAME%$/ { getline f } /^%SHA256SUM%$/ { getline s; print f, s }' <<<"$desc")
  ((${#files[@]})) || bad "$l: the database names no package"
  for f in "${files[@]}"; do
    sum=${f#* } f=${f%% *}
    if [[ -f $pkgs/$f && -f $pkgs/$f.sig ]] && verify "$pkgs/$f" && [[ $(sha256sum <"$pkgs/$f") == "$sum  -" ]]; then
      ok "$l: $f signed, the database's SHA-256"
    else
      bad "$l: $f missing, its signature missing, invalid or untrusted, or not the SHA-256 the database records"
    fi
  done
  if [[ -n $want ]]; then
    local expected actual
    expected=$( { printf '%s\n' grassfield.db grassfield.files grassfield-notes.json; for f in "${files[@]}"; do echo "${f%% *}"; done; } |
      sed 'p; s/$/.sig/' | sort)
    actual=$(ls -A "$meta" | sort)
    [[ $actual == "$expected" ]] && ok "$l: nothing else in the folder (what is uploaded)" ||
      bad "$l: other files than its packages, the three files and their .sig: $(comm -13 <(echo "$expected") <(echo "$actual") | tr '\n' ' ')"
  fi
  names=$(awk '/^%NAME%$/ { getline; print }' <<<"$desc" | grep -v '^grassfield-' || true)
  [[ -z $names ]] && ok "$l: every package is named grassfield-*" || bad "$l: packages not named grassfield-*: $names"
  grep -qx '%REPLACES%' <<<"$desc" && bad "$l: a package declares replaces=" || ok "$l: no package declares replaces="
  desktop=$(awk '/^%NAME%$/ { getline n } /^%VERSION%$/ { getline v; if (n == "grassfield-desktop") { print v; exit } }' <<<"$desc")
  [[ -z $want || $desktop == "$want" ]] || bad "$l: grassfield-desktop $desktop in the database of release build $want"
  awk '/^%NAME%$/ { getline n; next } /^%DEPENDS%$/ { d = 1; next } /^$/ { d = 0 }
       d && n == "grassfield-desktop" && $0 == "grassfield-keyring" { found = 1 } END { exit !found }' <<<"$desc" &&
    ok "$l: grassfield-desktop depends on grassfield-keyring" ||
    bad "$l: grassfield-desktop does not depend on grassfield-keyring (grassfield ADR-0033 O22)"
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
  id=$(python3 -I "$here/scripts/snapshot.py" current "$dir" 2>/dev/null)
  if [[ ! $id =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ || ! -d $dir/snap/$id ]]; then
    bad "$c: the pointer names no snapshot ($id)"
    continue
  fi
  python3 -I - "$dir/snap/$id" <<'PY' && ok "$c $id: manifest.json names every file with its SHA-256" || bad "$c $id: manifest.json does not match the snapshot"
import hashlib, json, os, sys
d = sys.argv[1]
m = json.loads(open(os.path.join(d, "manifest.json"), "rb").read())
names = set(os.listdir(d)) - {"manifest.json"}
assert set(m["files"]) == names, (sorted(m["files"]), sorted(names))
for n, s in m["files"].items():
    assert hashlib.sha256(open(os.path.join(d, n), "rb").read()).hexdigest() == s, n
PY
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
