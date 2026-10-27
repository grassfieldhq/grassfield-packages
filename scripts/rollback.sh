#!/usr/bin/env bash
# Roll a channel back by publishing a NEW snapshot with the packages of an older one (grassfield ADR-0033 h.2, probe R4).
#
#   rollback.sh --tree DIR --channel stable|beta --to ID --gnupghome DIR --key FPR
#
# Moving the pointer back to the older snapshot is never done: a client already on the newer one would get the older
# database as "not modified" (its copy is newer) and the older signature, so every `omarchy update` of that client would
# fail ("signature … is invalid"). Here the database is made again from the packages the older snapshot names (a new file,
# so every client downloads it), signed with its notes, and the pointer moves forward to it. Clients that installed the
# newer release keep it (pacman does not downgrade); when they must move, the previous release is rebuilt with a higher
# pkgrel (build-channel.sh --pkgrel). Runs only as root inside a throwaway container (repo-add).
set -euo pipefail
tree="" channel="" to="" gnupghome="" key=""
usage() { echo "usage: rollback.sh --tree DIR --channel stable|beta --to ID --gnupghome DIR --key FPR" >&2; exit 2; }
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
[[ -n $tree && $channel =~ ^(stable|beta)$ && -n $to && -n $gnupghome && $key =~ ^[0-9A-F]{40}$ ]] || usage
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "rollback.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
dir=$tree/$channel/x86_64
old=$dir/snap/$to
[[ -f $old/grassfield.db && -f $old/grassfield-notes.json ]] || { echo "rollback.sh: no snapshot $old" >&2; exit 1; }
sign() { gpg --homedir "$gnupghome" --batch --no-tty --local-user "$key!" --detach-sign --no-armor --yes --output "$1.sig" "$1"; }

work=$(mktemp -d)
mapfile -t files < <(bsdtar -xOf "$old/grassfield.db" | awk '/^%FILENAME%$/ { getline; print }')
((${#files[@]})) || { echo "rollback.sh: $old/grassfield.db names no package" >&2; exit 1; }
repo-add --quiet "$work/grassfield.db.tar.gz" "${files[@]/#/$dir/}" >/dev/null
id=$(date -u +%Y%m%dT%H%M%SZ)-${to: -12}   # the date of now, the commit of the packages it republishes
snap=$dir/snap/$id
[[ ! -e $snap ]] || { echo "rollback.sh: snapshot $snap exists already" >&2; exit 1; }
mkdir "$snap"
cp -L "$work/grassfield.db.tar.gz" "$snap/grassfield.db"
cp -L "$work/grassfield.files.tar.gz" "$snap/grassfield.files"
cp "$old/grassfield-notes.json" "$snap/grassfield-notes.json"
for f in grassfield.db grassfield.files grassfield-notes.json; do sign "$snap/$f"; done
rm -rf "$work"
printf '%s\n' "$id" >"$dir/pointer.new"
mv -f "$dir/pointer.new" "$dir/pointer"
echo "$channel: snapshot $id, the packages of $to"
