#!/usr/bin/env bash
# An app folder's PKGBUILD is pinned: one source, GitHub's archive of one full commit, one SHA-256, nothing else that could
# bring other bytes or code (README.md, "Bundled apps"). Every source and checksum array is read, the architecture-suffixed
# ones too (source_x86_64, sha256sums_x86_64: makepkg honours them).
#
#   pin-check.sh APP_DIR
#
# Refused: no 40-hex _commit; not exactly one `source` entry, of the form <pkgname>-<commit>.tar.gz::https://github.com/
# grassfieldhq/<repo>/archive/<commit>.tar.gz; any source_<arch> array; not exactly one checksum array, sha256sums, with one
# 64-hex entry (SKIP, md5/sha1/sha512/b2 arrays, sha256sums_<arch> are refused); install= (an install script runs as root on
# every client, grassfield ADR-0033 b.6); replaces. The PKGBUILD is sourced by bash, as makepkg does: it is this
# repository's own file. Exit 0 pinned, 1 not (the reason on stderr), 2 usage.
set -uo pipefail
[[ $# == 1 && -f $1/PKGBUILD ]] || { echo "usage: pin-check.sh APP_DIR (a folder with its PKGBUILD)" >&2; exit 2; }
dir=$1
fail() { echo "pin-check.sh: ${dir:-?}/PKGBUILD: $*" >&2; exit 1; }

facts=$(bash -c '
  source "$1/PKGBUILD" >/dev/null 2>&1 || { printf "ERR\tcannot be sourced\n"; exit 0; }
  printf "COMMIT\t%s\nNAME\t%s\n" "${_commit-}" "${pkgname-}"
  for v in $(compgen -v); do
    case $v in
      source | source_* | install | replaces | replaces_* | *sums | *sums_*)
        eval "for e in \"\${$v[@]}\"; do printf \"%s\t%s\n\" \"\$v\" \"\$e\"; done" ;;
    esac
  done' _ "$dir") || fail "cannot be read"
grep -q '^ERR' <<<"$facts" && fail "$(sed -n 's/^ERR\t//p' <<<"$facts")"
commit=$(sed -n 's/^COMMIT\t//p' <<<"$facts") name=$(sed -n 's/^NAME\t//p' <<<"$facts")
[[ $commit =~ ^[0-9a-f]{40}$ ]] || fail "_commit '$commit' is not a full 40-hex commit"
sources=$(grep -P '^(source|source_[^\t]*)\t' <<<"$facts" || true)
[[ $(wc -l <<<"$sources") == 1 && $sources == source$'\t'* ]] || fail "not exactly one source, in the plain source array: $(tr '\t\n' ' =' <<<"$sources")"
url=${sources#*$'\t'}
[[ $url =~ ^${name}-${commit}\.tar\.gz::https://github\.com/grassfieldhq/[A-Za-z0-9._-]+/archive/${commit}\.tar\.gz$ ]] ||
  fail "the source is not GitHub's archive of $commit under grassfieldhq: $url"
sums=$(grep -P '^[^\t]*sums[^\t]*\t' <<<"$facts" || true)
[[ $(wc -l <<<"$sums") == 1 && $sums =~ ^sha256sums$'\t'[0-9a-f]{64}$ ]] || fail "not exactly one checksum, a 64-hex sha256sums entry (SKIP, other algorithms and per-architecture arrays are refused): $(tr '\t\n' ' =' <<<"$sums")"
[[ -z $(grep -P '^install\t.' <<<"$facts") ]] || fail "install= is refused (an install script runs as root on every client)"
[[ -z $(grep -P '^replaces[^\t]*\t.' <<<"$facts") ]] || fail "replaces= is refused (ADR-0033 b.6)"
exit 0
