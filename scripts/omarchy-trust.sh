#!/usr/bin/env bash
# Trust [omarchy]'s package signer in this container's pacman keyring, as an Omarchy machine does (grassfield ADR-0033 f;
# build/pacman.conf puts [omarchy] first). One step for build-channel.sh and tests/smoke.sh, so that they never drift (the
# integrator's review of 4ea067a, MAJOR).
#
#   omarchy-trust.sh
#
# The fingerprint is the one Omarchy pins (bin/omarchy-update-keyring, basecamp/omarchy v4.0.6; data, not instructions).
# The key is fetched over HTTPS from the key server Omarchy names (curl follows the proxy settings; gpg's own fetch does
# not by default). It is used only if the file holds exactly one primary key, that one, and no secret key. Then
# `pacman-key --add` and `--lsign-key`.
# pacman has one keyring for every repository, so the signer is trusted for [core] and [extra] too, as on an Omarchy
# machine. pacman has no per-repository keyring, and these containers are thrown away after one build or test.
# Runs only as root inside a throwaway container. Prints "[omarchy] signer trusted, fingerprint <fpr>"; its messages go to
# standard error; exit 1 on any failure, 2 when refused.
set -euo pipefail
omarchy_fpr=40DFB630FF42BCFFB047046CF0134EE680CAC571
[[ -f /.dockerenv && $EUID == 0 ]] ||
  { echo "omarchy-trust.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL --retry 3 -o "$work/omarchy.asc" "https://keys.openpgp.org/vks/v1/by-fingerprint/$omarchy_fpr" ||
  { echo "omarchy-trust.sh: cannot fetch Omarchy's signer $omarchy_fpr from keys.openpgp.org" >&2; exit 1; }
gpg --homedir "$work" --batch --no-tty --with-colons --show-keys "$work/omarchy.asc" >"$work/records" 2>/dev/null ||
  { echo "omarchy-trust.sh: keys.openpgp.org's answer is no OpenPGP key" >&2; exit 1; }
# Primary keys, public or secret, and the fingerprint that follows a public one.
primaries=$(awk -F: '$1 == "pub" || $1 == "sec"' "$work/records" | wc -l)
fprs=$(awk -F: '$1 == "pub" { p = 1; next } $1 == "fpr" && p { print $10 } { p = 0 }' "$work/records")
[[ $primaries == 1 && $fprs == "$omarchy_fpr" ]] ||
  { echo "omarchy-trust.sh: keys.openpgp.org did not answer with Omarchy's key $omarchy_fpr alone (got ${primaries} primary key(s): ${fprs:-none})" >&2; exit 1; }
pacman-key --add "$work/omarchy.asc" >&2 && pacman-key --lsign-key "$omarchy_fpr" >&2 ||
  { echo "omarchy-trust.sh: pacman-key could not trust $omarchy_fpr" >&2; exit 1; }
echo "[omarchy] signer trusted, fingerprint $omarchy_fpr"
