#!/usr/bin/env python3
"""The members of a bundled app's package as a tar parser sees them, pax extended headers included.

    python3 -I pkg-members.py PACKAGE.pkg.tar.zst

`bsdtar -tv` shows a member's type, mode, owner and name, and nothing else: an extended attribute (security.capability
above all: pacman restores file capabilities from the archive, no install script needed), a POSIX ACL or file flags travel
in pax extended headers (SCHILY.xattr.*, LIBARCHIVE.xattr.*, SCHILY.acl.*, SCHILY.fflags) that the listing never prints. This
reads the zstd-decompressed stream with Python's tarfile, which exposes every member's pax_headers, and refuses:
  - any pax header key other than the plain ones (path, linkpath, size, mtime, atime, ctime, uid, gid, uname, gname,
    charset, comment), in a member or in a global header: so no xattr, ACL, file flag or other extension;
  - a member that is not a regular file or a folder (link, device, FIFO, socket, sparse or any other type);
  - an owner or group that is not root (uid and gid 0, names root or empty);
  - a setuid, setgid or sticky bit, and any group- or world-writable mode.
It reads, never extracts, and runs nothing. Exit 0 clean, 1 a problem (the reason on stderr), 2 usage.
"""
import subprocess
import sys
import tarfile

PLAIN = {"path", "linkpath", "size", "mtime", "atime", "ctime", "uid", "gid", "uname", "gname", "charset", "comment"}


def problems(stream):
    out = []
    tar = tarfile.open(fileobj=stream, mode="r|")
    for member in tar:
        name = member.name
        extra = sorted(set(member.pax_headers) - PLAIN)
        if extra:
            out.append(f"{name}: pax header(s) {', '.join(extra)}")
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE):
            out.append(f"{name}: not a regular file or a folder (type {member.type!r})")
        if member.uid != 0 or member.gid != 0 or member.uname not in ("root", "") or member.gname not in ("root", ""):
            out.append(f"{name}: owned by {member.uname or member.uid}:{member.gname or member.gid}, not root:root")
        if member.mode & 0o7000:
            out.append(f"{name}: setuid, setgid or sticky bit (mode {member.mode:o})")
        if member.mode & 0o022:
            out.append(f"{name}: group- or world-writable (mode {member.mode:o})")
    extra = sorted(set(tar.pax_headers) - PLAIN)
    if extra:
        out.append(f"global pax header(s) {', '.join(extra)}")
    return out


def main(argv):
    if len(argv) != 2:
        print("usage: pkg-members.py PACKAGE.pkg.tar.zst", file=sys.stderr)
        return 2
    proc = subprocess.Popen(["zstd", "-dc", "--", argv[1]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        found = problems(proc.stdout)
        while proc.stdout.read(1 << 16):  # the rest of the stream, so the exit status below is the whole file's
            pass
    except (tarfile.TarError, OSError, EOFError) as e:
        found = [f"not a readable tar stream: {e}"]
    if proc.wait() != 0:
        found.append("not a zstd stream, or a damaged one")
    for line in found:
        print(f"pkg-members.py: {argv[1].rsplit('/', 1)[-1]}: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
