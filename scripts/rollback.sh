#!/usr/bin/env bash
# Roll a channel back by publishing a NEW snapshot with the packages of an older one (grassfield ADR-0033 h.2, probe R4).
#
#   rollback.sh --tree DIR --channel stable|beta --to ID --gnupghome DIR --key FPR
#
# Moving the pointer back to the older snapshot is never done: a client already on the newer one would get the older
# database as "not modified" (its copy is newer) and the older signature, so every `omarchy update` of that client would
# fail ("signature … is invalid"). Here:
#   - ID must be an existing snapshot of the channel, older than the current one (its grassfield-desktop older);
#   - the release builds of the channel newer than ID's release are withdrawn: moved from releases/<channel>/ to
#     withdrawn/<channel>/, where the channel's publisher, which publishes the newest release build, never reads them, so
#     its next run does not put the bad release back; a newer tag's release build is published as usual;
#   - the database is made again from the packages ID names (a new file, so every client downloads it), signed with ID's
#     notes, and the current snapshot's other files are kept (the catalog); the pointer moves forward to it, only if it
#     has not moved (scripts/snapshot.py).
# Clients that installed the newer release keep it (pacman does not downgrade); when they must move, the fix is a new
# release (a new tag, or a pkgrel rebuild above the bad one, build-channel.sh --pkgrel). Runs only as root inside a
# throwaway container (repo-add). On the hosting, the same moves on the bucket, by the owner, inside the channel's
# publishing concurrency group.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tree="" channel="" to="" gnupghome="" key=""
usage() { echo "usage: rollback.sh --tree DIR --channel stable|beta --to ID --gnupghome DIR --key FPR" >&2; exit 2; }
die() { echo "rollback.sh: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --tree) tree=$2 ;;
    --channel) channel=$2 ;;
    --to) to=$2 ;;
    --gnupghome) gnupghome=$2 ;;
    --key) key=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $tree && $channel =~ ^(stable|beta)$ && -n $gnupghome && $key =~ ^[0-9A-F]{40}$ ]] || usage
[[ $to =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]] || die "--to '$to' is not a snapshot id"
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "rollback.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
dir=$tree/$channel/x86_64
old=$dir/snap/$to
cur=$(python3 -I "$here/scripts/snapshot.py" current "$dir") || die "$dir/pointer is not a pointer"
[[ -n $cur ]] || die "$channel has no current snapshot"
[[ -f $old/grassfield.db && -f $old/grassfield-notes.json && -f $old/manifest.json ]] || die "no snapshot $to in $channel"
[[ $to != "$cur" ]] || die "$to is the current snapshot"
desktop() { bsdtar -xOf "$1" | awk '/^%NAME%$/ { getline n } /^%VERSION%$/ { getline v; if (n == "grassfield-desktop") { print v; exit } }'; }
was=$(desktop "$dir/snap/$cur/grassfield.db") back=$(desktop "$old/grassfield.db")
(($(vercmp "$back" "$was") < 0)) || die "$to holds grassfield-desktop $back, not older than the current $was"
release=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["release"])' "$old/manifest.json")
sign() { gpg --homedir "$gnupghome" --batch --no-tty --local-user "$key!" --detach-sign --no-armor --yes --output "$1.sig" "$1"; }

# The bad releases leave what the publisher reads.
for rel in "$tree/releases/$channel"/*/; do
  [[ -d $rel ]] || continue
  v=$(basename "$rel")
  if (($(vercmp "$v" "$release") > 0)); then
    mkdir -p "$tree/withdrawn/$channel"
    [[ ! -e $tree/withdrawn/$channel/$v ]] || die "withdrawn/$channel/$v exists already"
    mv "${rel%/}" "$tree/withdrawn/$channel/$v"
    echo "$channel: release build $v withdrawn"
  fi
done

work=$(mktemp -d)
mapfile -t files < <(bsdtar -xOf "$old/grassfield.db" | awk '/^%FILENAME%$/ { getline; print }')
((${#files[@]})) || die "$old/grassfield.db names no package"
repo-add --quiet "$work/grassfield.db.tar.gz" "${files[@]/#/$dir/}" >/dev/null
src=$work/snapshot && mkdir "$src"
cp -L "$work/grassfield.db.tar.gz" "$src/grassfield.db"
cp -L "$work/grassfield.files.tar.gz" "$src/grassfield.files"
cp "$old/grassfield-notes.json" "$src/grassfield-notes.json"
for f in grassfield.db grassfield.files grassfield-notes.json; do sign "$src/$f"; done
id=$(python3 -I "$here/scripts/snapshot.py" write "$dir" --release "$release" --source "$src" --expect "$cur")
rm -rf "$work"
echo "$channel: snapshot $id, the packages of $to (grassfield-desktop $back, was $was)"
