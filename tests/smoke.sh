#!/usr/bin/env bash
# Smoke test of a built channel tree, the CI test job (grassfield ADR-0033 g): a fresh Omarchy stable machine installs the
# built packages from it and Grassfield's Software Update client answers.
#
#   smoke.sh --tree DIR --keyring FILE
#
#   --keyring FILE  the public key that signed the tree (the build's throwaway key); trusted here, in this container only
# Runs only as root inside a throwaway Arch container. Checks: the tree against the contract (check-tree.sh); the
# [grassfield] section written by hand (the first installation of ADR-0033 b.3a) and `pacman -S` of grassfield-desktop,
# grassfield-compositor and grassfield-icons with every signature required; grassfield-update-check, as a user, answers
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
fails=0
expect() { local d=$1; shift; if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
log=/tmp/smoke.log

install -m644 "$here/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm --needed python sudo; } >>"$log" 2>&1 ||
  { echo "FAIL: the Omarchy stable machine (see $log)"; exit 1; }
expect "the tree follows the contract (check-tree.sh)" "$here/scripts/check-tree.sh" --tree "$tree" --keyring "$keyring"
fpr=$(gpg --homedir "$(mktemp -d)" --batch --with-colons --show-keys "$keyring" 2>/dev/null | awk -F: '$1=="fpr" { print $10; exit }')
{ pacman-key --add "$keyring" && pacman-key --lsign-key "$fpr"; } >>"$log" 2>&1
"$here/scripts/view.sh" "$tree" /srv/view
channel=stable
[[ -f /srv/view/stable/x86_64/grassfield.db ]] || channel=beta
printf 'SigLevel = Required\nServer = file:///srv/view/%s/$arch\n' "$channel" >/etc/pacman.d/grassfield.conf
printf '\n[grassfield]\nInclude = /etc/pacman.d/grassfield.conf\n' >>/etc/pacman.conf
# grassfield-keyring named too: grassfield-desktop does not depend on it yet (grassfield ADR-0033 O21).
pacman -Sy --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >>"$log" 2>&1
expect "pacman -S grassfield-desktop, -compositor, -icons and -keyring from the $channel channel (signatures required)" \
  pacman -Q grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring
pacman -Q grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring 2>/dev/null | sed 's/^/   /'
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
pacman -Rns --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >>"$log" 2>&1
expect "pacman -Rns: no [grassfield] line, no /etc/pacman.d/grassfield.conf, pacman works" \
  test "$(grep -c '^\[grassfield\]' /etc/pacman.conf):$(ls /etc/pacman.d/grassfield.conf 2>/dev/null | wc -l):$(pacman -Qq pacman)" == "0:0:pacman"
echo "smoke: $fails failure(s)"
((fails == 0))
