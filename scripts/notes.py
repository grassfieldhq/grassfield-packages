#!/usr/bin/env python3
"""Write a channel's grassfield-notes.json (grassfield ADR-0033 d.8 and g; owner decision O9).

  notes.py --channel stable|beta --version PKGVER-PKGREL --date YYYY-MM-DD
           (--en FILE [--fr FILE] | --rebuilt-for HYPRLAND_VERSION) [--history GITDIR] > grassfield-notes.json

The new release goes first, then the earlier releases of the channel, newest first, at most 20. Each tag's build is
standalone (built once, ADR-0037 g; the publisher takes its notes as they are), so the earlier releases come from the
built repository itself (--history, the clone of the tag): its tags vX.Y.Z[-betaN|-rcN] that go to the channel (stable:
plain versions only; beta: all) and are older than --version, each with the text of packaging/release-notes/<VERSION>.
{en,fr}.txt at that tag, the pkgrel of its packaging/arch/PKGBUILD and its commit's date (UTC); a tag without notes was
never built and is left out. The text comes from grassfield's packaging/release-notes/<VERSION>.{en,fr}.txt at the built
tag; a pkgrel rebuild says "Rebuilt for Hyprland X.Y.Z" / « Reconstruit pour Hyprland X.Y.Z ». Checked as the client
checks it: UTF-8, plain text (control characters other than line feeds refused), `en` required, at most 8000 characters
a text, at most 64 KiB in all (the oldest releases are dropped to fit). Exit 1, nothing printed, when a check fails.
Python standard library, git and pacman's vercmp. The signature (.sig) is made by the caller.
"""
import argparse
import functools
import json
import os
import re
import subprocess
import sys

NOTES_CAP = 65536
NOTES_MAX = 20
NOTE_CHARS = 8000
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_]*-[1-9][0-9]*(\.[0-9]+)?$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
CONTROL = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f]")
TAG = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)(?:-((?:beta|rc)[1-9][0-9]*))?$")
PKGREL = re.compile(r"^pkgrel=(?:\$\{GRASSFIELD_PKGREL:-)?([1-9][0-9]*)\}?$", re.M)


class Invalid(Exception):
    pass


def text_of(path, lang):
    try:
        with open(path, "rb") as f:
            return checked(f.read(), path)
    except FileNotFoundError:
        raise Invalid(f"{path} is missing: write the release notes ({lang}) in grassfield's packaging/release-notes/")


def checked(raw, path):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid(f"{path} is not UTF-8")
    text = text.replace("\r\n", "\n").strip("\n")
    if not text.strip():
        raise Invalid(f"{path} is empty")
    if CONTROL.search(text):
        raise Invalid(f"{path} holds control characters (plain text only)")
    if len(text) > NOTE_CHARS:
        raise Invalid(f"{path} is longer than {NOTE_CHARS} characters")
    return text


def vercmp(a, b):
    return int(subprocess.run(["vercmp", a, b], capture_output=True, text=True, check=True,
                              stdin=subprocess.DEVNULL).stdout.strip())


def git(repo, *args):
    """git's output (bytes), or None when it fails (a path missing at a tag)."""
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, stdin=subprocess.DEVNULL,
                         env=dict(os.environ, TZ="UTC"))
    return out.stdout if out.returncode == 0 else None


def earlier(repo, channel, version):
    """The channel's releases older than version, from the tags of repo, newest first."""
    out = []
    for tag in (git(repo, "tag", "--list", "v*") or b"").decode().split():
        m = TAG.match(tag)
        if not m or (channel == "stable" and m.group(2)):
            continue
        en = git(repo, "show", f"{tag}:packaging/release-notes/{tag[1:]}.en.txt")
        if en is None:
            continue  # refused by the build (every release has notes): never built
        rel = PKGREL.search((git(repo, "show", f"{tag}:packaging/arch/PKGBUILD") or b"").decode("utf-8", "replace"))
        if not rel:
            raise Invalid(f"cannot read the pkgrel of {tag}'s packaging/arch/PKGBUILD")
        v = f"{m.group(1)}{m.group(2) or ''}-{rel.group(1)}"
        if vercmp(v, version) >= 0:
            continue
        notes = {"en": checked(en, f"{tag}:{tag[1:]}.en.txt")}
        fr = git(repo, "show", f"{tag}:packaging/release-notes/{tag[1:]}.fr.txt")
        if fr is not None:
            notes["fr"] = checked(fr, f"{tag}:{tag[1:]}.fr.txt")
        date = (git(repo, "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d", tag, "--") or b"").decode().strip()
        if not DATE.match(date):
            raise Invalid(f"cannot read the date of {tag}")
        out.append({"version": v, "date": date, "notes": notes})
    return sorted(out, key=functools.cmp_to_key(lambda a, b: vercmp(b["version"], a["version"])))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--channel", required=True, choices=("stable", "beta"))
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--en")
    ap.add_argument("--fr")
    ap.add_argument("--rebuilt-for")
    ap.add_argument("--history")
    args = ap.parse_args(argv)
    try:
        if not VERSION.match(args.version) or not DATE.match(args.date):
            raise Invalid("--version is pkgver-pkgrel and --date YYYY-MM-DD")
        if args.rebuilt_for:
            if args.en or args.fr or not re.match(r"^[0-9][0-9A-Za-z.+_-]*$", args.rebuilt_for):
                raise Invalid("--rebuilt-for takes a Hyprland version and no --en/--fr")
            notes = {"en": f"Rebuilt for Hyprland {args.rebuilt_for}.",
                     "fr": f"Reconstruit pour Hyprland {args.rebuilt_for}."}
        elif args.en:
            notes = {"en": text_of(args.en, "en")}
            if args.fr:
                notes["fr"] = text_of(args.fr, "fr")
        else:
            raise Invalid("--en FILE or --rebuilt-for VERSION is required")
        releases = [{"version": args.version, "date": args.date, "notes": notes}]
        if args.history:
            releases += earlier(args.history, args.channel, args.version)
        releases = releases[:NOTES_MAX]
        while True:
            text = json.dumps({"version": 1, "channel": args.channel, "releases": releases}, ensure_ascii=False,
                              separators=(",", ":"))
            if len(text.encode("utf-8")) <= NOTES_CAP:
                break
            if len(releases) == 1:
                raise Invalid("the notes of one release are larger than 64 KiB")
            releases = releases[:-1]
    except (OSError, ValueError, subprocess.CalledProcessError, Invalid) as e:
        print(f"notes.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
