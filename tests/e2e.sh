#!/usr/bin/env bash
# End-to-end exercise with the REAL Grassfield packages (grassfield ADR-0033; docs/specs/updates.md A10 and A7i).
#
#   tests/e2e.sh --grassfield DIR [--ref REF]
#     DIR   a grassfield checkout with its history (only cloned from); REF (default its HEAD) must carry ADR-0033's client
#   Runs itself in a throwaway container (`docker run --rm --network host` on archlinux:base, digest pinned below) with this
#   repository and DIR mounted read-only; HTTPS_PROXY/HTTP_PROXY/NO_PROXY are passed through and GRASSFIELD_TEST_CA, when
#   set, is mounted as the container's CA bundle. Exit 0 all PASS (or SKIP without docker), 1 a FAIL, 2 usage.
#
# Inside (never elsewhere): throwaway keys K (signs) and KR (rogue), made here and gone with the container; a test
# grassfield-keyring from keyring/ with K in it; a scratch clone of grassfield whose three local commits (never pushed)
# make the releases 1.0.0, 1.0.1 and 1.1.0-beta1, each with its release notes and a repository.conf that pins K on a
# file:// base; scripts/build-channel.sh builds each with grassfield's own PKGBUILD on Omarchy stable's package set, and
# scripts/view.sh serves the tree as the edge rule would. The same container is then the user's machine:
#   - the first installation of ADR-0033 b.3a (K added and locally signed, the section by hand, pacman -S from the
#     repository), then `grassfield-channel-set stable` through real polkitd and pkexec;
#   - 1.0.1 published: the client sees it with its notes, pacman -Syu installs it;
#   - a database signed by the rogue key and packages signed by it are refused; notes signed by it are not shown;
#   - beta: 1.1.0beta1 seen and installed; back to stable: no downgrade;
#   - A7i over HTTP (scripts/serve.py): a pointer moved back fails for a client already on the newer snapshot; a new
#     snapshot with the older packages (scripts/rollback.sh) works and downgrades nothing;
#   - the tree passes check-tree.sh; `pacman -Rns` takes the section and the key away; the real keyless keyring trusts
#     nothing.
set -uo pipefail
IMAGE=archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0

if [[ ${1:-} != --inside ]]; then
  here=$(cd "$(dirname "$0")/.." && pwd)
  gf="" ref=HEAD
  while (($#)); do
    case $1 in
      --grassfield) gf=${2:?} ; shift ;;
      --ref) ref=${2:?} ; shift ;;
      *) echo "usage: e2e.sh --grassfield DIR [--ref REF]" >&2; exit 2 ;;
    esac
    shift
  done
  [[ -d $gf/.git ]] || { echo "usage: e2e.sh --grassfield DIR [--ref REF] (a checkout with its history)" >&2; exit 2; }
  command -v docker >/dev/null && docker info >/dev/null 2>&1 || { echo "SKIP: no docker daemon (this test runs only in a throwaway container)"; exit 0; }
  args=(--rm --network host -e "E2E_REF=$ref" -v "$here:/packages:ro" -v "$(realpath "$gf"):/grassfield:ro")
  [[ -n ${GRASSFIELD_TEST_CA:-} ]] && args+=(-v "$(realpath "$GRASSFIELD_TEST_CA"):/etc/ssl/certs/ca-certificates.crt:ro")
  for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy NO_PROXY no_proxy; do [[ -n ${!v:-} ]] && args+=(-e "$v"); done
  exec docker run "${args[@]}" "$IMAGE" bash /packages/tests/e2e.sh --inside
fi

[[ -f /.dockerenv && $EUID == 0 && -d /packages/scripts && -d /grassfield/.git ]] ||
  { echo "refused: runs only as root inside a throwaway container (/packages, /grassfield)"; exit 2; }
P=/packages W=/work
mkdir -p "$W" && chmod 755 "$W"
fails=0
expect() { local d=$1; shift; if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
say() { printf '\n== %s\n' "$*"; }
as() { local u=$1; shift; runuser -u "$u" -- env HOME="/home/$u" XDG_RUNTIME_DIR="/run/user/$(id -u "$u")" "$@"; }
installed() { pacman -Q grassfield-desktop 2>/dev/null | awk '{print $2}'; }
check() { # fields of the checker's answer, as alice
  as alice /usr/lib/grassfield/grassfield-update-check >"$W/check.json" 2>"$W/check.err"
  python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
def get(p):
    v = d
    for k in p.split("."):
        v = v.get(k) if isinstance(v, dict) else None
    return v
print(" ".join(str(get(p)) for p in sys.argv[2:]))' "$W/check.json" "$@"
}
validity() { gpg --homedir /etc/pacman.d/gnupg --batch --no-tty --with-colons --list-keys "$1" 2>/dev/null | awk -F: '$1=="pub"{print $2; exit}'; }

say "an Omarchy stable machine (build/pacman.conf) with the tools of this test"
install -m644 "$P/build/pacman.conf" /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux &&
  pacman -Syu --noconfirm --needed base-devel git python polkit sudo; } >"$W/setup.log" 2>&1 || { tail -n 20 "$W/setup.log"; exit 1; }
pacman -Q pacman pacman-contrib gnupg polkit git python 2>/dev/null | tr '\n' ' '; echo

say "throwaway keys"
mkkey() {
  mkdir -p -m 700 "/root/keys/$1"
  gpg --homedir "/root/keys/$1" --batch --pinentry-mode loopback --passphrase '' \
    --quick-gen-key "Grassfield e2e $1 (throwaway) <$1@grassfield.invalid>" ed25519 sign 1d 2>/dev/null
  gpg --homedir "/root/keys/$1" --with-colons --list-keys | awk -F: '$1=="fpr"{print $10; exit}'
}
K=$(mkkey k) KR=$(mkkey kr)
gpg --homedir /root/keys/k --export "$K" >"$W/k.gpg"
gpg --homedir /root/keys/k --armor --export "$K" >"$W/k.asc"
gpg --homedir /root/keys/kr --export "$KR" >"$W/kr.gpg"
echo "K $K"; echo "KR $KR"

say "the test keyring (keyring/ of this repository with K) and the scratch releases of grassfield"
cp -a "$P/keyring" "$W/keyring"
cp "$W/k.gpg" "$W/keyring/grassfield.gpg" && echo "$K:4:" >"$W/keyring/grassfield-trusted"
sums=$(cd "$W/keyring" && sha256sum grassfield.gpg grassfield-trusted grassfield-revoked | awk '{printf "\x27%s\x27 ", $1}')
sed -i "/^sha256sums=/,/)$/c\\sha256sums=(${sums% })" "$W/keyring/PKGBUILD"
git clone --quiet /grassfield "$W/gf" 2>/dev/null || git -c safe.directory='*' clone --quiet /grassfield "$W/gf"
git -C "$W/gf" -c advice.detachedHead=false checkout --quiet --detach "$E2E_REF"
git -C "$W/gf" config user.name "e2e (container only)" && git -C "$W/gf" config user.email e2e@grassfield.invalid
release() { # VERSION -> commit
  local v=$1 d=$W/gf
  echo "$v" >"$d/VERSION"
  printf 'GRASSFIELD_REPO_BASE=file:///srv/view\nGRASSFIELD_REPO_MIRRORS=\nGRASSFIELD_REPO_BASE_PREVIOUS=\nGRASSFIELD_SIGNING_FINGERPRINT=%s\n' "$K" \
    >"$d/packaging/pacman/repository.conf"
  cp "$W/k.asc" "$d/packaging/pacman/grassfield-signing-key.asc"
  mkdir -p "$d/packaging/release-notes"
  printf 'Grassfield %s: what changed.\nSecond line.\n' "$v" >"$d/packaging/release-notes/$v.en.txt"
  printf 'Grassfield %s : ce qui a changé.\n' "$v" >"$d/packaging/release-notes/$v.fr.txt"
  git -C "$d" add -A && git -C "$d" commit --quiet -m "e2e release $v (throwaway, container only)"
  git -C "$d" rev-parse HEAD
}
C1=$(release 1.0.0) C2=$(release 1.0.1) C3=$(release 1.1.0-beta1)
# The pkgrel each build gets: the one committed in grassfield's PKGBUILD (no GRASSFIELD_PKGREL here).
REL=$(cd "$W/gf/packaging/arch" && env -u GRASSFIELD_PKGREL bash -c 'source ./PKGBUILD >/dev/null 2>&1; printf %s "$pkgrel"')
echo "releases: 1.0.0 $C1, 1.0.1 $C2, 1.1.0-beta1 $C3 (pkgrel $REL)"
build() { # commit; this container is also the user's machine: its pacman.conf ([grassfield] included) is kept aside
  local rc
  cp /etc/pacman.conf "$W/pacman.conf.client"
  "$P/scripts/build-channel.sh" --source "$W/gf" --ref "$1" --tree "$W/tree" --gnupghome /root/keys/k --key "$K" \
    --keyring "$W/keyring" >"$W/build-$1.log" 2>&1
  rc=$?
  grep -q '^\[grassfield\]' "$W/pacman.conf.client" && cp "$W/pacman.conf.client" /etc/pacman.conf
  return $rc
}
publish_view() { "$P/scripts/view.sh" "$W/tree" /srv/view; }

say "build 1.0.0 (the real PKGBUILD, Omarchy stable's package set)"
start=$(date +%s)
build "$C1"; rc=$?
expect "build-channel.sh 1.0.0 -> exit 0 ($(( $(date +%s) - start )) s)" test "$rc" == 0
((rc == 0)) || { tail -n 40 "$W/build-$C1.log"; exit 1; }
grep -E '^(commit|channels|stable:|beta:|trust anchor|done)' "$W/build-$C1.log" | sed 's/^/   /'
sed -n '/^ref/,/^package-set:/p' "$W"/tree/build-*.txt | sed 's/^/   /'
expect "the tree follows the contract (check-tree.sh)" "$P/scripts/check-tree.sh" --tree "$W/tree" --keyring "$W/k.gpg"
publish_view

say "the user's machine: the first installation (ADR-0033 b.3a), then Set Up through pkexec"
useradd -m alice && useradd -m bob
for u in alice bob; do d=/run/user/$(id -u "$u"); mkdir -p "$d" && chown "$u:" "$d" && chmod 700 "$d"; done
echo 'alice ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/90-alice && chmod 440 /etc/sudoers.d/90-alice
mkdir -p /run/dbus && dbus-daemon --system --fork
/usr/lib/polkit-1/polkitd --no-debug >"$W/polkitd.log" 2>&1 &
cat >/etc/polkit-1/rules.d/50-e2e.rules <<'EOF'
polkit.addRule(function(action, subject) {
  if (action.id == "org.grassfield.packages.set-channel" && subject.user == "alice") return polkit.Result.YES;
});
EOF
pacman -Rdd --noconfirm grassfield-keyring >>"$W/client.log" 2>&1   # the build's copy; the user's comes from the repository
{ pacman-key --add "$W/k.asc" && pacman-key --lsign-key "$K"; } >>"$W/client.log" 2>&1
printf 'SigLevel = Required\nServer = file:///srv/view/stable/$arch\n' >/etc/pacman.d/grassfield.conf
printf '\n[grassfield]\nInclude = /etc/pacman.d/grassfield.conf\n' >>/etc/pacman.conf
# grassfield-keyring named too: grassfield-desktop does not depend on it yet (owner decision O21).
pacman -Sy --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >>"$W/client.log" 2>&1
expect "pacman -S from the repository installs grassfield-desktop 1.0.0-$REL and grassfield-keyring" \
  test "$(installed):$(pacman -Q grassfield-keyring 2>/dev/null | wc -l)" == "1.0.0-$REL:1"
out=$(as alice grassfield-channel-set stable 2>&1); rc=$?
expect "alice: grassfield-channel-set stable -> exit 0 (b.3a step 5: template, keyring populated, hook linked)" test "$rc" == 0 || echo "$out"
expect "the channel is stable; the checker: up-to-date" test "$(as alice grassfield-channel-set) $(check state channel)" == "stable up-to-date stable"

say "A10 1.0.1 published: refused with a rogue signature, seen with its notes, installed"
build "$C2"; rc=$?
expect "build-channel.sh 1.0.1 -> exit 0" test "$rc" == 0 || tail -n 40 "$W/build-$C2.log"
publish_view
cp -a /srv/view "$W/view.good"
v=/srv/view/stable/x86_64
gpg --homedir /root/keys/kr --batch --detach-sign --no-armor --yes -o "$v/grassfield.db.sig" "$v/grassfield.db" 2>/dev/null
rm -f /var/lib/pacman/sync/grassfield.*
pacman -Sy >"$W/bad.log" 2>&1; rc=$?
expect "a database signed by the rogue key -> pacman -Sy exit 1 ($(grep -m1 '^error:' "$W/bad.log"))" test "$rc" == 1
expect "... and the checker answers failed (its [grassfield]-only sync), no crash" test "$(check state)" == failed
rm -rf /srv/view && cp -r "$W/view.good" /srv/view && chmod -R a+rX /srv/view   # republished: new files
for f in "$v"/grassfield-desktop-1.0.1-*.pkg.tar.zst "$v"/grassfield-compositor-1.0.1-*.pkg.tar.zst "$v"/grassfield-icons-1.0.1-*.pkg.tar.zst; do
  gpg --homedir /root/keys/kr --batch --detach-sign --no-armor --yes -o "$f.sig" "$f" 2>/dev/null
done
rm -f "$v/grassfield.db" "$v/grassfield.files"
(cd "$v" && repo-add --quiet grassfield.db.tar.gz ./*.pkg.tar.zst >/dev/null 2>&1 && rm -f grassfield.db grassfield.files &&
  cp -L grassfield.db.tar.gz grassfield.db && cp -L grassfield.files.tar.gz grassfield.files && rm -f grassfield.db.tar.gz* grassfield.files.tar.gz* grassfield.db.tar.gz.old grassfield.files.tar.gz.old)
for f in grassfield.db grassfield.files; do gpg --homedir /root/keys/k --batch --detach-sign --no-armor --yes -o "$v/$f.sig" "$v/$f" 2>/dev/null; done
gpg --homedir /root/keys/kr --batch --detach-sign --no-armor --yes -o "$v/grassfield-notes.json.sig" "$v/grassfield-notes.json" 2>/dev/null
rm -f /var/cache/pacman/pkg/grassfield-*1.0.1*
expect "notes signed by the rogue key: the update is offered without notes" test "$(check state grassfield.available grassfield.notesError)" == "available 1.0.1-$REL unavailable"
pacman -Syu --noconfirm >"$W/bad.log" 2>&1; rc=$?
expect "packages signed by the rogue key (database signed by K) -> pacman -Syu exit 1, still 1.0.0-$REL ($(grep -m1 '^error:' "$W/bad.log"))" \
  test "$rc:$(installed)" == "1:1.0.0-$REL"
rm -rf /srv/view && cp -r "$W/view.good" /srv/view && chmod -R a+rX /srv/view   # republished: new files
rm -f /var/cache/pacman/pkg/grassfield-*1.0.1*
expect "the checker sees Grassfield 1.0.0 -> 1.0.1 with verified notes" \
  test "$(check state grassfield.installed grassfield.available grassfield.notesError)" == "available 1.0.0-$REL 1.0.1-$REL None"
python3 -I -c 'import json; print("   notes:", json.load(open("/work/check.json"))["grassfield"]["notes"])'
pacman -Syu --noconfirm >>"$W/client.log" 2>&1
expect "pacman -Syu installs 1.0.1 (grassfield-desktop, -compositor and -icons together)" \
  test "$(pacman -Q grassfield-desktop grassfield-compositor grassfield-icons | awk '{print $2}' | sort -u)" == 1.0.1-$REL
expect "the checker: up-to-date" test "$(check state)" == up-to-date

say "A10 beta, then back to stable without a downgrade"
build "$C3"; rc=$?
expect "build-channel.sh 1.1.0-beta1 -> exit 0, beta only" test "$rc:$(grep -c '^stable:' "$W/build-$C3.log")" == "0:0" || tail -n 40 "$W/build-$C3.log"
publish_view
expect "on stable the checker still says up-to-date" test "$(check state)" == up-to-date
expect "grassfield-channel-set beta -> exit 0" as alice grassfield-channel-set beta
expect "the checker: 1.1.0beta1 available on beta, with its notes" \
  test "$(check state channel grassfield.available grassfield.notesError)" == "available beta 1.1.0beta1-$REL None"
pacman -Syu --noconfirm >>"$W/client.log" 2>&1
expect "pacman -Syu installs 1.1.0beta1" test "$(installed)" == "1.1.0beta1-$REL"
expect "grassfield-channel-set stable -> exit 0" as alice grassfield-channel-set stable
expect "back on stable: the checker offers nothing" test "$(check state grassfield.available)" == "up-to-date None"
pacman -Syu --noconfirm >"$W/syu.log" 2>&1
expect "pacman -Syu keeps 1.1.0beta1 ('is newer than grassfield')" test "$(installed):$(grep -q 'is newer than grassfield' "$W/syu.log" && echo said)" == "1.1.0beta1-$REL:said"

say "A7i a rollback over HTTP (the edge rule of scripts/serve.py)"
python3 -I "$P/scripts/serve.py" "$W/tree" 8788 2>"$W/serve.log" &
server=$!
sleep 1
printf 'SigLevel = Required\nServer = http://127.0.0.1:8788/stable/$arch\n' >/etc/pacman.d/grassfield.conf
rm -f /var/lib/pacman/sync/grassfield.*
expect "pacman -Sy over the redirects of the current snapshot (1.0.1)" pacman -Sy
mapfile -t snaps < <(ls "$W/tree/stable/x86_64/snap")
older=${snaps[0]} newer=$(cat "$W/tree/stable/x86_64/pointer")
echo "$older" >"$W/tree/stable/x86_64/pointer"
pacman -Sy >"$W/back.log" 2>&1; rc=$?
expect "the pointer moved back to the older snapshot: pacman -Sy fails for this client ($(grep -m1 '^error:' "$W/back.log"))" test "$rc" == 1
echo "$newer" >"$W/tree/stable/x86_64/pointer"
"$P/scripts/rollback.sh" --tree "$W/tree" --channel stable --to "$older" --gnupghome /root/keys/k --key "$K" >"$W/rollback.log" 2>&1
expect "rollback.sh: a new snapshot with the older packages ($(tail -n 1 "$W/rollback.log"))" test "$(cat "$W/tree/stable/x86_64/pointer")" != "$newer"
expect "... pacman -Sy works" pacman -Sy
pacman -Syu --noconfirm >"$W/syu.log" 2>&1
expect "... and pacman -Syu downgrades nothing" test "$(installed)" == "1.1.0beta1-$REL"
grep -E '" 30[24] ' "$W/serve.log" | head -n 4 | sed 's/^/   /'
kill "$server" 2>/dev/null
expect "the tree after the rollback still follows the contract" "$P/scripts/check-tree.sh" --tree "$W/tree" --keyring "$W/k.gpg"

say "removal, and the real keyless keyring"
pacman -Rn --noconfirm grassfield-desktop grassfield-compositor grassfield-icons grassfield-keyring >"$W/rn.log" 2>&1; rc=$?
echo "   pacman -Rn exit $rc; pacman.conf [grassfield] lines $(grep -c grassfield /etc/pacman.conf); K '$(validity "$K")'"
if grep -q grassfield /etc/pacman.conf; then
  sed 's/^/   rn.log: /' "$W/rn.log"
  grep -iE 'scriptlet|grassfield' /var/log/pacman.log | tail -n 15 | sed 's/^/   pacman.log: /'
  tail -n 4 /etc/pacman.conf | sed 's/^/   pacman.conf: /'
  ls -l /run/grassfield /usr/lib/grassfield/grassfield-channel-scriptlet 2>&1 | sed 's/^/   /'
fi
expect "pacman -Rn: exit 0, no [grassfield] line, no file, K no longer in pacman's keyring, pacman works" \
  test "$rc:$(grep -c grassfield /etc/pacman.conf):$(ls /etc/pacman.d/grassfield.conf 2>/dev/null | wc -l):$(validity "$K"):$(pacman -Qq pacman)" == "0:0:0::pacman"
before=$(gpg --homedir /etc/pacman.d/gnupg --batch --with-colons --list-keys 2>/dev/null | grep -c '^pub:')
cp -a "$P/keyring" "$W/real-keyring" && chown -R builder: "$W/real-keyring"
(cd "$W/real-keyring" && runuser -u builder -- makepkg -f --noconfirm >>"$W/client.log" 2>&1)
pacman -U --noconfirm "$W"/real-keyring/grassfield-keyring-*.pkg.tar.zst >>"$W/client.log" 2>&1
after=$(gpg --homedir /etc/pacman.d/gnupg --batch --with-colons --list-keys 2>/dev/null | grep -c '^pub:')
expect "this repository's keyring (no key until O11) installs and trusts nothing ($before keys before and after)" test "$before" == "$after"
expect "... and removes cleanly" pacman -Rn --noconfirm grassfield-keyring

say "done: $fails failure(s)"
((fails == 0))
