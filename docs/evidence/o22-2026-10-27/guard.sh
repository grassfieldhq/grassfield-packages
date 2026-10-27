#!/usr/bin/env bash
# grassfield ADR-0033 O22's release guard with the real packages, in one throwaway container: build-channel.sh refuses a
# grassfield ref whose grassfield-desktop does not depend on grassfield-keyring, builds one that does, and check-tree.sh
# checks that dependency in the tree it wrote.
#   /packages  this repository (ro)    /grassfield  a grassfield clone holding BEFORE and AFTER (ro)
#   /out       the accepted build's tree and key, for smoke.sh afterwards in its own container
#   BEFORE     a grassfield commit from before PR #24 (no grassfield-keyring in grassfield-desktop's depends)
#   AFTER      PR #24's head
# Each ref gets packaging/release-notes/<VERSION>.{en,fr}.txt in one commit on top, in a scratch clone here (never
# pushed): build-channel.sh needs a release's notes before it builds. Each build has its own throwaway key, made here.
set -u
[[ -f /.dockerenv && $EUID == 0 && -n ${BEFORE:-} && -n ${AFTER:-} ]] || { echo "refused: container only, BEFORE and AFTER set"; exit 2; }
fails=0 checks=0
expect() { local d=$1; shift; checks=$((checks + 1)); if "$@"; then echo "PASS: $d"; else echo "FAIL: $d"; fails=$((fails + 1)); return 1; fi; }
say() { printf '\n== %s\n' "$*"; }
install -m644 /packages/build/pacman.conf /etc/pacman.conf
{ pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm --needed git; } >/tmp/setup.log 2>&1 ||
  { tail -n 20 /tmp/setup.log; exit 1; }

git config --global --add safe.directory '*'
git clone -q /grassfield /gf && git -C /gf config user.name test && git -C /gf config user.email test@grassfield.invalid
with_notes() { # commit -> a commit on top of it with its VERSION's release notes
  git -C /gf -c advice.detachedHead=false checkout -q --detach "$1" || return 1
  local v; v=$(tr -d '[:space:]' </gf/VERSION)
  mkdir -p /gf/packaging/release-notes
  echo "Grassfield $v (O22 guard test)." >"/gf/packaging/release-notes/$v.en.txt"
  echo "Grassfield $v (essai du garde-fou O22)." >"/gf/packaging/release-notes/$v.fr.txt"
  git -C /gf add packaging/release-notes && git -C /gf commit -qm "release notes $v (test)" && git -C /gf rev-parse HEAD
}
has_dep() { # -> 0 when the checked-out PKGBUILD's grassfield-desktop depends on grassfield-keyring
  local deps=" $(sed -n '/^package_grassfield-desktop()/,/^}/s/^  depends=(\(.*\))$/\1/p' /gf/packaging/arch/PKGBUILD) "
  [[ $deps == *" grassfield-keyring "* ]]
}
no_dep() { ! has_dep; }
build() { # name ref -> build-channel.sh's exit code; its output in /out/name/build.txt, its key in /out/name
  mkdir -p "/out/$1"
  (
    export GNUPGHOME=$(mktemp -d)
    gpg --batch --pinentry-mode loopback --passphrase "" \
      --quick-gen-key "Grassfield CI build (throwaway) <ci@grassfield.invalid>" ed25519 sign 14d 2>/dev/null
    key=$(gpg --with-colons --list-keys | awk -F: '$1=="fpr" {print $10; exit}')
    gpg --export "$key" >"/out/$1/build-signing-key.gpg"
    /packages/scripts/build-channel.sh --source /gf --ref "$2" --tree "/out/$1/tree" --gnupghome "$GNUPGHOME" --key "$key" \
      >"/out/$1/build.txt" 2>&1
  )
}

say "BEFORE ($BEFORE): grassfield-desktop without the dependency"
ref=$(with_notes "$BEFORE") || { echo "cannot prepare $BEFORE"; exit 1; }
expect "its PKGBUILD: no grassfield-keyring in grassfield-desktop's depends" no_dep
start=$(date +%s)
build before "$ref"; rc=$?
msg=$(grep -m1 'does not depend on grassfield-keyring' /out/before/build.txt)
expect "build-channel.sh refuses it after makepkg -> exit $rc ($(( $(date +%s) - start )) s): ${msg:-no such message}" \
  test "$rc:${msg:+said}" == "1:said" || tail -n 15 /out/before/build.txt
expect "... and writes no release build" test -z "$(ls -A /out/before/tree/releases 2>/dev/null)"

say "AFTER ($AFTER): grassfield-desktop depends on grassfield-keyring"
ref=$(with_notes "$AFTER") || { echo "cannot prepare $AFTER"; exit 1; }
expect "its PKGBUILD: grassfield-keyring in grassfield-desktop's depends" has_dep
start=$(date +%s)
build after "$ref"; rc=$?
expect "build-channel.sh builds it -> exit $rc ($(( $(date +%s) - start )) s)" test "$rc" == 0 || tail -n 15 /out/after/build.txt
/packages/scripts/check-tree.sh --tree /out/after/tree --keyring /out/after/build-signing-key.gpg >/out/after/check.txt 2>&1; rc=$?
expect "check-tree.sh --keyring -> exit $rc, $(grep -c 'grassfield-desktop depends on grassfield-keyring' /out/after/check.txt) sets with the dependency ($(tail -n 1 /out/after/check.txt))" \
  test "$rc" == 0
echo
echo "done: $checks checks, $fails failure(s)"
((fails == 0))
