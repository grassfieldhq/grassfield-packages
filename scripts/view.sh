#!/usr/bin/env bash
# What the hosting's edge rule serves, as plain files, for file:// repositories in tests (grassfield ADR-0033 h.2).
#
#   view.sh TREE VIEW
#
# VIEW/<channel>/x86_64/ gets the channel's packages and their signatures, and the current snapshot's files under their
# fixed names (grassfield.db, grassfield.files, grassfield-notes.json, the catalog when there is one, and their .sig), as
# real files. The pointer is {"snapshot": "<id>"} (scripts/snapshot.py). The new view is made beside VIEW and swapped in
# with one rename per channel, so a client never reads half of it.
set -euo pipefail
[[ $# == 2 && -d $1 ]] || { echo "usage: view.sh TREE VIEW" >&2; exit 2; }
tree=$1 view=$2
for c in stable beta; do
  dir=$tree/$c/x86_64
  [[ -f $dir/pointer ]] || continue
  snap=$dir/snap/$(python3 -I "$(dirname "$0")/snapshot.py" current "$dir")
  new=$view/.$c.new
  rm -rf "$new" && mkdir -p "$new"
  find "$dir" -maxdepth 1 -type f -name '*.pkg.tar.zst*' -exec cp -t "$new" {} +
  find "$snap" -maxdepth 1 -type f ! -name manifest.json -exec cp -t "$new" {} +
  mkdir -p "$view/$c"
  rm -rf "$view/$c/x86_64.old"
  [[ -d $view/$c/x86_64 ]] && mv "$view/$c/x86_64" "$view/$c/x86_64.old"
  mv "$new" "$view/$c/x86_64"
  rm -rf "$view/$c/x86_64.old"
done
chmod -R a+rX "$view"
