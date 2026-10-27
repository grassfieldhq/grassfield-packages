#!/usr/bin/env python3
"""The hosting's edge rule over a channel tree, for tests only (grassfield ADR-0033 h.2; probes Q2 and R4).

  serve.py TREE PORT

Serves TREE on 127.0.0.1:PORT. The fixed names of a channel (/<channel>/<arch>/grassfield.db, grassfield.files,
grassfield-notes.json and their .sig) are answered with a 302 to /<channel>/<arch>/snap/<id>/<name>, where <id> is read
from /<channel>/<arch>/pointer at each request; nothing is cached (Cache-Control: no-store on the redirect and the
pointer). Every other path is a plain file, with the If-Modified-Since handling of Python's http.server (a 304 when the
client's copy is newer, which is what makes a pointer moved back fail, R4). Python standard library only.
"""
import functools
import http.server
import os
import re
import sys

FIXED = re.compile(r"^/(stable|beta)/([a-z0-9_]+)/((grassfield\.(db|files)|grassfield-notes\.json)(\.sig)?)$")


class Edge(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        m = FIXED.match(self.path.split("?", 1)[0])
        if m:
            channel, arch, name = m.group(1), m.group(2), m.group(3)
            try:
                with open(os.path.join(self.directory, channel, arch, "pointer"), encoding="utf-8") as f:
                    snap = f.read().strip()
            except OSError:
                self.send_error(404)
                return
            self.send_response(302)
            self.send_header("Location", f"/{channel}/{arch}/snap/{snap}/{name}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_GET()

    do_HEAD = do_GET

    def log_message(self, fmt, *args):
        sys.stderr.write("serve.py: %s\n" % (fmt % args))


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[0]) or not argv[1].isdigit():
        print("usage: serve.py TREE PORT", file=sys.stderr)
        return 2
    handler = functools.partial(Edge, directory=os.path.abspath(argv[0]))
    http.server.ThreadingHTTPServer(("127.0.0.1", int(argv[1])), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
