#!/usr/bin/env bash
# The second pass of the canonical repack, run where the package is about to be signed (README.md, "Bundled apps"; fifth review
# of grassfield-packages PR #22).
#
#   app-reverify.sh --app NAME --in PACKAGE
#
# The package that reaches build-channel.sh was made by scripts/app-repack.sh in another container. The signed file would
# then depend on that one container alone: a compromised repack container could leave something in the file that nothing
# later notices. So the file is repacked AGAIN here, in the container that signs (same image, so the same libarchive and zstd),
# and must equal its own repack byte for byte: the repack is deterministic and idempotent, so a canonical package is its own
# fixed point, and anything that is not (an xattr, a changed mode or time, an extra member, a flipped byte) is refused.
# Needs what app-repack.sh needs (root in a container, or fakeroot in tests). Exit 0 identical, 1 refused, 2 usage.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
app="" in=""
usage() { echo "usage: app-reverify.sh --app grassfield-sanaga|grassfield-notes --in PACKAGE" >&2; exit 2; }
die() { echo "app-reverify.sh: ${in##*/}: $*" >&2; exit 1; }
while (($#)); do
  [[ $# -ge 2 ]] || usage
  case $1 in --app) app=$2 ;; --in) in=$2 ;; *) usage ;; esac
  shift 2
done
case $app in grassfield-sanaga | grassfield-notes) ;; *) usage ;; esac
[[ -f $in && ! -L $in ]] || usage
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/out"
"$here/scripts/app-repack.sh" --app "$app" --in "$in" --out "$tmp/out" >"$tmp/log" 2>&1 || { tail -n 5 "$tmp/log" >&2; die "its own repack refuses it"; }
cmp -s "$tmp/out/${in##*/}" "$in" || die "differs from its own repack (not canonical: something in it survived the first repack)"
echo "reverified ${in##*/}"
