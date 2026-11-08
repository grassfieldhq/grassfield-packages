#!/usr/bin/env python3
"""Does the published Grassfield still match the toolkit Omarchy ships? (grassfield ADR-0033 f, ADR-0041 step 2a, SQ-3 A.)

Run daily by .github/workflows/watch-hyprland.yml. Standard library, plus the `zstd` command line (on the GitHub runner and
in the Arch image). It reads, over https and never writing anywhere but its --out file:

  1. The PUBLISHED channel's build record: <packages>/<channel>/x86_64/grassfield.db (the Worker answers 302 to the current
     snapshot), then the two package files it lists, each checked against the database's SHA-256:
       grassfield-desktop      usr/share/grassfield/BUILD-DEPS       the toolkit the build ran against (U27, ADR-0033 s3.4)
       grassfield-compositor   usr/lib/grassfield/grassfield-compositor.abi   the plugin's ABI stamp (first line)
     These are the files the client reads, so this is the record that decides whether a client refuses; the build-<id>.txt of
     scripts/build-channel.sh is a CI artifact and is not published. The bounds of grassfield-hold come from that same
     BUILD-DEPS (quickshell at its version without pkgrel, qt6-base at major.minor: grassfield packaging/arch/hold-bounds.sh,
     whose rule this restates; tests/test_watch_toolkit.py holds the same cases as grassfield's tests/shell/update_hold.sh).
  2. Omarchy's two channels, each its own mirror: `stable` and `rc`.
       quickshell   <pkgs.omarchy.org>/<channel>/x86_64/omarchy.db   ([omarchy] serves it, not [extra])
       qt6-base     <channel>-mirror.omarchy.org/extra/os/x86_64/extra.db
       hyprland     the same extra.db, then the package file: usr/include/hyprland/src/version.h gives the ABI stamp by the
                    formula of grassfield compositor/abi-stamp.cmake (the commit, then the aquamarine, hyprutils, hyprgraphics,
                    hyprcursor and hyprlang versions without their patch number). A version string that moved with the same
                    stamp (a pkgrel bump) needs no rebuild; a stamp that moved with the Hyprland version string unchanged
                    cannot happen (the stamp is inside that package).

  watch_toolkit.py [--channels beta stable] [--out result.json]    exit 0 compared (a rebuild may be due), 1 a source could not
                                                                   be read or checked (fail loudly), 2 usage

The result (--out, and a summary on stdout) lists `rebuild`: a rebuild with pkgrel + 1 of the published ref, due because
Omarchy's STABLE channel differs from the build (build.yml builds against stable's mirrors: build/pacman.conf); and `issue`: what
a person must decide, because only Omarchy's rc channel differs (build.yml has no rc variant: a build ahead of stable needs
the owner's choice), or the published record cannot be compared (no ABI stamp). The workflow starts the builds and opens the
issue; this program starts nothing. Everything it reads is data: a database it cannot parse, a hash that does not match or a
missing member is an error, never a guess. It checks no signature: a record that lied could only start a needless rebuild
(the release job still waits for the owner's approval) or miss one (the next day's run reads it again).
"""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PACKAGES = "https://packages.grassfield.site"
OMARCHY = "https://pkgs.omarchy.org"
MIRROR = "https://{channel}-mirror.omarchy.org"
OMARCHY_CHANNELS = ("stable", "rc")
RECORD = "usr/share/grassfield/BUILD-DEPS"
ABI_FILE = "usr/lib/grassfield/grassfield-compositor.abi"
VERSION_H = "usr/include/hyprland/src/version.h"
LIMIT_DB = 64 << 20
LIMIT_PKG = 400 << 20
LIMIT_UNPACKED = 1 << 30   # what zstd may write for one file (a package of 400 MiB never unpacks to more than this)
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ABI_RE = re.compile(r"[0-9a-f]{40}(_[a-z]+_[0-9]+(\.[0-9]+)*)+")
NAME_RE = re.compile(r"[a-z0-9@_+][a-z0-9@._+-]*")
VERSION_RE = re.compile(r"[A-Za-z0-9:._+~-]+")
PKGVER_RE = re.compile(r"(\d+\.\d+\.\d+)(?:(beta|rc)([1-9]\d*))?-([1-9]\d*)")


class WatchError(Exception):
    """A source could not be read or did not check out: the run fails loudly."""


class SameHosts(urllib.request.HTTPRedirectHandler):
    """A redirect goes to https on a host this tool already reads from, and nowhere else."""

    def __init__(self, hosts):
        self.hosts = frozenset(hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or (parts.hostname or "") not in self.hosts:
            raise WatchError(f"refused: {req.full_url} redirects to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Http:
    """The one place that touches the network (replaced in the tests)."""

    def __init__(self, retries=3, timeout=120, hosts=None):
        self.retries = retries
        self.timeout = timeout
        self.hosts = set(hosts or ())
        self.opener = urllib.request.build_opener(SameHosts(self.hosts))

    def get(self, url, limit):
        """The body of an https URL (redirects followed by urllib), or None for a 404; anything else is an error."""
        if not url.startswith("https://"):
            raise WatchError(f"refused: {url} is not https")
        if self.hosts and (urllib.parse.urlsplit(url).hostname or "") not in self.hosts:
            raise WatchError(f"refused: {url} is not on a host this tool reads from")
        last = None
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "grassfield-watch-toolkit"})
                with self.opener.open(request, timeout=self.timeout) as answer:
                    data = b""
                    while len(data) <= limit:
                        chunk = answer.read(1 << 20)
                        if not chunk:
                            break
                        data += chunk
                if len(data) > limit:
                    raise WatchError(f"{url}: more than {limit} bytes")
                return data
            except WatchError:
                raise
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                last = f"HTTP {error.code}"
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last = str(error)
            time.sleep(2 * (attempt + 1))
        raise WatchError(f"{url}: {last}")


def decompress(data):
    """The bytes of a zstd stream (a package, or Omarchy's database); anything else as it is."""
    if data[:4] == b"\x28\xb5\x2f\xfd":
        with tempfile.NamedTemporaryFile() as source:
            source.write(data)
            source.flush()
            child = subprocess.Popen(["zstd", "-dc", "-q", source.name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            out = bytearray()
            try:
                while True:
                    chunk = child.stdout.read(1 << 20)
                    if not chunk:
                        break
                    out += chunk
                    if len(out) > LIMIT_UNPACKED:
                        child.kill()
                        raise WatchError(f"a file unpacks to more than {LIMIT_UNPACKED} bytes")
            finally:
                child.stdout.close()
                if child.wait() != 0 and len(out) <= LIMIT_UNPACKED:
                    raise WatchError("zstd could not decompress a file")
        return bytes(out)
    return data


def tar_of(data):
    try:
        return tarfile.open(fileobj=io.BytesIO(decompress(data)), mode="r:*")
    except tarfile.TarError as error:
        raise WatchError(f"not a tar archive: {error}") from error


def member(data, path):
    """A regular file of a package, by its path ('./' stripped); None when the package lacks it."""
    with tar_of(data) as archive:
        for entry in archive:
            if entry.name.lstrip("./") == path:
                if not entry.isreg():
                    raise WatchError(f"{path} is not a regular file")
                handle = archive.extractfile(entry)
                return handle.read(1 << 20).decode("utf-8", "replace") if handle else None
    return None


def parse_desc(text):
    """The fields of a pacman database entry: {'NAME': ['x'], 'VERSION': ['1-1'], ...}."""
    fields, key = {}, None
    for line in text.splitlines():
        match = re.fullmatch(r"%([A-Z0-9]+)%", line)
        if match:
            key = match.group(1)
            fields[key] = []
        elif line and key:
            fields[key].append(line)
    return fields


def read_db(data):
    """Every package of a sync database: {name: desc fields}, the last of equal names winning."""
    packages = {}
    with tar_of(data) as archive:
        for entry in archive:
            if entry.isreg() and entry.name.endswith("/desc"):
                handle = archive.extractfile(entry)
                fields = parse_desc((handle.read(1 << 20) if handle else b"").decode("utf-8", "replace"))
                name = (fields.get("NAME") or [""])[0]
                if NAME_RE.fullmatch(name) and fields.get("VERSION") and fields.get("FILENAME"):
                    packages[name] = fields
    return packages


# --- the rules (grassfield packaging/arch/hold-bounds.sh and compositor/abi-stamp.cmake, restated) -----------------------

def parse_record(text):
    """BUILD-DEPS: {name: version}, from `<name> <version>` lines; a line that is not one is an error."""
    record = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or not NAME_RE.fullmatch(parts[0]) or not VERSION_RE.fullmatch(parts[1]):
            raise WatchError(f"BUILD-DEPS: unreadable line '{line}'")
        record[parts[0]] = parts[1]
    return record


def without_pkgrel(version):
    return version.rsplit("-", 1)[0] if "-" in version else version


def minor(version):
    """[epoch:]MAJOR.MINOR of a version (U27's key for Qt); None when it has none."""
    match = re.match(r"^((?:\d+:)?)(\d+)\.(\d+)", without_pkgrel(version))
    return f"{match.group(1)}{match.group(2)}.{int(match.group(3))}" if match else None


def next_minor(version):
    match = re.match(r"^((?:\d+:)?)(\d+)\.(\d+)", without_pkgrel(version))
    return f"{match.group(1)}{match.group(2)}.{int(match.group(3)) + 1}" if match else None


def bounds_of(record):
    """What grassfield-hold would bound for this build record: quickshell at its version, qt6-base from minor to next minor."""
    try:
        quickshell, qt = without_pkgrel(record["quickshell"]), record["qt6-base"]
    except KeyError as error:
        raise WatchError(f"BUILD-DEPS lacks {error.args[0]}") from error
    if not quickshell or minor(qt) is None:
        raise WatchError("BUILD-DEPS: a version the hold cannot bound")
    return {"quickshell": quickshell, "qt6-base": [minor(qt), next_minor(qt)]}


def define(text, name):
    match = re.search(rf'#define[ \t]+{name}[ \t]+"([^"\n]*)"', text)
    return match.group(1) if match else ""


def abi_of(version_h):
    """The plugin's ABI stamp of a Hyprland version.h (compositor/abi-stamp.cmake)."""
    commit = define(version_h, "GIT_COMMIT_HASH")
    if not commit:
        raise WatchError("version.h: GIT_COMMIT_HASH is missing")
    if not COMMIT_RE.fullmatch(commit):
        raise WatchError("version.h: GIT_COMMIT_HASH is not 40 hexadecimal digits")
    stamp = commit
    for name, tag in (("AQUAMARINE_VERSION", "aq"), ("HYPRUTILS_VERSION", "hu"), ("HYPRGRAPHICS_VERSION", "hg"),
                      ("HYPRCURSOR_VERSION", "hc"), ("HYPRLANG_VERSION", "hlg")):
        value = define(version_h, name)
        if not value:
            raise WatchError(f"version.h: {name} is missing")
        stamp += f"_{tag}_{value.rsplit('.', 1)[0] if '.' in value else value}"
    if not ABI_RE.fullmatch(stamp):
        raise WatchError("version.h: the ABI stamp it gives is not of the plain form")
    return stamp


def tag_of(version):
    """The grassfield tag a published pkgver-pkgrel was built from, and its pkgrel: ('v1.0.0-rc7', 1) for 1.0.0rc7-1."""
    match = PKGVER_RE.fullmatch(version)
    if not match:
        raise WatchError(f"published version '{version}' is not a pkgver-pkgrel this tool knows")
    base, kind, number, pkgrel = match.groups()
    return (f"v{base}-{kind}{number}" if kind else f"v{base}"), int(pkgrel)


# --- the sources -------------------------------------------------------------------------------------------------------

def published(http, base, channel):
    """The published channel's record, or None when the channel has no published snapshot (a 404 on its database)."""
    url = f"{base}/{channel}/x86_64"
    data = http.get(f"{url}/grassfield.db", LIMIT_DB)
    if data is None:
        return None
    db = read_db(data)
    files = {}
    for name in ("grassfield-desktop", "grassfield-compositor"):
        if name not in db:
            raise WatchError(f"{channel}: grassfield.db does not list {name}")
        fields = db[name]
        filename = fields["FILENAME"][0]
        if not re.fullmatch(r"[A-Za-z0-9._+-]+\.pkg\.tar\.zst", filename):
            raise WatchError(f"{channel}: {name}: unexpected file name '{filename}'")
        blob = http.get(f"{url}/{filename}", LIMIT_PKG)
        if blob is None:
            raise WatchError(f"{channel}: {filename} is listed and not served")
        want = (fields.get("SHA256SUM") or [""])[0]
        if hashlib.sha256(blob).hexdigest() != want:
            raise WatchError(f"{channel}: {filename} does not match the database's SHA-256")
        files[name] = blob
    version = db["grassfield-desktop"]["VERSION"][0]
    # Everything that can reach the summary or an issue is checked against a strict form first (no markdown, no @mention).
    tag_of(version)
    if db["grassfield-compositor"]["VERSION"][0] != version:
        raise WatchError(f"{channel}: desktop {version} and compositor {db['grassfield-compositor']['VERSION'][0]} differ")
    text = member(files["grassfield-desktop"], RECORD)
    if text is None:
        raise WatchError(f"{channel}: grassfield-desktop {version} has no {RECORD}")
    abi_text = member(files["grassfield-compositor"], ABI_FILE)
    abi = abi_text.splitlines()[0].strip() if abi_text and abi_text.strip() else ""
    if abi and not ABI_RE.fullmatch(abi):
        raise WatchError(f"{channel}: the plugin's ABI stamp is not of the plain form")
    ref, pkgrel = tag_of(version)
    record = parse_record(text)
    return {"version": version, "ref": ref, "pkgrel": pkgrel, "record": record, "bounds": bounds_of(record), "abi": abi}


def package_version(db, name, where):
    if name not in db:
        raise WatchError(f"{where}: {name} is not in the database")
    version = db[name]["VERSION"][0]
    if not VERSION_RE.fullmatch(version):
        raise WatchError(f"{where}: {name} has a version of no plain form")
    return version


def _need(data, what):
    if data is None:
        raise WatchError(f"{what}: not found (404)")
    return data


def omarchy_versions(http, channel):
    """quickshell, qt6-base and Hyprland as an Omarchy channel serves them (versions; the Hyprland file is read on demand)."""
    omarchy = read_db(_need(http.get(f"{OMARCHY}/{channel}/x86_64/omarchy.db", LIMIT_DB), f"{channel}: omarchy.db"))
    mirror = MIRROR.format(channel=channel)
    extra = read_db(_need(http.get(f"{mirror}/extra/os/x86_64/extra.db", LIMIT_DB), f"{channel}: extra.db"))
    hyprland = extra.get("hyprland") or {}
    return {
        "quickshell": package_version(omarchy, "quickshell", f"{channel} omarchy.db"),
        "qt6-base": package_version(extra, "qt6-base", f"{channel} extra.db"),
        "hyprland": package_version(extra, "hyprland", f"{channel} extra.db"),
        "_mirror": mirror,
        "_fields": hyprland,
    }


def hyprland_abi(http, channel, versions):
    """The ABI stamp of the Hyprland package an Omarchy channel serves: its version.h, from the package file."""
    fields = versions["_fields"]
    filename = fields["FILENAME"][0]
    if not re.fullmatch(r"hyprland-[A-Za-z0-9._+-]+\.pkg\.tar\.zst", filename):
        raise WatchError(f"{channel}: unexpected Hyprland file name '{filename}'")
    blob = _need(http.get(f"{versions['_mirror']}/extra/os/x86_64/{filename}", LIMIT_PKG), f"{channel}: {filename}")
    if hashlib.sha256(blob).hexdigest() != (fields.get("SHA256SUM") or [""])[0]:
        raise WatchError(f"{channel}: {filename} does not match the database's SHA-256")
    text = member(blob, VERSION_H)
    if text is None:
        raise WatchError(f"{channel}: {filename} has no {VERSION_H}")
    return abi_of(text), f"version.h of {filename}"


def differences(built, candidate):
    """Why a build with this record and plugin stamp no longer matches an Omarchy channel's packages (the ABI stamp too when
    the published plugin has one; a plugin without one is reported apart)."""
    reasons = []
    quickshell = without_pkgrel(candidate["quickshell"])
    if quickshell != built["bounds"]["quickshell"]:
        reasons.append(f"quickshell {candidate['quickshell']} (the hold keeps quickshell={built['bounds']['quickshell']})")
    low, high = built["bounds"]["qt6-base"]
    if minor(candidate["qt6-base"]) != low:
        reasons.append(f"qt6-base {candidate['qt6-base']} (the hold keeps >={low} and <{high})")
    if built["abi"] and candidate["abi"] != built["abi"]:
        reasons.append(f"Hyprland {candidate['hyprland']} has the plugin ABI {candidate['abi']}, the build's is {built['abi']}")
    return reasons


def watch(http, base, channels):
    """The comparison: each published channel's record against both Omarchy channels."""
    result = {"published": {}, "omarchy": {}, "rebuild": [], "issue": None, "notes": []}
    for channel in channels:
        record = published(http, base, channel)
        if record is None:
            result["notes"].append(f"{channel}: nothing is published (no database): not watched")
        else:
            result["published"][channel] = record
    if not result["published"]:
        raise WatchError("no channel is published: nothing to watch (a published beta is expected)")
    sources = {o: omarchy_versions(http, o) for o in OMARCHY_CHANNELS}
    downloaded = {}   # (omarchy channel, hyprland version) -> (abi, where it came from)
    due = {}          # (ref, pkgrel) -> the rebuild Omarchy's stable channel calls for
    ahead, unknown = [], []
    for channel, built in result["published"].items():
        built_hyprland = built["record"].get("hyprland", "")
        if not built["abi"]:
            unknown.append(f"{channel} {built['version']}: the published plugin has no ABI stamp to compare")
        by_channel = {}
        for omarchy in OMARCHY_CHANNELS:
            versions = sources[omarchy]
            if versions["hyprland"] == built_hyprland and built["abi"]:
                abi, where = built["abi"], "the same Hyprland package as the build"
            else:
                key = (omarchy, versions["hyprland"])
                if key not in downloaded:
                    downloaded[key] = hyprland_abi(http, omarchy, versions)
                abi, where = downloaded[key]
            candidate = {"quickshell": versions["quickshell"], "qt6-base": versions["qt6-base"],
                         "hyprland": versions["hyprland"], "abi": abi, "abi_from": where}
            result["omarchy"][omarchy] = candidate
            by_channel[omarchy] = differences(built, candidate)
            if not by_channel[omarchy] and versions["hyprland"] != built_hyprland:
                result["notes"].append(f"{channel}: Omarchy {omarchy} has Hyprland {versions['hyprland']} with the plugin ABI of the build "
                                       f"(built with {built_hyprland or 'unknown'}): no rebuild is needed")
        if by_channel["stable"]:
            entry = due.setdefault((built["ref"], built["pkgrel"] + 1), {"ref": built["ref"], "pkgrel": built["pkgrel"] + 1,
                                                                         "channels": [], "reasons": []})
            entry["channels"].append(channel)
            entry["reasons"] += [f"Omarchy stable: {r}" for r in by_channel["stable"] if f"Omarchy stable: {r}" not in entry["reasons"]]
        # What rc differs on and stable does not (stable's differences are the rebuild above) waits for a person.
        ahead += [f"{channel} {built['version']}: Omarchy rc: {r}" for r in by_channel["rc"] if r not in by_channel["stable"]]
    result["rebuild"] = list(due.values())
    if ahead or unknown:
        lines = ["The daily toolkit watch found something a person must decide.", ""]
        if ahead:
            lines += ["Omarchy's rc channel is ahead of what its stable channel serves, and build.yml builds against stable's mirrors "
                      "(build/pacman.conf), so no automatic rebuild can be made for it. Choose: add an rc variant of the build, or wait for stable.", ""]
            lines += [f"- {a}" for a in ahead] + [""]
        if unknown:
            lines += ["A published build that cannot be fully compared:", ""] + [f"- {u}" for u in unknown] + [""]
        lines += ["The hold's bounds and the plugin's ABI stamp are read from the published packages (tools/watch_toolkit.py); nothing was changed."]
        result["issue"] = {"title": "Toolkit watch: a decision is needed", "body": "\n".join(lines)}
    return result


def summary(result):
    lines = []
    for channel, built in result["published"].items():
        lines.append(f"published {channel}: grassfield {built['version']} (ref {built['ref']}); hold keeps quickshell={built['bounds']['quickshell']}, "
                     f"qt6-base>={built['bounds']['qt6-base'][0]} <{built['bounds']['qt6-base'][1]}; plugin ABI {built['abi'] or 'unknown'}")
    for omarchy, found in result["omarchy"].items():
        lines.append(f"omarchy {omarchy}: quickshell {found['quickshell']}, qt6-base {found['qt6-base']}, hyprland {found['hyprland']} "
                     f"(ABI {found['abi']}, from {found['abi_from']})")
    lines += [f"note: {n}" for n in result["notes"]]
    lines += [f"REBUILD due: {r['ref']} pkgrel {r['pkgrel']} for {', '.join(r['channels'])}: {'; '.join(r['reasons'])}" for r in result["rebuild"]]
    if result["issue"]:
        lines.append("ISSUE: " + result["issue"]["title"])
    if not result["rebuild"] and not result["issue"]:
        lines.append("nothing to do: the published Grassfield matches Omarchy's stable and rc")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--channels", nargs="+", default=["beta", "stable"], choices=["beta", "stable"])
    parser.add_argument("--out", help="write the result as JSON here")
    parser.add_argument("--packages", default=PACKAGES)
    args = parser.parse_args(argv)
    try:
        base = args.packages.rstrip("/")
        hosts = {urllib.parse.urlsplit(u).hostname for u in (base, OMARCHY, MIRROR.format(channel="stable"), MIRROR.format(channel="rc"))}
        result = watch(Http(hosts=hosts), base, args.channels)
    except WatchError as error:
        print(f"watch_toolkit: {error}", file=sys.stderr)
        return 1
    print(summary(result))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
