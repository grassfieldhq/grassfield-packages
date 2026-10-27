#!/usr/bin/env bash
# The CI path end to end, with keyring/ as it will be after O11 (holding the project's key): two tags, each built in a
# fresh tree with build.yml's build-step commands (a throwaway build key), then build.yml's release job for each (prepare
# without the key, sign with the project's key by gpg only, check as a client would, keyring/ byte for byte), published
# by the one publisher (tools/publish.py), and a client that installs the first and updates to the second. One throwaway
# container: the project key KP and the build keys are made in it and gone with it.
#   /packages  this repository (ro)    /grassfield  a grassfield clone with the tags v1.0.0-rc1, v1.0.0-rc2 (ro)
#   /out       the builds' trees, for the test job (smoke.sh) run afterwards in its own containers
set -u
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "refused: container only"; exit 2; }
fails=0 checks=0
expect() { local d=$1; shift; checks=$((checks + 1)); if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
say() { printf '\n== %s\n' "$*"; }
install -m644 /packages/build/pacman.conf /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm --needed python sudo diffutils; } >/tmp/setup.log 2>&1 ||
  { tail -n 20 /tmp/setup.log; exit 1; }

say "keyring/ as after O11: the project's key KP (a throwaway one, made here)"
mkdir -p -m 700 /root/kp
gpg --homedir /root/kp --batch --pinentry-mode loopback --passphrase '' --quick-gen-key "project (throwaway) <kp@grassfield.invalid>" ed25519 sign 1d 2>/dev/null
KP=$(gpg --homedir /root/kp --with-colons --list-keys 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')
cp -r /packages /pk
gpg --homedir /root/kp --export "$KP" >/pk/keyring/grassfield.gpg && echo "$KP:4:" >/pk/keyring/grassfield-trusted
sums=$(cd /pk/keyring && sha256sum grassfield.gpg grassfield-trusted grassfield-revoked | awk '{printf "\x27%s\x27 ", $1}')
sed -i "/^sha256sums=/,/)$/c\\sha256sums=(${sums% })" /pk/keyring/PKGBUILD
echo "KP $KP"

for rc in rc1 rc2; do
  say "build.yml's build step for v1.0.0-$rc, in a fresh tree (a throwaway build key)"
  start=$(date +%s)
  mkdir -p "/out/$rc"
  (
    export GNUPGHOME=$(mktemp -d)
    gpg --batch --pinentry-mode loopback --passphrase "" \
      --quick-gen-key "Grassfield CI build (throwaway) <ci@grassfield.invalid>" ed25519 sign 14d 2>/dev/null
    key=$(gpg --with-colons --list-keys | awk -F: "\$1==\"fpr\" {print \$10; exit}")
    /pk/scripts/build-channel.sh --source /grassfield --ref "v1.0.0-$rc" --tree "/out/$rc/tree" \
      --gnupghome "$GNUPGHOME" --key "$key" >"/out/$rc/build.txt" 2>&1 &&
      gpg --export "$key" >"/out/$rc/build-signing-key.gpg" &&
      /pk/scripts/check-tree.sh --tree "/out/$rc/tree" --keyring "/out/$rc/build-signing-key.gpg" >"/out/$rc/check.txt" 2>&1
  ); rc_=$?
  expect "$rc: built and checked -> exit 0 ($(( $(date +%s) - start )) s; $(tail -n 1 "/out/$rc/check.txt"))" test "$rc_" == 0 ||
    tail -n 20 "/out/$rc/build.txt"
done
k1=$(sha256sum /out/rc1/tree/releases/beta/*/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')
k2=$(sha256sum /out/rc2/tree/releases/beta/*/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')
expect "each fresh tree built its own grassfield-keyring 20261027-1: other bytes ($k1, $k2)" test "$k1" != "$k2"

store=/store kept=/kept
mkdir -p "$store" "$kept"
release_job() { # rc [--no-published]: build.yml's release job, then the publisher
  local rc=$1 rel v out r
  rel=$(ls -d /out/"$rc"/tree/releases/beta/*/) && rel=${rel%/} && v=${rel##*/}
  r=$kept/$rc/releases/beta/$v && mkdir -p "$(dirname "$r")" && cp -r "$rel" "$r"
  local pub=(--published "$store/beta/x86_64")
  [[ ${2:-} == --no-published ]] && pub=()
  out=$(/pk/scripts/sign-release.sh prepare --release "$r" --keyring /pk/keyring "${pub[@]}" 2>&1); r_=$?
  expect "$rc: prepare, without the key -> exit 0 ($(grep -c 'published file' <<<"$out") published file used as it is)" test "$r_" == 0 || echo "$out"
  out=$(GRASSFIELD_SIGNING_KEY=never-read /pk/scripts/sign-release.sh sign --release "$r" --gnupghome /root/kp --key "$KP" 2>&1); r_=$?
  expect "$rc: sign with KP, gpg only -> exit 0 ($(grep -c ': signed$' <<<"$out") files signed)" test "$r_" == 0 || echo "$out"
  /pk/scripts/check-tree.sh --tree "$kept/$rc" --trusted --keyring-src /pk/keyring >"/tmp/check-$rc.txt" 2>&1; r_=$?
  expect "$rc: checked as a client checks it, keyring/ byte for byte, nothing else in the folder -> exit 0" test "$r_" == 0 ||
    grep FAIL "/tmp/check-$rc.txt"
}
publish() { # rc: tools/publish.py on the release builds kept so far
  local out r_
  mkdir -p /kept/all
  cp -r "$kept/$1"/releases/beta/* /kept/all/
  out=$(python3 -I /pk/tools/publish.py --store "$store" --channel beta --releases /kept/all --keyring-dir /pk/keyring 2>&1); r_=$?
  expect "$1: tools/publish.py -> exit 0 ($out)" test "$r_" == 0
  expect "$1: the published channel follows the contract (check-tree.sh --trusted --keyring-src)" \
    /pk/scripts/check-tree.sh --tree "$store" --trusted --keyring-src /pk/keyring
  /pk/scripts/view.sh "$store" /srv/view
}
check() { runuser -u alice -- env HOME=/home/alice /usr/lib/grassfield/grassfield-update-check |
  python3 -I -c 'import json, sys; d = json.load(sys.stdin); g = d["grassfield"]; print(d["state"], g["installed"], g["available"], g["notesError"], len(g["notes"]))'; }

say "v1.0.0-rc1: build.yml's release job, published, installed"
release_job rc1
publish rc1
gpg --homedir /root/kp --armor --export "$KP" >/tmp/kp.asc
{ pacman-key --add /tmp/kp.asc && pacman-key --lsign-key "$KP"; } >/tmp/client.log 2>&1
printf 'SigLevel = Required\nServer = file:///srv/view/beta/$arch\n' >/etc/pacman.d/grassfield.conf
printf '\n[grassfield]\nInclude = /etc/pacman.d/grassfield.conf\n' >>/etc/pacman.conf
pacman -Sy --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >>/tmp/client.log 2>&1
expect "pacman -S from the published channel: $(pacman -Q grassfield-desktop grassfield-keyring 2>/dev/null | tr '\n' ' ')" \
  test "$(pacman -Q grassfield-desktop 2>/dev/null | awk '{print $2}')" == 1.0.0rc1-3
useradd -m alice
expect "the checker: up-to-date ($(check))" test "$(check | awk '{print $1}')" == up-to-date

say "v1.0.0-rc2: counter-case first (signed without the published keyring), then build.yml's release job"
mkdir -p /counter && cp -r "$store" /counter/store
release_job rc2 --no-published
mkdir -p /counter/releases && cp -r "$kept/rc2"/releases/beta/* /counter/releases/
out=$(python3 -I /pk/tools/publish.py --store /counter/store --channel beta --releases /counter/releases --keyring-dir /pk/keyring 2>&1); r_=$?
expect "counter-case: tools/publish.py refuses it, exit 1 ($out)" test "$r_" == 1
rm -rf "$kept/rc2"
release_job rc2
publish rc2
expect "the published grassfield-keyring kept its bytes" \
  test "$(sha256sum "$store"/beta/x86_64/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')" == "$k1"
# This build's base is https (main's repository.conf): the client fetches notes over https only, so the file:// view's
# notes are not fetched; tests/e2e.sh verifies them with releases whose base is file://.
expect "the checker: 1.0.0rc1-3 -> 1.0.0rc2-3 offered; notes over https only, so none from this file:// view ($(check))" \
  test "$(check | cut -d' ' -f1-5)" == "available 1.0.0rc1-3 1.0.0rc2-3 unavailable 0"
pacman -Syu --noconfirm >>/tmp/client.log 2>&1; r_=$?
expect "pacman -Syu -> exit 0, installs 1.0.0rc2-3, all three together" \
  test "$r_:$(pacman -Q grassfield-desktop grassfield-compositor grassfield-icons | awk '{print $2}' | sort -u)" == "0:1.0.0rc2-3"
out=$(python3 -I /pk/tools/publish.py --store "$store" --channel beta --releases /kept/all --keyring-dir /pk/keyring 2>&1)
expect "the publisher again, nothing new: nothing written ($out)" grep -q 'nothing new' <<<"$out"
echo "done: $checks checks, $fails failure(s)"
((fails == 0))
