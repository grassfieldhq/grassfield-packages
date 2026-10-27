#!/usr/bin/env bash
# keyring/grassfield-keyring.install's pre_remove on a trusted list whose last line has no newline, with pacman-key
# stubbed (it only logs its arguments): main's version (b0e8494) against this branch's. Pure bash in a scratch folder.
set -u
repo=$1 w=$(mktemp -d)
A=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA B=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
for rev in b0e8494 HEAD; do
  r=$w/$rev && mkdir -p "$r/usr/bin" "$r/usr/share/grassfield/pacman-keyring"
  printf '#!/bin/sh\necho "$*" >>"%s/log"\n' "$r" >"$r/usr/bin/pacman-key" && chmod 755 "$r/usr/bin/pacman-key"
  printf '%s:4:\n%s:4:' "$A" "$B" >"$r/usr/share/grassfield/pacman-keyring/grassfield-trusted"
  git -C "$repo" show "$rev:keyring/grassfield-keyring.install" >"$w/install-$rev"
  (cd "$r" && bash -c ". '$w/install-$rev' && pre_remove")
  echo "$rev ($(git -C "$repo" rev-parse --short "$rev")): pre_remove exit $?, deleted: $(grep '^--delete' "$r/log" | cut -c10-13 | tr '\n' ' ')"
done
rm -rf "$w"
