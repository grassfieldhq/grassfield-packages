#!/usr/bin/env bash
# Smoke test of a built channel tree, the CI test job (grassfield ADR-0033 g): a fresh Omarchy stable machine installs the
# built packages from it and Grassfield's Software Update client answers.
#
#   smoke.sh --tree DIR --keyring FILE
#
#   --keyring FILE  the public key that signed the tree (the build's throwaway key); trusted here, in this container only
# Runs only as root inside a throwaway Arch container. Checks: the tree against the contract (check-tree.sh); the
# [grassfield] section written by hand (the first installation of ADR-0033 b.3a) and `pacman -S` of grassfield-desktop,
# grassfield-compositor and grassfield-icons with every signature required (grassfield-keyring, grassfield-sanaga and
# grassfield-notes come as grassfield-desktop's dependencies, ADR-0033 O22 and ADR-0055); grassfield-update-check, as a user, answers
# up-to-date; grassfield-channel-set reads the channel and, in a build that pins no key yet (O11), refuses to set
# anything up; `pacman -Rns` leaves no [grassfield] line, no file and a working pacman. Exit 0 all PASS, 1 a FAIL.
set -uo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tree="" keyring=""
while (($#)); do
  case $1 in
    --tree) tree=${2:-} ;;
    --keyring) keyring=${2:-} ;;
    *) echo "usage: smoke.sh --tree DIR --keyring FILE" >&2; exit 2 ;;
  esac
  shift 2 || exit 2
done
[[ -d $tree && -s $keyring ]] || { echo "usage: smoke.sh --tree DIR --keyring FILE" >&2; exit 2; }
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "smoke.sh: refused: runs only as root inside a throwaway container" >&2; exit 2; }
fails=0 checks=0
expect() { local d=$1; shift; checks=$((checks + 1)); if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
log=/tmp/smoke.log
# `pacman -Q NAME` also answers for a package that PROVIDES NAME (pacman -Q sh prints bash), so "no package named sanaga" is
# the other way round: pacman -Qq NAME names the package that answers, which must be the one expected (tests/test_apps.py
# runs this function against a fake pacman, both ways).
only_provided_by() { [[ $(pacman -Qq "$1" 2>/dev/null) == "$2" ]]; }

install -m644 "$here/build/pacman.conf" /etc/pacman.conf
# [omarchy] comes first (an Omarchy stable machine): its signer is trusted the way the build trusts it, by Omarchy's pinned
# fingerprint (scripts/omarchy-trust.sh; the integrator's review of 4ea067a), or quickshell from it would be refused.
{ pacman-key --init && pacman-key --populate archlinux && "$here/scripts/omarchy-trust.sh" &&
  pacman -Syu --noconfirm --needed python sudo; } >>"$log" 2>&1 ||
  { echo "FAIL: the Omarchy stable machine (see $log)"; exit 1; }
expect "the tree follows the contract (check-tree.sh)" "$here/scripts/check-tree.sh" --tree "$tree" --keyring "$keyring"
fpr=$(gpg --homedir "$(mktemp -d)" --batch --with-colons --show-keys "$keyring" 2>/dev/null | awk -F: '$1=="fpr" { print $10; exit }')
{ pacman-key --add "$keyring" && pacman-key --lsign-key "$fpr"; } >>"$log" 2>&1
"$here/scripts/view.sh" "$tree" /srv/view
channel=stable
[[ -f /srv/view/stable/x86_64/grassfield.db ]] || channel=beta
printf 'SigLevel = Required\nServer = file:///srv/view/%s/$arch\n' "$channel" >/etc/pacman.d/grassfield.conf
printf '\n[grassfield]\nInclude = /etc/pacman.d/grassfield.conf\n' >>/etc/pacman.conf
# The three packages only: grassfield-keyring comes as grassfield-desktop's dependency (grassfield ADR-0033 O22).
pacman -Sy --noconfirm grassfield-desktop grassfield-compositor grassfield-icons >>"$log" 2>&1
reason=$(pacman -Qi grassfield-keyring 2>/dev/null | sed -n 's/^Install Reason *: //p')
expect "pacman -S grassfield-desktop, -compositor and -icons from the $channel channel (signatures required); grassfield-keyring: ${reason:-not installed}" \
  bash -c "pacman -Q grassfield-desktop grassfield-compositor grassfield-icons >/dev/null && [[ '$reason' == 'Installed as a dependency for another package' ]]"
pacman -Q grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring 2>/dev/null | sed 's/^/   /'
# The bundled apps (grassfield ADR-0055): grassfield-desktop depends on `sanaga`, which grassfield-sanaga provides (the channel
# holds only grassfield-* names, ADR-0033 b.6), and on grassfield-notes. A ref from before that ADR has no such depends: the
# apps are then installed here by name, so this test installs them from the channel either way.
desktop_deps=$(pacman -Qi grassfield-desktop 2>/dev/null | sed -n 's/^Depends On *: //p')
if [[ " $desktop_deps " == *" sanaga "* && " $desktop_deps " == *" grassfield-notes "* ]]; then
  expect "grassfield-desktop's depends brought grassfield-sanaga (as sanaga's provider) and grassfield-notes, as dependencies" \
    bash -c "pacman -Qi grassfield-sanaga grassfield-notes | sed -n 's/^Install Reason *: //p' | grep -cx 'Installed as a dependency for another package' | grep -qx 2"
else
  echo "NOTE: this grassfield-desktop does not depend on sanaga and grassfield-notes (a ref from before ADR-0055): installing them by name"
  pacman -Sy --noconfirm grassfield-sanaga grassfield-notes >>"$log" 2>&1
fi
expect "the apps' contract: /usr/bin/sanaga, /usr/bin/grassfield-notes, their .desktop files and hicolor icons, sanaga provided by grassfield-sanaga" \
  bash -c 'test -x /usr/bin/sanaga && test -x /usr/bin/grassfield-notes && test -f /usr/share/applications/sanaga.desktop &&
    test -f /usr/share/applications/grassfield-notes.desktop && test -f /usr/share/icons/hicolor/256x256/apps/sanaga.png &&
    test -f /usr/share/icons/hicolor/256x256/apps/grassfield-notes.png && pacman -Qqo /usr/bin/sanaga | grep -qx grassfield-sanaga &&
    pacman -Qi grassfield-sanaga | grep -q "^Provides *: sanaga$"'
expect "pacman -Q: grassfield-sanaga and grassfield-notes from the channel ($(pacman -Q grassfield-sanaga grassfield-notes 2>/dev/null | tr '\n' ' '))" \
  bash -c "$(declare -f only_provided_by); pacman -Q grassfield-sanaga grassfield-notes >/dev/null && only_provided_by sanaga grassfield-sanaga"
expect "quickshell installed from [omarchy] (trusted by its pinned fingerprint): $(pacman -Q quickshell 2>/dev/null)" \
  bash -c 'pacman -Sl omarchy 2>/dev/null | awk '"'"'$2 == "quickshell" { print $3 }'"'"' | grep -qx -- "$(pacman -Q quickshell | cut -d" " -f2)"'
useradd -m smoke
state=$(runuser -u smoke -- env HOME=/home/smoke /usr/lib/grassfield/grassfield-update-check |
  python3 -I -c 'import json, sys; d = json.load(sys.stdin); print(d["state"], d["channel"])')
expect "grassfield-update-check as a user: up-to-date ($state)" test "${state%% *}" == up-to-date
expect "grassfield-channel-set reads the channel (custom: the Server is this test's, not the build's base)" \
  test "$(runuser -u smoke -- env HOME=/home/smoke grassfield-channel-set)" == custom
if [[ -z $(sed -n 's/^GRASSFIELD_SIGNING_FINGERPRINT=//p' /usr/share/grassfield/pacman/repository.conf) ]]; then
  out=$(runuser -u smoke -- env HOME=/home/smoke grassfield-channel-set stable 2>&1)
  expect "a build that pins no key yet (O11): grassfield-channel-set stable refuses ('$out')" grep -q "no signing key in this build" <<<"$out"
fi
pacman -Rns --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-sanaga grassfield-notes grassfield-keyring >>"$log" 2>&1
expect "pacman -Rns: no [grassfield] line, no /etc/pacman.d/grassfield.conf, pacman works" \
  test "$(grep -c '^\[grassfield\]' /etc/pacman.conf):$(ls /etc/pacman.d/grassfield.conf 2>/dev/null | wc -l):$(pacman -Qq pacman)" == "0:0:pacman"
echo "smoke: $checks checks, $fails failure(s)"
((fails == 0))
