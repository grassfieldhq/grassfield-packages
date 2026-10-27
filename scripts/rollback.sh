#!/usr/bin/env bash
# ADR-0033 h.2's deliberate rollback of a channel: a NEW snapshot with an older snapshot's databases and notes, never the
# pointer moved back (probe R4).
#
#   rollback.sh --tree DIR --channel stable|beta --to ID --keyring-dir DIR
#
#   --keyring-dir DIR  the keyring folder the publisher checks signatures with (grassfield-keyring's files)
#
# Moving the pointer back to the older snapshot is never done: a client already on the newer one would get the older
# database as "not modified" (its copy is newer) and the older signature, so every `omarchy update` of that client would
# fail ("signature … is invalid"). Here:
#   1. ID must be an existing snapshot of the channel, other than the current one, whose release is older;
#   2. the release builds of the channel newer than ID's release are withdrawn: moved from releases/<channel>/ to
#      withdrawn/<channel>/, where the channel's publisher, which publishes the newest release build, never reads them, so
#      its next run does not put the bad release back; a newer tag's release build is published as usual; they come back
#      if the publisher refuses the rollback (step 3), so a refused rollback changes nothing;
#   3. the channel's one publisher writes the new snapshot (tools/publish.py --rollback-to: ID's databases and notes with
#      their signatures, checked against --keyring-dir first, the current snapshot's other files such as the catalog, the
#      pointer only if it has not moved).
# No key is needed. Clients that installed the newer release keep it (pacman does not downgrade); when they must move,
# the fix is a new release (a new tag, or a pkgrel rebuild above the bad one, build-channel.sh --pkgrel). Needs vercmp and
# bsdtar (an Arch container). On the hosting, the same moves on the bucket, by the owner, inside the channel's publishing
# concurrency group.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tree="" channel="" to="" keyring_dir=""
usage() { echo "usage: rollback.sh --tree DIR --channel stable|beta --to ID --keyring-dir DIR" >&2; exit 2; }
die() { echo "rollback.sh: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --tree) tree=$2 ;;
    --channel) channel=$2 ;;
    --to) to=$2 ;;
    --keyring-dir) keyring_dir=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $tree && $channel =~ ^(stable|beta)$ && -d $keyring_dir ]] || usage
[[ $to =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]] || die "--to '$to' is not a snapshot id"
dir=$tree/$channel/x86_64
old=$dir/snap/$to
cur=$(python3 -I "$here/scripts/snapshot.py" current "$dir") || die "$dir/pointer is not a pointer"
[[ -n $cur ]] || die "$channel has no current snapshot"
[[ -f $old/grassfield.db && -f $old/manifest.json ]] || die "no snapshot $to in $channel"
[[ $to != "$cur" ]] || die "$to is the current snapshot"
# The manifests' releases only (JSON): the databases are read by tools/publish.py, after their signatures are checked.
release_of() { python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["release"])' "$1"; }
release=$(release_of "$old/manifest.json") was=$(release_of "$dir/snap/$cur/manifest.json")
(($(vercmp "$release" "$was") < 0)) || die "$to holds release $release, not older than the current $was"

# The bad releases leave what the publisher reads before the rollback is published (so that no run in between can publish
# them again), and come back if the publisher refuses the rollback: a refused rollback withdraws nothing.
withdrawn=()
for rel in "$tree/releases/$channel"/*/; do
  [[ -d $rel ]] || continue
  v=$(basename "$rel")
  if (($(vercmp "$v" "$release") > 0)); then
    mkdir -p "$tree/withdrawn/$channel"
    [[ ! -e $tree/withdrawn/$channel/$v ]] || die "withdrawn/$channel/$v exists already"
    mv "${rel%/}" "$tree/withdrawn/$channel/$v"
    withdrawn+=("$v")
    echo "$channel: release build $v withdrawn"
  fi
done

if ! python3 -I "$here/tools/publish.py" --store "$tree" --channel "$channel" --keyring-dir "$keyring_dir" --rollback-to "$to"; then
  for v in "${withdrawn[@]}"; do
    mv "$tree/withdrawn/$channel/$v" "$tree/releases/$channel/$v"
    echo "$channel: release build $v put back"
  done
  die "the publisher refused the rollback: nothing changed"
fi
