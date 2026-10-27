#!/usr/bin/env bash
# The release a channel's publisher publishes (grassfield ADR-0033 h.2 as amended by ADR-0037 g: a run takes nothing from
# its trigger and publishes the latest state).
#
#   newest-release.sh CHANNEL [CURRENT] < tags
#
# Reads grassfield tags (vX.Y.Z, vX.Y.Z-betaN, vX.Y.Z-rcN; one per line, the tags whose build succeeded), keeps those that go
# to CHANNEL (stable: plain versions only; beta: all, ADR-0033 e), and prints the newest by pacman's vercmp when it is newer
# than CURRENT, the pkgver of the snapshot's grassfield-desktop (pkgrel ignored: a pkgrel rebuild is published by hand).
# Prints nothing when nothing is newer. Needs vercmp (pacman). Exit 0, 2 usage.
set -euo pipefail
[[ $# -ge 1 && $1 =~ ^(stable|beta)$ ]] || { echo "usage: newest-release.sh stable|beta [CURRENT] < tags" >&2; exit 2; }
channel=$1 current=${2:-}
current=${current%-*}   # pkgver-pkgrel -> pkgver
best="" bestv=""
while IFS= read -r tag; do
  [[ $tag =~ ^v([0-9]+\.[0-9]+\.[0-9]+)(-((beta|rc)[1-9][0-9]*))?$ ]] || continue
  [[ $channel == beta || -z ${BASH_REMATCH[3]} ]] || continue
  v=${BASH_REMATCH[1]}${BASH_REMATCH[3]}
  if [[ -z $bestv ]] || (($(vercmp "$v" "$bestv") > 0)); then best=$tag bestv=$v; fi
done
[[ -n $best ]] || exit 0
[[ -z $current ]] || (($(vercmp "$bestv" "$current") > 0)) || exit 0
printf '%s\n' "$best"
