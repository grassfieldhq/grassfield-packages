#!/usr/bin/env bash
# Runs the tests where they may make throwaway signing keys: a disposable Arch container (CLAUDE.md). The keys live in
# temporary GnuPG homes inside it and go with it. Usage: tests/run-in-container.sh [docker run options…]
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
image=archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0
exec docker run --rm -e CI -e GITHUB_ACTIONS "$@" -v "$root":/src:ro "$image" bash -c '
  set -euo pipefail
  if [[ -f /ccr-ca.crt ]]; then cp /ccr-ca.crt /etc/ca-certificates/trust-source/anchors/ccr.crt && update-ca-trust; fi
  pacman -Syu --noconfirm --needed python python-yaml gnupg >/dev/null
  cd /tmp && cp -r /src /tmp/src && cd /tmp/src
  python3 -I -m unittest discover -s tests ${GRASSFIELD_UNITTEST_ARGS:-} -v'
