#!/usr/bin/env bash
# scripts/newest-release.sh, the release a channel's publisher picks (grassfield ADR-0033 h.2 as amended, e): stable takes
# plain versions only, beta every one; the newest by pacman's vercmp (beta9 < beta10 < rc1); nothing when the snapshot holds
# it already. Needs vercmp: runs itself in a throwaway archlinux:base container. Exit 0 all PASS (or SKIP without docker).
set -u
IMAGE=archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0
if [[ ${1:-} != --inside ]]; then
  here=$(cd "$(dirname "$0")/.." && pwd)
  command -v docker >/dev/null && docker info >/dev/null 2>&1 || { echo "SKIP: no docker daemon"; exit 0; }
  exec docker run --rm -v "$here:/p:ro" "$IMAGE" bash /p/tests/newest-release.sh --inside
fi
f=0
t() {
  local want=$1 got
  shift
  got=$(printf '%s\n' v1.0.0 v1.0.1 v1.1.0-beta1 v1.1.0-beta10 v1.1.0-beta9 v1.1.0-rc1 v2.0 junk v1.0.2-alpha1 |
    /p/scripts/newest-release.sh "$@")
  if [[ $got == "$want" ]]; then echo "PASS: $* -> '$got'"; else echo "FAIL: $* -> '$got' (want '$want')"; f=1; fi
}
t v1.0.1 stable
t v1.0.1 stable 1.0.0-3
t "" stable 1.0.1-3
t "" stable 1.1.0-1
t v1.1.0-rc1 beta
t v1.1.0-rc1 beta 1.1.0beta10-3
t "" beta 1.1.0rc1-3
t v1.1.0-rc1 beta 1.0.1-3
/p/scripts/newest-release.sh nightly </dev/null 2>/dev/null
if [[ $? == 2 ]]; then echo "PASS: an unknown channel -> exit 2"; else echo "FAIL: an unknown channel"; f=1; fi
exit $f
