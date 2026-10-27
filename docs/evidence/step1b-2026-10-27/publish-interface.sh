#!/usr/bin/env bash
# The CI path's publication: the release builds of two tags, each built in a fresh tree as build.yml's build job builds it,
# signed by sign-release.sh as its release job signs them (--published), published by the one publisher
# (tools/publish.py), then a client installs and updates from that store. Runs inside a throwaway archlinux:base
# container; every key is made here and gone with it.
#   /packages  this repository (ro)    /ci  the two CI-path builds (ro)
set -u
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "refused: container only"; exit 2; }
P=/packages
fails=0
expect() { local d=$1; shift; if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
say() { printf '\n== %s\n' "$*"; }
install -m644 "$P/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm --needed python sudo diffutils; } >/tmp/setup.log 2>&1 ||
  { tail -n 20 /tmp/setup.log; exit 1; }

say "the project's key (a throwaway one, made here)"
export GNUPGHOME=/root/kp && mkdir -p -m 700 $GNUPGHOME
gpg --batch --pinentry-mode loopback --passphrase '' --quick-gen-key "project (throwaway) <kp@grassfield.invalid>" ed25519 sign 1d 2>/dev/null
KP=$(gpg --with-colons --list-keys 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')
gpg --export "$KP" >/root/kp.gpg && gpg --armor --export "$KP" >/root/kp.asc
echo "KP $KP"

store=/store kept=/kept/releases/beta
mkdir -p "$store" "$kept"
publish() { # rc: sign its tested release build, keep it, run the channel's publisher
  local rc=$1 rel v out
  rel=$(ls -d /ci/"$rc"/tree/releases/beta/*/) && rel=${rel%/} && v=${rel##*/}
  cp -r "$rel" "$kept/$v"
  "$P/scripts/sign-release.sh" --release "$kept/$v" --gnupghome "$GNUPGHOME" --key "$KP" --published "$store/beta/x86_64" \
    >"/tmp/sign-$rc.log" 2>&1
  local src=$?
  expect "$rc: sign-release.sh -> exit 0 ($(grep -c ': signed$' "/tmp/sign-$rc.log") signed, $(grep -c 'published file' "/tmp/sign-$rc.log") published file used as it is)" \
    test "$src" == 0 || cat "/tmp/sign-$rc.log"
  out=$(python3 -I "$P/tools/publish.py" --store "$store" --channel beta --releases "$kept" 2>&1); rc_=$?
  expect "$rc: tools/publish.py -> exit 0 ($out)" test "$rc_" == 0
}
view() { # the store as publish.py left it, read by this PR's tools as they are (one pointer format), the edge rule's files
  expect "the published channel follows the contract (check-tree.sh with KP: manifest, signatures, the database's SHA-256)" \
    "$P/scripts/check-tree.sh" --tree "$store" --keyring /root/kp.gpg
  "$P/scripts/view.sh" "$store" /srv/view
}
check() { runuser -u alice -- env HOME=/home/alice /usr/lib/grassfield/grassfield-update-check |
  python3 -I -c 'import json, sys; d = json.load(sys.stdin); print(d["state"], d["grassfield"]["installed"], d["grassfield"]["available"], d["grassfield"]["notesError"])'; }

say "v1.0.0-rc1: signed, published by the Store's publisher, installed"
publish rc1
mkdir -p /m4/releases/beta && cp -r "$kept"/* /m4/releases/beta/
"$P/scripts/check-tree.sh" --tree /m4 --trusted >/tmp/m4.log 2>&1; rc=$?
expect "check-tree.sh --trusted refuses it: this build's grassfield-keyring holds no key yet (O11), so KP is trusted by none ($(grep -m1 FAIL /tmp/m4.log))" test "$rc" == 1
view
{ pacman-key --add /root/kp.asc && pacman-key --lsign-key "$KP"; } >/tmp/client.log 2>&1
printf 'SigLevel = Required\nServer = file:///srv/view/beta/$arch\n' >/etc/pacman.d/grassfield.conf
printf '\n[grassfield]\nInclude = /etc/pacman.d/grassfield.conf\n' >>/etc/pacman.conf
pacman -Sy --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >>/tmp/client.log 2>&1
expect "pacman -S from the published channel: $(pacman -Q grassfield-desktop grassfield-keyring 2>/dev/null | tr '\n' ' ')" \
  test "$(pacman -Q grassfield-desktop 2>/dev/null | awk '{print $2}')" == 1.0.0rc1-3
useradd -m alice
expect "the checker: up-to-date ($(check))" test "$(check | awk '{print $1}')" == up-to-date
k1=$(sha256sum "$store"/beta/x86_64/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')

say "v1.0.0-rc2: built in a fresh tree (its own grassfield-keyring), signed with the published keyring, published, installed"
built=$(sha256sum /ci/rc2/tree/releases/beta/*/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')
expect "rc2's build made its own grassfield-keyring 20261027-1, other bytes than the published one ($built, $k1)" test "$built" != "$k1"
# Counter-case: signed without the published files, the release build names a keyring of other bytes.
rel2=$(ls -d /ci/rc2/tree/releases/beta/*/) && rel2=${rel2%/}
mkdir -p /counter/releases && cp -r "$store" /counter/store && cp -r "$rel2" "/counter/releases/${rel2##*/}"
"$P/scripts/sign-release.sh" --release "/counter/releases/${rel2##*/}" --gnupghome "$GNUPGHOME" --key "$KP" >/dev/null 2>&1
out=$(python3 -I "$P/tools/publish.py" --store /counter/store --channel beta --releases /counter/releases 2>&1); rc_=$?
expect "counter-case, signed without --published: tools/publish.py refuses it, exit 1 ($out)" test "$rc_" == 1
publish rc2
expect "the published grassfield-keyring kept its bytes (an immutable name)" \
  test "$(sha256sum "$store"/beta/x86_64/grassfield-keyring-*.pkg.tar.zst | awk '{print $1}')" == "$k1"
view
expect "the checker: 1.0.0rc1-3 -> 1.0.0rc2-3 ($(check); notes unverifiable: this build's keyring holds no key, O11)" \
  test "$(check | cut -d' ' -f1-3)" == "available 1.0.0rc1-3 1.0.0rc2-3"
pacman -Syu --noconfirm >>/tmp/client.log 2>&1
expect "pacman -Syu installs 1.0.0rc2-3, all three together" \
  test "$(pacman -Q grassfield-desktop grassfield-compositor grassfield-icons | awk '{print $2}' | sort -u)" == 1.0.0rc2-3
out=$(python3 -I "$P/tools/publish.py" --store "$store" --channel beta --releases "$kept" 2>&1)
expect "the publisher again, nothing new: nothing written ($out)" grep -q 'nothing new' <<<"$out"
python3 -I -c 'import json, sys; m = json.load(open(sys.argv[1])); print("   manifest:", m["release"], m["previous"], len(m["files"]), "files,", m["packages"])' \
  "$store/beta/x86_64/snap/$(python3 -I "$P/scripts/snapshot.py" current "$store/beta/x86_64")/manifest.json"
echo "done: $fails failure(s)"
((fails == 0))
