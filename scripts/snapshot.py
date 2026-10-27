#!/usr/bin/env python3
"""The current snapshot of a channel, for the shell tools (check-tree.sh, view.sh, rollback.sh, the tests): the pointer as
the one publisher writes it (tools/publish.py: {"snapshot": "<id>"}, grassfield ADR-0033 h.2, ADR-0037 g).

  snapshot.py current DIR      DIR is <channel>/x86_64; prints the id, or "" when there is no pointer yet

Standard library only. Exit 0, 1 a pointer that names no snapshot id, 2 usage.
"""
import json
import os
import re
import sys

ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


def main(argv):
    if len(argv) != 2 or argv[0] != "current":
        print("usage: snapshot.py current DIR", file=sys.stderr)
        return 2
    try:
        with open(os.path.join(argv[1], "pointer"), "rb") as f:
            snap = json.loads(f.read())["snapshot"]
    except FileNotFoundError:
        print("")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"snapshot.py: {argv[1]}/pointer: {e}", file=sys.stderr)
        return 1
    if not isinstance(snap, str) or not ID.match(snap):
        print(f"snapshot.py: {argv[1]}/pointer does not name a snapshot", file=sys.stderr)
        return 1
    print(snap)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
