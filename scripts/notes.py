#!/usr/bin/env python3
"""Write a channel's grassfield-notes.json (grassfield ADR-0033 d.8 and g; owner decision O9).

  notes.py --channel stable|beta --version PKGVER-PKGREL --date YYYY-MM-DD
           (--en FILE [--fr FILE] | --rebuilt-for HYPRLAND_VERSION) [--previous FILE] > grassfield-notes.json

The new release goes first, then the releases of the channel's previous notes (another entry of the same version is
replaced), at most 20. The text comes from grassfield's packaging/release-notes/<VERSION>.{en,fr}.txt at the built tag;
a pkgrel rebuild says "Rebuilt for Hyprland X.Y.Z" / « Reconstruit pour Hyprland X.Y.Z ». Checked as the client checks
it: UTF-8, plain text (control characters other than line feeds refused), `en` required, at most 8000 characters a
text, at most 64 KiB in all (the oldest releases are dropped to fit). Exit 1, nothing printed, when a check fails.
Python standard library only. The signature (.sig) is made by the caller.
"""
import argparse
import json
import re
import sys

NOTES_CAP = 65536
NOTES_MAX = 20
NOTE_CHARS = 8000
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_]*-[1-9][0-9]*(\.[0-9]+)?$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
CONTROL = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f]")


class Invalid(Exception):
    pass


def text_of(path, lang):
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8")
    except FileNotFoundError:
        raise Invalid(f"{path} is missing: write the release notes ({lang}) in grassfield's packaging/release-notes/")
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--channel", required=True, choices=("stable", "beta"))
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--en")
    ap.add_argument("--fr")
    ap.add_argument("--rebuilt-for")
    ap.add_argument("--previous")
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
        if args.previous:
            with open(args.previous, encoding="utf-8") as f:
                old = json.load(f)
            if not isinstance(old, dict) or old.get("version") != 1 or old.get("channel") != args.channel:
                raise Invalid(f"{args.previous} is not version 1 notes of the {args.channel} channel")
            releases += [r for r in old.get("releases", []) if isinstance(r, dict) and r.get("version") != args.version]
        releases = releases[:NOTES_MAX]
        while True:
            text = json.dumps({"version": 1, "channel": args.channel, "releases": releases}, ensure_ascii=False,
                              separators=(",", ":"))
            if len(text.encode("utf-8")) <= NOTES_CAP:
                break
            if len(releases) == 1:
                raise Invalid("the notes of one release are larger than 64 KiB")
            releases = releases[:-1]
    except (OSError, ValueError, Invalid) as e:
        print(f"notes.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
