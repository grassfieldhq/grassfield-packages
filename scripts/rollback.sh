#!/usr/bin/env bash
# ADR-0033 h.2's deliberate rollback of a channel: a NEW snapshot with an older snapshot's databases and notes, never the
# pointer moved back (probe R4).
#
#   rollback.sh --tree DIR --channel stable|beta --to ID
#
# Moving the pointer back to the older snapshot is never done: a client already on the newer one would get the older
# database as "not modified" (its copy is newer) and the older signature, so every `omarchy update` of that client would
# fail ("signature … is invalid"). Here:
#   1. ID must be an existing snapshot of the channel, other than the current one, whose grassfield-desktop is older;
#   2. the release builds of the channel newer than ID's release are withdrawn: moved from releases/<channel>/ to
#      withdrawn/<channel>/, where the channel's publisher, which publishes the newest release build, never reads them, so
#      its next run does not put the bad release back; a newer tag's release build is published as usual;
#   3. the channel's one publisher writes the new snapshot (tools/publish.py --rollback-to: ID's databases and notes with
#      their signatures, the current snapshot's other files such as the catalog, the pointer only if it has not moved).
# No key is needed. Clients that installed the newer release keep it (pacman does not downgrade); when they must move,
# the fix is a new release (a new tag, or a pkgrel rebuild above the bad one, build-channel.sh --pkgrel). Needs vercmp and
# bsdtar (an Arch container). On the hosting, the same moves on the bucket, by the owner, inside the channel's publishing
# concurrency group.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tree="" channel="" to=""
usage() { echo "usage: rollback.sh --tree DIR --channel stable|beta --to ID" >&2; exit 2; }
die() { echo "rollback.sh: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --tree) tree=$2 ;;
    --channel) channel=$2 ;;
    --to) to=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $tree && $channel =~ ^(stable|beta)$ ]] || usage
[[ $to =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]] || die "--to '$to' is not a snapshot id"
dir=$tree/$channel/x86_64
old=$dir/snap/$to
cur=$(python3 -I "$here/scripts/snapshot.py" current "$dir") || die "$dir/pointer is not a pointer"
[[ -n $cur ]] || die "$channel has no current snapshot"
[[ -f $old/grassfield.db && -f $old/manifest.json ]] || die "no snapshot $to in $channel"
[[ $to != "$cur" ]] || die "$to is the current snapshot"
desktop() { bsdtar -xOf "$1" | awk '/^%NAME%$/ { getline n } /^%VERSION%$/ { getline v; if (n == "grassfield-desktop") { print v; exit } }'; }
was=$(desktop "$dir/snap/$cur/grassfield.db") back=$(desktop "$old/grassfield.db")
(($(vercmp "$back" "$was") < 0)) || die "$to holds grassfield-desktop $back, not older than the current $was"
release=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["release"])' "$old/manifest.json")

# The bad releases leave what the publisher reads, before the rollback is published.
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

python3 -I "$here/tools/publish.py" --store "$tree" --channel "$channel" --rollback-to "$to"
