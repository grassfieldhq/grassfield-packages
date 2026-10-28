#!/usr/bin/env bash
# Facts for `catalog.py check-env`, read from the system the catalog names (ADR-0037 g "CI also refuses"): the packages of
# Omarchy's stable mirror, the application entries of the packages the catalog names, Arch's AppStream ids and, when the
# catalog lists a Flatpak, Flathub's app ids, and when it lists an AUR app, the AUR's packages of those names. Everything
# read is data.
#
# Runs ONLY as root inside a throwaway Arch container (it rewrites pacman's configuration and syncs it), e.g.:
#   docker run --rm -v "$PWD":/src:ro -v <omarchy checkout>:/omarchy:ro -v <out>:/out \
#     archlinux:base bash /src/tools/catalog-facts.sh /omarchy /src/catalog /out
set -euo pipefail

if [[ ! -f /.dockerenv && ! -f /run/.containerenv ]] || [[ $(id -u) != 0 ]]; then
  echo "catalog-facts.sh: refused: run as root inside a throwaway container" >&2
  exit 2
fi
[[ $# == 3 ]] || { echo "usage: catalog-facts.sh <omarchy checkout> <catalog dir> <out dir>" >&2; exit 2; }
omarchy=$1 src=$2 out=$3
tool=$(dirname "$(readlink -f "$0")")/catalog.py

# The Omarchy release the catalog is checked against must be the pinned one.
want=$(awk '$1 == "commit" {print $2}' "$src/omarchy.lock")
have=$(git -C "$omarchy" rev-parse HEAD 2>/dev/null || cat "$omarchy/.commit" 2>/dev/null || true)
if [[ -z $want || $have != "$want" ]]; then
  echo "catalog-facts.sh: $omarchy is at '${have:-unknown}', catalog/omarchy.lock pins '$want'" >&2
  exit 2
fi

# Exactly Omarchy's stable pacman configuration; Docker has no Landlock for pacman's download sandbox (as ADR-0033's probes).
cp "$omarchy/default/pacman/pacman-stable.conf" /etc/pacman.conf
cp "$omarchy/default/pacman/mirrorlist-stable" /etc/pacman.d/mirrorlist
sed -i 's/^DownloadUser = alpm$/DownloadUser = alpm\nDisableSandbox/' /etc/pacman.conf
pacman-key --init >/dev/null 2>&1
pacman-key --populate archlinux >/dev/null 2>&1
# A whole upgrade, never -Sy alone, even in a throwaway container: python and libarchive come from the same snapshot.
pacman -Syu --noconfirm --needed python libarchive >/dev/null
pacman -Fy >/dev/null

mkdir -p "$out"
{
  echo "# pacman -Sl on Omarchy's stable configuration: repository, package, version"
  pacman -Sl | awk '{print $1, $2, $3}'
} >"$out/repo-packages.txt"

mapfile -t wanted < <(python3 -I "$tool" packages --src "$src")
{
  echo "# pacman -Fl of the packages the catalog names: application entries only"
  if ((${#wanted[@]})); then
    # A name pacman does not know makes -Fl exit 1; check-env reports it from repo-packages.txt.
    { pacman -Fl "${wanted[@]}" 2>/dev/null || true; } | awk '$2 ~ /^usr\/share\/applications\/[^\/]+\.desktop$/ {print $1, "/" $2}'
  fi
} >"$out/app-entries.txt"

# Arch's AppStream: the package file and its signature from pacman's own mirror, checked by pacman's keyring and rule,
# read from gpg itself on a copy of the keyring: pacman-key --verify exits 0 for a good signature by any key of the keyring,
# trusted or not, and for a disabled one (grassfield ADR-0037 S19). One good detached signature, its key fully or
# ultimately valid and not disabled, nothing else.
pacman_trusted() (
  # A subshell: its temporary home goes with it, whatever the outcome.
  home=$(mktemp -d)
  trap 'rm -rf "$home"' EXIT
  cp /etc/pacman.d/gnupg/pubring.* /etc/pacman.d/gnupg/trustdb.gpg "$home"/ 2>/dev/null || exit 1
  status=$(gpg --homedir "$home" --batch --no-tty --no-autostart --status-fd 1 --verify "$1" "$2" 2>/dev/null) || exit 1
  grep -qE '^\[GNUPG:\] (PLAINTEXT|BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY)( |$)' <<<"$status" && exit 1
  [[ $(grep -c '^\[GNUPG:\] VALIDSIG ' <<<"$status") == 1 ]] || exit 1
  grep -qE '^\[GNUPG:\] TRUST_(FULLY|ULTIMATE)( |$)' <<<"$status" || exit 1
  signer=$(awk '$2 == "VALIDSIG" {print $12}' <<<"$status")
  gpg --homedir "$home" --batch --no-autostart --with-colons --list-keys "$signer" 2>/dev/null |
    awk -F: '$1 == "pub" {n++; ok = ($2 == "f" || $2 == "u") && $12 !~ /D/} END {exit !(n == 1 && ok)}'
)
cache=$(mktemp -d)
url=$(pacman -Sp archlinux-appstream-data | tail -1)
pkg=$cache/$(basename "$url")
curl -fsS --max-time 300 -o "$pkg" "$url"
curl -fsS --max-time 60 -o "$pkg.sig" "$url.sig"
pacman_trusted "$pkg.sig" "$pkg" || { echo "catalog-facts.sh: $(basename "$pkg"): not one good signature by a key pacman trusts fully" >&2; exit 1; }
{
  echo "# $(basename "$pkg"): package, AppStream id, component type"
  for xml in $(bsdtar -tf "$pkg" | grep -E '^usr/share/swcatalog/xml/[^/]+\.xml\.gz$'); do
    bsdtar -xOf "$pkg" "$xml" | gzip -dc | python3 -I -c '
import sys, xml.etree.ElementTree as ET
for _, el in ET.iterparse(sys.stdin.buffer):
    if el.tag == "component":
        cid, pkg = el.findtext("id"), el.findtext("pkgname")
        if cid and pkg:
            print(pkg.strip(), cid.strip(), el.get("type", "generic"))
        el.clear()
'
  done | sort -u
} >"$out/appstream-ids.txt"
rm -rf "$cache"

# Flathub, only when the catalog lists a Flatpak: the ids of its AppStream.
if grep -qs '"kind": *"flatpak"' "$src"/apps/*.json; then
  {
    echo "# Flathub's AppStream (dl.flathub.org): app ids"
    curl -fsS --max-time 300 https://dl.flathub.org/repo/appstream/x86_64/appstream.xml.gz | gzip -dc | python3 -I -c '
import sys, xml.etree.ElementTree as ET
for _, el in ET.iterparse(sys.stdin.buffer):
    if el.tag == "component":
        cid = el.findtext("id")
        if cid:
            print(cid.strip().removesuffix(".desktop"))
        el.clear()
' | sort -u
  } >"$out/flathub-ids.txt"
fi

# The AUR, only when the catalog lists an AUR app: the packages its web service (RPC v5 info) has of those names, as name
# and version; anything else in its answer is left out.
mapfile -t aur < <(python3 -I "$tool" aur-packages --src "$src")
if ((${#aur[@]})); then
  args=()
  for name in "${aur[@]}"; do args+=(--data-urlencode "arg[]=$name"); done
  {
    echo "# The AUR's web service (aur.archlinux.org/rpc/v5/info): package, version"
    curl -fsS --max-time 60 --max-filesize 4194304 -G "${args[@]}" https://aur.archlinux.org/rpc/v5/info | python3 -I -c '
import json, re, sys
answer = json.load(sys.stdin)
if not isinstance(answer, dict) or answer.get("type") != "multiinfo" or not isinstance(answer.get("results"), list):
    sys.exit("catalog-facts.sh: the AUR did not answer with package information")
for r in answer["results"]:
    name, version = (r.get("Name"), r.get("Version")) if isinstance(r, dict) else (None, None)
    if isinstance(name, str) and isinstance(version, str) and re.fullmatch(r"[a-z0-9@_+][a-z0-9@._+-]{0,127}", name) \
            and re.fullmatch(r"[A-Za-z0-9._+:~-]{1,64}", version):
        print(name, version)
' | sort -u
  } >"$out/aur-packages.txt"
fi

echo "catalog-facts.sh: $(grep -vc '^#' "$out/repo-packages.txt") packages, $(grep -vc '^#' "$out/app-entries.txt") entries, $(grep -vc '^#' "$out/appstream-ids.txt") AppStream components"
