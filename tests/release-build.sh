#!/usr/bin/env bash
# The release build's pieces with small fake packages (grassfield ADR-0033 b.7, g; ADR-0037 g): notes.py's earlier
# releases from the tags, sign-release.sh, tools/publish.py on a signed release build (its own tests are
# tests/test_publish.py) and check-tree.sh (--keyring, and --trusted as a client checks it). The real packages are
# build-channel.sh's, tested by e2e.sh. Runs itself in a throwaway archlinux:base container (git, vercmp, repo-add,
# throwaway keys made there and gone with it). Exit 0 all PASS (or SKIP without docker, outside CI), 1 a FAIL.
set -u
IMAGE=archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0
if [[ ${1:-} != --inside ]]; then
  here=$(cd "$(dirname "$0")/.." && pwd)
  if ! { command -v docker >/dev/null && docker info >/dev/null 2>&1; }; then
    [[ -z ${CI:-} ]] || { echo "FAIL: no docker daemon in CI: the test did not run"; exit 1; }
    echo "SKIP: no docker daemon"; exit 0
  fi
  args=(--rm --network host -v "$here:/p:ro")
  [[ -n ${GRASSFIELD_TEST_CA:-} ]] && args+=(-v "$(realpath "$GRASSFIELD_TEST_CA"):/etc/ssl/certs/ca-certificates.crt:ro")
  for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy NO_PROXY no_proxy; do [[ -n ${!v:-} ]] && args+=(-e "$v"); done
  exec docker run "${args[@]}" "$IMAGE" bash /p/tests/release-build.sh --inside
fi
[[ -f /.dockerenv && $EUID == 0 ]] || { echo "refused: runs only inside a throwaway container"; exit 2; }
fails=0
expect() { local d=$1; shift; if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); fi; }
install -m644 /p/build/pacman.conf /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm --needed git python diffutils; } >/tmp/setup.log 2>&1 ||
  { tail -n 20 /tmp/setup.log; exit 1; }

echo "== notes.py: the channel's earlier releases from the tags"
g=/w/gf
mkdir -p "$g/packaging/arch" "$g/packaging/release-notes" && cd "$g" && git init -q && git config user.name t && git config user.email t@grassfield.invalid
printf 'pkgver=x\npkgrel=${GRASSFIELD_PKGREL:-3}\n' >packaging/arch/PKGBUILD
rel() { # VERSION [no-notes]
  if [[ -z ${2:-} ]]; then
    printf '%s: what changed.\n' "$1" >"packaging/release-notes/$1.en.txt"
    printf '%s : ce qui a changé.\n' "$1" >"packaging/release-notes/$1.fr.txt"
  fi
  echo "$1" >VERSION && git add -A && git commit -qm "$1" && git tag "v$1"
}
rel 1.0.0 && rel 1.0.1-rc1 && rel 1.0.1 && rel 1.0.2 no-notes && rel 1.1.0-beta1 && git tag not-a-release
notes() { # channel version args... -> the versions it lists
  python3 -I /p/scripts/notes.py --channel "$1" --version "$2" --date 2026-10-27 "${@:3}" --history "$g" |
    python3 -I -c 'import json, sys; d = json.load(sys.stdin); print(" ".join(r["version"] for r in d["releases"]), d["releases"][-1]["date"], d["releases"][-1]["notes"].get("fr", ""))'
}
out=$(notes stable 1.0.1-3 --en packaging/release-notes/1.0.1.en.txt)
expect "stable 1.0.1-3: itself and 1.0.0, not the rc, the beta or later tags ($out)" test "${out%% 20*}" == "1.0.1-3 1.0.0-3"
expect "... an earlier release keeps its date and its French text" grep -Eq ' 20[0-9]{2}-[0-9]{2}-[0-9]{2} 1\.0\.0 : ce qui a changé\.$' <<<"$out"
out=$(notes beta 1.1.0beta1-3 --en packaging/release-notes/1.1.0-beta1.en.txt)
expect "beta 1.1.0beta1-3: every earlier release, newest first, 1.0.2 without notes left out ($out)" \
  test "${out%% 20*}" == "1.1.0beta1-3 1.0.1-3 1.0.1rc1-3 1.0.0-3"
out=$(notes stable 1.0.1-4 --rebuilt-for 0.56.3)
expect "a pkgrel rebuild 1.0.1-4: its 'Rebuilt for' note, then 1.0.1-3's own ($out)" test "${out%% 20*}" == "1.0.1-4 1.0.1-3 1.0.0-3"
printf 'pkgver=x\n' >packaging/arch/PKGBUILD && printf '1.2.0\n' >packaging/release-notes/1.2.0.en.txt
git add -A && git commit -qm 'no pkgrel' && git tag v1.2.0
python3 -I /p/scripts/notes.py --channel stable --version 1.3.0-1 --date 2026-10-27 --en packaging/release-notes/1.0.0.en.txt \
  --history "$g" >/dev/null 2>/tmp/err; rc=$?
expect "a tag whose pkgrel cannot be read is an error, not a silent gap" test "$rc:$(cat /tmp/err)" == "1:notes.py: cannot read the pkgrel of v1.2.0's packaging/arch/PKGBUILD" ||
  cat /tmp/err

echo "== sign-release.sh and check-tree.sh on a release build"
mkkey() {
  mkdir -p -m 700 "/root/keys/$1"
  gpg --homedir "/root/keys/$1" --batch --pinentry-mode loopback --passphrase '' --quick-gen-key "t $1 <$1@grassfield.invalid>" ed25519 sign 1d 2>/dev/null
  gpg --homedir "/root/keys/$1" --with-colons --list-keys 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}'
}
K1=$(mkkey k1) K2=$(mkkey k2)
gpg --homedir /root/keys/k2 --export "$K2" >/w/k2.gpg
sig() { gpg --homedir "/root/keys/$1" --batch --detach-sign --no-armor --yes -o "$2.sig" "$2" 2>/dev/null; }
mkpkg() { # dir name version [keyring folder: a grassfield-keyring with those files]
  local d; d=$(mktemp -d)
  mkdir -p "$d/usr/share/$2" && echo "$2 $3" >"$d/usr/share/$2/v"
  [[ -z ${4:-} ]] || { mkdir -p "$d/usr/share/grassfield" && cp -r "$4" "$d/usr/share/grassfield/pacman-keyring"; }
  printf 'pkgname = %s\npkgbase = %s\npkgver = %s\npkgdesc = test\nbuilddate = %s\npackager = test\nsize = 4\narch = any\nlicense = MIT\n' \
    "$2" "$2" "$3" "$RANDOM" >"$d/.PKGINFO"
  (cd "$d" && bsdtar --zstd -cf "$1/$2-$3-any.pkg.tar.zst" .PKGINFO usr)
}
r=/w/tree/releases/stable/1.0.1-3 pub=/w/published
mkdir -p "$r" "$pub"
mkdir -p /w/kr-k2 && gpg --homedir /root/keys/k2 --export "$K2" >/w/kr-k2/grassfield.gpg && echo "$K2:4:" >/w/kr-k2/grassfield-trusted && : >/w/kr-k2/grassfield-revoked
mkpkg "$r" grassfield-desktop 1.0.1-3 && mkpkg "$r" grassfield-keyring 20261027-1 /w/kr-k2 && mkpkg "$pub" grassfield-keyring 20261027-1 /w/kr-k2
for f in "$r"/*.pkg.tar.zst; do sig k1 "$f"; done
sig k2 "$pub/grassfield-keyring-20261027-1-any.pkg.tar.zst"
mkdir -p /tmp/db && (cd "$r" && repo-add -q /tmp/db/grassfield.db.tar.gz ./*.pkg.tar.zst >/dev/null)
cp -L /tmp/db/grassfield.db.tar.gz "$r/grassfield.db" && cp -L /tmp/db/grassfield.files.tar.gz "$r/grassfield.files"
python3 -I /p/scripts/notes.py --channel stable --version 1.0.1-3 --date 2026-10-27 --en "$g/packaging/release-notes/1.0.1.en.txt" >"$r/grassfield-notes.json"
for f in grassfield.db grassfield.files grassfield-notes.json; do sig k1 "$r/$f"; done
cp -r /w/tree /w/tree.k1
/p/scripts/sign-release.sh --release "$r" --gnupghome /root/keys/k2 --key "$K2" --published "$pub" >/tmp/sign.log 2>&1; rc=$?
expect "sign-release.sh with K2 -> exit 0" test "$rc" == 0 || cat /tmp/sign.log
expect "... grassfield-keyring is the published file, with its signature" \
  cmp -s "$r/grassfield-keyring-20261027-1-any.pkg.tar.zst" "$pub/grassfield-keyring-20261027-1-any.pkg.tar.zst"
expect "... the release build passes check-tree.sh with K2 alone (every signature, the database's SHA-256)" \
  /p/scripts/check-tree.sh --tree /w/tree --keyring /w/k2.gpg
expect "... and check-tree.sh --trusted: K2 is in the trusted list of the grassfield-keyring the release ships" \
  /p/scripts/check-tree.sh --tree /w/tree --trusted

echo "== tools/publish.py publishes the signed release build"
store=/w/store
out=$(python3 -I /p/tools/publish.py --store "$store" --channel stable --releases /w/tree/releases/stable 2>&1); rc=$?
expect "tools/publish.py --releases -> exit 0 ($out)" test "$rc" == 0
id=$(python3 -I /p/scripts/snapshot.py current "$store/stable/x86_64")
expect "its pointer {\"snapshot\": \"$id\"} and manifest (release 1.0.1-3, 6 files)" \
  test "$(python3 -I -c 'import json, sys; m = json.load(open(sys.argv[1])); print(m["release"], len(m["files"]))' "$store/stable/x86_64/snap/$id/manifest.json")" == "1.0.1-3 6"
expect "check-tree.sh --trusted on the published channel (manifest, signatures, SHA-256)" /p/scripts/check-tree.sh --tree "$store" --trusted
echo tampered >>"$store/stable/x86_64/snap/$id/grassfield-notes.json"
/p/scripts/check-tree.sh --tree "$store" --trusted >/tmp/check.log 2>&1; rc=$?
expect "a snapshot file that is not the one its manifest records -> exit 1 ($(grep -m1 FAIL /tmp/check.log))" test "$rc" == 1

echo "== check-tree.sh --trusted refuses a key its grassfield-keyring does not trust"
trusted_case() { # trusted-list revoked-list -> check-tree --trusted's exit code on a release build signed by K2
  local t=/w/t-$RANDOM k=/w/kr-$RANDOM
  mkdir -p "$t/releases/beta/1.0.1-3" "$k"
  gpg --homedir /root/keys/k2 --export "$K2" >"$k/grassfield.gpg" && gpg --homedir /root/keys/k1 --export "$K1" >>"$k/grassfield.gpg"
  printf '%s' "$1" >"$k/grassfield-trusted" && printf '%s' "$2" >"$k/grassfield-revoked"
  mkpkg "$t/releases/beta/1.0.1-3" grassfield-desktop 1.0.1-3 && mkpkg "$t/releases/beta/1.0.1-3" grassfield-keyring 20261027-1 "$k"
  (cd "$t/releases/beta/1.0.1-3" && for f in ./*.pkg.tar.zst; do sig k2 "$f"; done && rm -f /tmp/db/* &&
    repo-add -q /tmp/db/grassfield.db.tar.gz ./*.pkg.tar.zst >/dev/null && cp -L /tmp/db/grassfield.db.tar.gz grassfield.db &&
    cp -L /tmp/db/grassfield.files.tar.gz grassfield.files &&
    python3 -I /p/scripts/notes.py --channel beta --version 1.0.1-3 --date 2026-10-27 --en "$g/packaging/release-notes/1.0.1.en.txt" >grassfield-notes.json &&
    for f in grassfield.db grassfield.files grassfield-notes.json; do sig k2 "$f"; done)
  /p/scripts/check-tree.sh --tree "$t" --trusted >/tmp/check.log 2>&1
}
trusted_case "$K1:4:"$'\n' ""; rc=$?
expect "signed by K2, its keyring trusts K1 only -> exit 1 ($(grep -m1 FAIL /tmp/check.log))" test "$rc" == 1
trusted_case "$K2:4:"$'\n' "$K2"$'\n'; rc=$?
expect "signed by K2, trusted but also revoked -> exit 1" test "$rc" == 1
trusted_case "$K2:4:"$'\n' ""; rc=$?
expect "signed by K2, trusted -> exit 0" test "$rc" == 0
mkdir -p /w/pub.k1 && cp "$r"/grassfield-keyring-*.pkg.tar.zst /w/pub.k1/ && sig k1 /w/pub.k1/grassfield-keyring-20261027-1-any.pkg.tar.zst
/p/scripts/sign-release.sh --release /w/tree.k1/releases/stable/1.0.1-3 --gnupghome /root/keys/k2 --key "$K2" --published /w/pub.k1 >/tmp/sign.log 2>&1; rc=$?
expect "a published package not signed by the key -> exit 1 ($(tail -n 1 /tmp/sign.log))" test "$rc" == 1
mkpkg /tmp grassfield-desktop 1.0.1-3 && cp /tmp/grassfield-desktop-1.0.1-3-any.pkg.tar.zst "$r/" && sig k2 "$r/grassfield-desktop-1.0.1-3-any.pkg.tar.zst"
/p/scripts/check-tree.sh --tree /w/tree --keyring /w/k2.gpg >/tmp/check.log 2>&1; rc=$?
expect "a package whose bytes are not the ones its database records -> check-tree.sh exit 1 ($(grep -m1 FAIL /tmp/check.log))" test "$rc" == 1

echo "done: $fails failure(s)"
((fails == 0))
