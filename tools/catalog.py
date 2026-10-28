#!/usr/bin/env python3
"""Grassfield Store catalog: validate the sources, check them against the system they name, build, sign, verify.

The contract is grassfieldhq/grassfield docs/decisions/ADR-0037 g (format, rules, signature, publication); this tool is
its build side. Standard library only. Upstream data (pacman's databases, AppStream, Flathub, Omarchy's scripts) is data.

  catalog.py validate  [--src catalog]
  catalog.py packages  [--src catalog]                         the package names check-env needs facts for
  catalog.py check-env [--src catalog] --facts DIR --omarchy DIR
  catalog.py build     [--src catalog] --channel stable --serial N --out DIR
  catalog.py sign      --homedir DIR --key FINGERPRINT FILE
  catalog.py verify    --keyring-dir DIR --channel stable [--min-serial N] DIR

Sources (catalog/): categories.json; sections/<id>.json (with "order", which the build drops); apps/<id>.json (one app,
the file named by its id); icons/<name>.png with icons/<name>.json ({"license", "origin"}; an app names it as "icon").
Exit codes: 0 ok, 1 the input breaks a rule (each problem on stderr), 2 usage or environment error.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse

CATALOG_NAME = "grassfield-catalog.v1.json"
MAX_CATALOG = 1024 * 1024
MAX_ICON = 256 * 1024
MAX_ICON_SIDE = 512
CHANNELS = ("stable", "beta")
LANGS = ("en", "fr")
REPOS = ("core", "extra", "multilib", "omarchy")
SOURCE_KINDS = ("repo", "aur", "omarchy-setup", "webapp", "flatpak")
BLOCK_KINDS = ("hero", "cards", "row")

# ADR-0037 e.5 and g.
SECTION_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
APP_ID = re.compile(r"^[A-Za-z0-9._-]{1,255}\Z")
PACKAGE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]{0,127}\Z")
SETUP_INSTALL = re.compile(r"^omarchy-install-[a-z0-9-]+\Z")
SETUP_REMOVE = re.compile(r"^omarchy-remove-[a-z0-9-]+\Z")
RECIPE_ARG = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}\Z")
DESKTOP_ID = re.compile(r"^[A-Za-z0-9._-]{1,250}\.desktop\Z")
FLATPAK_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}\Z")
SYMBOL = re.compile(r"^[a-z][a-z0-9-]{0,47}\Z")
FREEDESKTOP = re.compile(r"^[A-Za-z0-9-]{1,64}\Z")
SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
# The catalog's "omarchy" object (ADR-0037 g): the release its setups were read against, and the pins the Store checks
# the installed Omarchy against before it runs a setup or one of the AUR's two commands (a path relative to Omarchy's
# folder, no "." or ".." segment).
OMARCHY_TAG = re.compile(r"^v[0-9]+(\.[0-9]+){0,3}\Z")
OMARCHY_COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
OMARCHY_FILE_PATH = re.compile(r"^(?!.*(^|/)\.{1,2}(/|\Z))[A-Za-z0-9_.+-]+(/[A-Za-z0-9_.+-]+){0,7}\Z")
MAX_OMARCHY_FILES = 512
LICENSE = re.compile(r"^[A-Za-z0-9.+()-]+( (AND|OR|WITH) [A-Za-z0-9.+()-]+)*\Z")
GENERATED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
ICON_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\Z")
FINGERPRINT = re.compile(r"^[0-9A-F]{40}\Z")

# Lengths in code points (ADR-0037 g).
LEN_SECTION_TITLE, LEN_EYEBROW, LEN_TITLE, LEN_TEXT, LEN_DESCRIPTION = 40, 40, 80, 200, 4000
# Bidirectional formatting characters: plain text never needs them, and they can make a text read other than it is.
BIDI = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")

# Recipes: what the catalog may name (ADR-0037 a, e.4 and g). The control is the pin: catalog/omarchy.lock records the
# sha256 of every Omarchy file the catalog's setups and the AUR's two commands (AUR_COMMANDS) run or read, transitively,
# and check-env refuses any file that differs, is missing or is not pinned, until a person has read it and `catalog.py
# pin` writes the new pins. A shell cannot be judged by patterns alone, so the scan below is the second line: it runs at
# pin time (pin refuses to write pins over a finding) and in check-env, to help the person who reads the files. It reads
# the text as shell and fails closed where it cannot read it: comments dropped, heredoc bodies set apart, every command
# found after the wrappers that run it (sudo -u x, env, command, exec, timeout, gum ... --, systemd-run...), $(...),
# `...`, a shell's -c argument and a terminal launcher's command line read as commands too; text it cannot parse, eval,
# a script read from a pipe or a heredoc, a command made by a substitution, an Omarchy command named at run time, an
# Omarchy command or a sourced file outside the pinned files, and pacman's options or arguments made at run time are
# refused, never guessed. A command named by a variable is resolved when the file only ever sets that variable to
# literal text (pm=pacman); otherwise it is listed for the person reading the files, not refused.
# A sync makes the next install a partial upgrade (S12): any short-option cluster with y (-Sy, -Syu, -S -y), --refresh or
# --sysupgrade or a start of them (--ref, --sysu) on pacman, yay or paru, and a yay or paru with no operation (alone it is
# -Syu; with a term, an interactive AUR install). pacman -U installs a file from outside the repositories. A download runs
# code pacman never checked: curl, wget, aria2c, rsync and their kin, makepkg, git clone, pull, fetch or submodule, yay or
# paru -G or -B, flatpak, the language installers (mise, npm, npx, pipx, pip, cargo, uv, go, gem), an interpreter's own
# network code, and an AUR build (omarchy-pkg-aur-add, or yay/paru -S, of a name no repository serves or known only at
# run time). The setups Omarchy marks as such (GeForce NOW, Battle.net, dev-env, Hermes) are refused.
# The two patterns below are a plainer reading of the same text.
SYNC = re.compile(r"\b(pacman|yay|paru)\b[^\n;&|]*?\s(-[A-Za-z]*y[A-Za-z]*|--ref[a-z]*|--sysu[a-z]*)\b")
DOWNLOAD = re.compile(r"\b(curl|wget|makepkg|aria2c)\b|\bgit\b[^\n;&|]*\s(clone|pull|fetch|submodule)\b|"
                      r"\b(yay|paru)\b[^\n;&|]*\s(-G|--getpkgbuild|-B|--build)\b|"
                      r"\|\s*(sudo\s+)?(ba|z|da|k)?sh\s*($|[;&|)])")
SHELL_PUNCT = "();<>|&"
REDIRECTS = {"<", ">", ">>", "<<", ">&", "<&", "&>", "&>>", ">|", "<>", "<<<"}
SHELL_OPERATORS = {";", ";;", ";&", ";;&", "&&", "||", "|", "|&", "&", "(", ")", "((", "))"}
SHELL_OPS_BY_LENGTH = sorted(SHELL_OPERATORS | REDIRECTS, key=len, reverse=True)
# What prepare() puts in place of $(...), `...`, <(...) and $((...)): code made at run time, read on its own.
PLACEHOLDER = "__subst"
SUBST, PROCESS, ARITH = "__subst__", "__subst_process__", "__arith__"
# A script's own folder, Omarchy's idiom: "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)", read as that folder.
SELF_DIR = re.compile(r'\$\(cd -- "\$\(dirname -- "\$\{BASH_SOURCE\[0\]\}"\)" && pwd\)')
SHELL_KEYWORDS = {"if", "then", "do", "else", "elif", "while", "until", "!", "time", "{", "}", "fi", "done"}
# Words that start no command: tests, a loop's list, declarations (their $(...) is still read).
SHELL_NOT_RUN = {"[", "test", "for", "select", "local", "declare", "typeset", "export", "readonly", "function",
                 "esac"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SHELL_FROM_INPUT = re.compile(r"(^|[|;&(\s])(sudo\s+)?(sh|bash|zsh|dash|ksh|python3?|perl|ruby|node)(\s+-[A-Za-z-]*)*\s*$")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
INTERPRETERS = {"python", "python3", "perl", "ruby", "node"}
# An interpreter's options that run code given as text or a module, not a file (in a group of short options too: -uc),
# and those that take the next word as their argument (-W ignore, -I dir, -r lib) or written in the same word (-Idir).
INTERPRETER_CODE = set("ceEm")
INTERPRETER_TAKES = {"-W", "-X", "-I", "-r", "--require"}
# A word that names a script by its suffix: handed to a command the scan does not know, it may be run.
SCRIPT_FILE = re.compile(r"\.(sh|bash|zsh|ksh|py|pl|rb|js|mjs|cjs|lua)\Z")
NETWORK = re.compile(r"\b(urllib|urlopen|requests|http\.client|httpx|aiohttp|pycurl|socket|ftplib|LWP|HTTP::Tiny|"
                     r"Net::HTTP|open-uri|fetch\s*\()")
TERMINAL_RUNNERS = {"xdg-terminal-exec"}
# find's actions that run a command on each file found, up to ";" or to a "+" right after "{}" (grassfield-packages PR
# #7's merge, PR #10's review). Its ";", escaped or quoted on its own (\; ';' ";"), is a word, not the shell's separator:
# prepare() writes it FIND_END.
FIND_RUNS = {"-exec", "-execdir", "-ok", "-okdir"}
# What an action handed the files found ("{}") may be, its first word, no wrapper in front: commands that copy, move,
# remove, change or read a file, and never run it. Anything else (a wrapper, a shell, an interpreter, busybox, the file
# itself) is refused: the files find finds are outside the pinned files.
FIND_HANDS = {"rm", "rmdir", "cp", "mv", "ln", "install", "chmod", "chown", "chgrp", "touch", "stat", "cat", "ls",
              "readlink", "realpath", "basename", "dirname", "sha256sum", "cmp", "grep", "echo", "printf"}
FIND_END = "__find_end__"
LONE_SEMICOLON = re.compile(r"(?<!\S)(?:\\;|';'|\";\")(?!\S)")
DYNAMIC_OMARCHY = re.compile(r"\bomarchy-[a-z0-9-]*\$")
# Programs that run the command after them: (their options that take an argument, their options that take none, how many
# plain arguments come first). An option on neither list is refused (grassfield-packages PR #10's re-review): one that
# takes an argument would otherwise put that argument in the command's place, and a few run a command string of their
# own (env -S, flock -c, runuser -c, sudo -s and -i), which no list holds.
WRAPPERS = {
    "sudo": ({"-u", "--user", "-g", "--group", "-C", "--close-from", "-h", "--host", "-p", "--prompt", "-U",
              "--other-user", "-r", "--role", "-t", "--type", "-D", "--chdir", "-R", "--chroot", "-T",
              "--command-timeout"},
             {"-A", "--askpass", "-b", "--background", "-B", "--bell", "-E", "--preserve-env", "-H", "--set-home", "-k",
              "--reset-timestamp", "-K", "--remove-timestamp", "-l", "--list", "-n", "--non-interactive", "-N",
              "--no-update", "-P", "--preserve-groups", "-S", "--stdin", "-v", "--validate"}, 0),
    "doas": ({"-u", "-C", "-a"}, {"-n", "-L"}, 0),
    "run0": ({"-u", "--user", "-g", "--group", "-D", "--chdir", "--description", "--slice", "--unit", "--property",
              "--nice", "--setenv", "--background", "--machine"}, {"--no-ask-password"}, 0),
    "pkexec": ({"--user"}, {"--keep-cwd", "--disable-internal-agent"}, 0),
    "env": ({"-u", "--unset", "-C", "--chdir", "-a", "--argv0"}, {"-i", "--ignore-environment", "-", "-0", "--null",
                                                                  "-v", "--debug"}, 0),
    "command": (set(), {"-p"}, 0), "builtin": (set(), set(), 0), "exec": ({"-a"}, {"-c", "-l"}, 0),
    "nohup": (set(), set(), 0), "setsid": (set(), {"-c", "--ctty", "-f", "--fork", "-w", "--wait"}, 0),
    "nice": ({"-n", "--adjustment"}, set(), 0), "ionice": ({"-c", "--class", "-n", "--classdata"}, {"-t", "--ignore"}, 0),
    "stdbuf": ({"-i", "--input", "-o", "--output", "-e", "--error"}, set(), 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, {"--foreground", "--preserve-status", "-v", "--verbose"}, 1),
    "flock": ({"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"},
              {"-s", "--shared", "-x", "-e", "--exclusive", "-u", "--unlock", "-n", "--nb", "--nonblock", "-o",
               "--close", "-F", "--no-fork", "--verbose"}, 1),
    "xargs": ({"-I", "--replace", "-n", "--max-args", "-P", "--max-procs", "-d", "--delimiter", "-a", "--arg-file",
               "-L", "--max-lines", "-E", "--eof", "-s", "--max-chars", "--process-slot-var"},
              {"-0", "--null", "-r", "--no-run-if-empty", "-t", "--verbose", "-p", "--interactive", "-x", "--exit",
               "-o", "--open-tty"}, 0),
    "uwsm-app": ({"-s", "-t", "-a", "-u", "-d", "-S"}, {"-T"}, 0),
    "systemd-run": ({"-u", "--unit", "-p", "--property", "--uid", "--gid", "-E", "--setenv", "--description",
                     "--slice", "-M", "--machine", "-H", "--host", "--working-directory", "--nice", "--service-type",
                     "--on-active", "--on-boot", "--on-startup", "--on-unit-active", "--on-unit-inactive",
                     "--on-calendar", "--timer-property", "--path-property", "--socket-property"},
                    {"--user", "--system", "--scope", "--wait", "-q", "--quiet", "--collect", "-G", "--no-block",
                     "--no-ask-password", "-t", "--pty", "-P", "--pipe", "--same-dir", "-d", "-r",
                     "--remain-after-exit", "--send-sighup"}, 0),
    "runuser": ({"-u", "-g", "-G", "--user", "--group", "--supp-group", "-w", "--whitelist-environment"},
                {"-l", "--login", "-m", "-p", "--preserve-environment", "-P", "--pty"}, 0),
    "chroot": ({"--userspec", "--groups"}, {"--skip-chdir"}, 1),
    "unshare": (set(), {"-m", "--mount", "-u", "--uts", "-i", "--ipc", "-n", "--net", "-p", "--pid", "-U", "--user",
                        "-C", "--cgroup", "-T", "--time", "-f", "--fork", "-r", "--map-root-user", "--mount-proc"}, 0),
    "watch": ({"-n", "--interval"}, {"-t", "--no-title", "-b", "--beep", "-e", "--errexit", "-g", "--chgexit", "-c",
                                     "--color", "-x", "--exec", "-p", "--precise"}, 0),
}
PACKAGE_MANAGERS = {"pacman", "yay", "paru"}
AUR_HELPERS = {"yay", "paru"}
DOWNLOADERS = {"curl", "wget", "aria2c", "axel", "rsync", "scp", "sftp", "lftp", "ftp", "makepkg", "flatpak", "snap",
               "mise", "npm", "npx", "pnpm", "yarn", "bun", "bunx", "pipx", "pip", "pip3", "cargo", "rustup", "uv",
               "uvx", "go", "gem"}
GIT_FETCH = {"clone", "pull", "fetch", "submodule"}
# Folders PATH may hold: the system's, Omarchy's own commands (judged by name) and PATH as it was; a program run from a
# system folder by its path is judged by its name too.
PATH_FOLDERS = {"$PATH", "${PATH}", "$OMARCHY_PATH/bin", "${OMARCHY_PATH}/bin", "/usr/local/sbin", "/usr/local/bin",
                "/usr/bin", "/usr/sbin", "/bin", "/sbin"}
SYSTEM_BIN = ("/usr/local/sbin/", "/usr/local/bin/", "/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/")
DECLARATIONS = {"export", "declare", "typeset", "local", "readonly"}
# What an argument may not name, through a command the scan does not know (firejail, strace, bwrap, parallel...): it
# could run it, with options the scan cannot see.
RUN_THROUGH = PACKAGE_MANAGERS | DOWNLOADERS | {"git"}
# Commands that take a command, a package name or a value as data and never run it; Omarchy's package helpers are read
# in the closure, where what they do with the names is judged.
NAMES_AS_DATA = {"echo", "printf", "which", "type", "hash", "whereis", "pgrep", "pidof", "pkill", "killall", "chmod",
                 "chown", "ln", "rm", "cp", "mv", "install", "mkdir", "touch", "cat", "grep", "jq", "head", "tail",
                 "stat", "dirname", "basename", "realpath", "logger", "notify-send", "kill", "wait", "exit", "return",
                 "shift", "set", ":", "omarchy-cmd-present", "omarchy-cmd-missing", "omarchy-pkg-add",
                 "omarchy-pkg-drop", "omarchy-pkg-missing", "omarchy-pkg-present", "omarchy-pkg-aur-add",
                 "omarchy-pkg-aur-accessible", "useradd", "usermod", "chsh"}
# Commands whose arguments the scan reads in its own way (a script, find's actions, a sourced file, gum's command, a
# trap's code): not "a command the scan does not know" below.
READ_ON_THEIR_OWN = SHELLS | INTERPRETERS | {"find", "run-parts", "source", ".", "gum", "trap", "eval"}
# One word that is all a variable or a substitution: what a command the scan does not know is handed, unknown.
WHOLE_RUN_TIME = re.compile(r"^(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\{[^}]*\}|\$[0-9@*]|__subst__|__subst_process__)$")
OMARCHY_NAME = re.compile(r"omarchy-[a-z0-9-]+\Z")


def runs_what_it_is_handed(base):
    """A command the scan does not know (firejail, chrt, strace, systemd-cat, a shell function...): it may run what it is
    handed. Omarchy's own commands are read where they are written; the scan's known commands are read their own way."""
    return base not in RUN_THROUGH | NAMES_AS_DATA | TERMINAL_RUNNERS | READ_ON_THEIR_OWN and \
        not base.startswith("omarchy-")
FUNCTION = re.compile(r"(?m)^\s*(?:function\s+([A-Za-z_][A-Za-z0-9_:-]*)|([A-Za-z_][A-Za-z0-9_:-]*)\s*\(\s*\))")
# What mise does without fetching anything (where, ls, rm...); every other mise command may install.
MISE_LOCAL = {"where", "ls", "list", "current", "which", "rm", "remove", "uninstall", "unuse", "activate", "version",
              "--version"}
PIN = re.compile(r"^file ([0-9a-f]{64}) ([A-Za-z0-9_./-]+)$")
OMARCHY_CALL = re.compile(r"\b(omarchy-[a-z0-9-]+)\b")
# Omarchy's two launcher makers download an icon (data, never run: ADR-0037 S9), not code; read again at each pin bump.
DATA_DOWNLOADS = {"bin/omarchy-webapp-install", "bin/omarchy-tui-install"}
OMARCHY_SOURCE = re.compile(r"\$\{?OMARCHY_PATH\}?/([A-Za-z0-9_./-]+)")
# Omarchy's other names for its own folder, read as ${OMARCHY_PATH} so the closure follows them.
OMARCHY_ROOTS = [
    (re.compile(r"\$\{?OMARCHY_INSTALL\}?"), "${OMARCHY_PATH}/install"),
    (re.compile(r"(?<![\w/])/usr/share/omarchy(?=/)"), "${OMARCHY_PATH}"),
    (re.compile(r"(~|\$\{?HOME\}?)/\.local/share/omarchy(?=/)"), "${OMARCHY_PATH}"),
]
OMARCHY_FILE = re.compile(r"^\$\{?OMARCHY_PATH\}?/([A-Za-z0-9_./-]+)$")


class Problems:
    """Collects every rule a catalog breaks, so one run lists them all."""

    def __init__(self):
        self.items = []

    def add(self, where, message):
        self.items.append(f"{where}: {message}")

    def __bool__(self):
        return bool(self.items)


# --- text and value rules -------------------------------------------------------------------------------------------

def plain_text_problem(value, limit, newlines):
    if not isinstance(value, str):
        return "not a string"
    if value != value.strip() or not value:
        return "empty, or space at an end"
    if len(value) > limit:
        return f"longer than {limit} characters ({len(value)})"
    for ch in value:
        if ch == "\n" and newlines:
            continue
        # Cc: controls; Cf: format characters (bidirectional controls, zero-width characters, the BOM, soft hyphens);
        # Zl, Zp: line and paragraph separators, line breaks a one-line title must not hide.
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") or ch in BIDI:
            return f"control, format or separator character U+{ord(ch):04X}"
    if "<" in value or ">" in value or re.search(r"&(#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);", value):
        return "markup (< > or an &entity;): plain text only"
    if unicodedata.normalize("NFC", value) != value:
        return "not in Unicode NFC form"
    return None


def check_localized(p, where, value, limit, newlines=False, required=True):
    if value is None:
        if required:
            p.add(where, "missing")
        return
    if not isinstance(value, dict):
        p.add(where, 'not an object like {"en": "…", "fr": "…"}')
        return
    if "en" not in value:
        p.add(where, "no English text (en is required)")
    for lang, text in value.items():
        if lang not in LANGS:
            p.add(where, f"language '{lang}' is not one v1 reads (en, fr)")
            continue
        problem = plain_text_problem(text, limit, newlines)
        if problem:
            p.add(f"{where}.{lang}", problem)


def https_problem(url):
    if not isinstance(url, str):
        return "not a string"
    if len(url.encode("utf-8")) > 2048:
        return "longer than 2048 bytes"
    if any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf") for ch in url):
        return "whitespace, control or format character"
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # an invalid port raises
    except ValueError:
        return "not a URL"
    if parts.scheme != "https" or not url.startswith("https://"):
        return "not an https URL"
    if "@" in parts.netloc:
        return "user information in the URL"
    host = parts.hostname or ""
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$", host):
        return "no valid host"
    return None


def check_keys(p, where, obj, allowed):
    for key in obj:
        if key not in allowed:
            p.add(where, f"unknown key '{key}'")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def webapp_name_problem(name):
    # ADR-0037 e.5: printable, 1 to 64 characters, no '/', no control character, not starting with '.'.
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        return "1 to 64 characters"
    if name.startswith(".") or "/" in name or name != name.strip():
        return "starts with '.', holds '/', or has a space at an end"
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") or ch in BIDI for ch in name):
        return "a control or format character"
    return None


# --- the catalog as the Store reads it (ADR-0037 g) -----------------------------------------------------------------

def validate_omarchy(obj, p):
    """The "omarchy" object: required when the catalog has a setup, whose install and remove recipes it must pin, or an
    AUR app, whose two commands and what they call (AUR_PINS) it must pin."""
    sources = [a["source"] for a in obj.get("apps", []) if isinstance(obj.get("apps"), list) and isinstance(a, dict)
               and isinstance(a.get("source"), dict)]
    setups = [s for s in sources if s.get("kind") == "omarchy-setup"]
    aur = any(s.get("kind") == "aur" for s in sources)
    o = obj.get("omarchy")
    if o is None:
        if setups:
            p.add("omarchy", "missing: the Store checks the installed Omarchy against these pins before it runs a setup")
        elif aur:
            p.add("omarchy", "missing: the Store checks the installed Omarchy against these pins before it builds from "
                             "the AUR")
        return
    if not isinstance(o, dict):
        p.add("omarchy", "not an object")
        return
    check_keys(p, "omarchy", o, ("tag", "commit", "files"))
    if not isinstance(o.get("tag"), str) or not OMARCHY_TAG.match(o["tag"]):
        p.add("omarchy", "tag not like v4.0.4")
    if not isinstance(o.get("commit"), str) or not OMARCHY_COMMIT.match(o["commit"]):
        p.add("omarchy", "commit not 40 lowercase hexadecimal digits")
    files = o.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_OMARCHY_FILES:
        p.add("omarchy", f"files: an object of 1 to {MAX_OMARCHY_FILES} pins")
        return
    for path, digest in files.items():
        if len(path) > 255 or not OMARCHY_FILE_PATH.match(path) or not isinstance(digest, str) or not SHA256.match(digest):
            p.add("omarchy", f"files: {path[:80]!r} is not a relative path with a SHA-256")
    for s in setups:
        for recipe in (s.get("install"), s.get("remove")):
            if isinstance(recipe, str) and f"bin/{recipe}" not in files:
                p.add("omarchy", f"files: bin/{recipe} is not pinned, so the Store could not check it")
    for rel in AUR_PINS if aur else ():
        if rel not in files:
            p.add("omarchy", f"files: {rel} is not pinned, so the Store could not check it (an AUR app)")


def validate_catalog(obj, p, channel=None, pins=True):
    """The rules of the built file. The Store applies the same ones; CI refuses any break. pins=False: the "omarchy"
    object is not checked (catalog.py pin, which writes it)."""
    if not isinstance(obj, dict):
        p.add("catalog", "not a JSON object")
        return
    check_keys(p, "catalog", obj, ("version", "channel", "serial", "generated", "sections", "categories", "apps", "omarchy"))
    if obj.get("version") != 1:
        p.add("version", "not 1")
    if obj.get("channel") not in CHANNELS:
        p.add("channel", f"not one of {', '.join(CHANNELS)}")
    elif channel is not None and obj["channel"] != channel:
        p.add("channel", f"'{obj['channel']}', not the channel it is for ('{channel}')")
    serial = obj.get("serial")
    if not is_int(serial) or not 0 < serial < 2 ** 53:
        p.add("serial", "not a positive integer below 2^53")
    if not isinstance(obj.get("generated"), str) or not GENERATED.match(obj["generated"]):
        p.add("generated", "not a UTC time like 2026-10-27T10:00:00Z")

    categories = obj.get("categories")
    category_ids = set()
    if not isinstance(categories, list) or len(categories) > 32:
        p.add("categories", "not a list of at most 32")
        categories = []
    for i, c in enumerate(categories):
        where = f"categories[{i}]"
        if not isinstance(c, dict):
            p.add(where, "not an object")
            continue
        check_keys(p, where, c, ("id", "title", "symbol", "freedesktop"))
        cid = c.get("id")
        if not isinstance(cid, str) or not SECTION_ID.match(cid):
            p.add(where, "id does not match ^[a-z][a-z0-9-]{0,31}$")
        elif cid in category_ids:
            p.add(where, f"id '{cid}' appears twice")
        else:
            category_ids.add(cid)
        check_localized(p, f"{where}.title", c.get("title"), LEN_SECTION_TITLE)
        if not isinstance(c.get("symbol"), str) or not SYMBOL.match(c["symbol"]):
            p.add(where, "symbol missing or not like category-graphics")
        names = c.get("freedesktop")
        if not isinstance(names, list) or not 1 <= len(names) <= 16 or \
                not all(isinstance(n, str) and FREEDESKTOP.match(n) for n in names):
            p.add(where, "freedesktop: 1 to 16 freedesktop category names")

    apps = obj.get("apps")
    app_ids = set()
    if not isinstance(apps, list) or len(apps) > 2000:
        p.add("apps", "not a list of at most 2000")
        apps = []
    for i, a in enumerate(apps):
        where = f"apps[{i}]"
        if isinstance(a, dict) and isinstance(a.get("id"), str):
            where = f"app {a['id']}"
        validate_app(a, p, where, category_ids)
        if isinstance(a, dict) and isinstance(a.get("id"), str):
            if a["id"] in app_ids:
                p.add(where, "id appears twice")
            app_ids.add(a["id"])

    if pins:
        validate_omarchy(obj, p)

    sections = obj.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 8:
        p.add("sections", "not a list of 1 to 8")
        sections = []
    section_ids = set()
    for i, s in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(s, dict):
            p.add(where, "not an object")
            continue
        check_keys(p, where, s, ("id", "title", "symbol", "blocks"))
        sid = s.get("id")
        if not isinstance(sid, str) or not SECTION_ID.match(sid):
            p.add(where, "id does not match ^[a-z][a-z0-9-]{0,31}$")
        elif sid in section_ids:
            p.add(where, f"id '{sid}' appears twice")
        else:
            section_ids.add(sid)
            where = f"section {sid}"
        if i == 0 and sid != "discover":
            p.add(where, "the first section must be 'discover'")
        check_localized(p, f"{where}.title", s.get("title"), LEN_SECTION_TITLE)
        if not isinstance(s.get("symbol"), str) or not SYMBOL.match(s["symbol"]):
            p.add(where, "symbol missing or not like discover")
        blocks = s.get("blocks")
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= 12:
            p.add(where, "blocks: 1 to 12")
            continue
        for j, b in enumerate(blocks):
            validate_block(b, p, f"{where}.blocks[{j}]", app_ids)


def validate_block(b, p, where, app_ids):
    if not isinstance(b, dict):
        p.add(where, "not an object")
        return
    kind = b.get("kind")
    if kind not in BLOCK_KINDS:
        p.add(where, f"kind not one of {', '.join(BLOCK_KINDS)}")
        return
    if kind == "row":
        check_keys(p, where, b, ("kind", "title", "apps"))
        check_localized(p, f"{where}.title", b.get("title"), LEN_TITLE)
        ids = b.get("apps")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 24:
            p.add(where, "apps: 1 to 24 app ids")
            return
        for app in ids:
            if not isinstance(app, str) or app not in app_ids:
                p.add(where, f"app '{app}' is not in apps")
        if len(set(map(str, ids))) != len(ids):
            p.add(where, "an app appears twice")
        return
    check_keys(p, where, b, ("kind", "items"))
    items = b.get("items")
    most = 8 if kind == "hero" else 12
    if not isinstance(items, list) or not 1 <= len(items) <= most:
        p.add(where, f"items: 1 to {most}")
        return
    for k, item in enumerate(items):
        w = f"{where}.items[{k}]"
        if not isinstance(item, dict):
            p.add(w, "not an object")
            continue
        check_keys(p, w, item, ("app", "eyebrow", "title", "text"))
        if not isinstance(item.get("app"), str) or item["app"] not in app_ids:
            p.add(w, f"app '{item.get('app')}' is not in apps")
        check_localized(p, f"{w}.eyebrow", item.get("eyebrow"), LEN_EYEBROW, required=False)
        check_localized(p, f"{w}.title", item.get("title"), LEN_TITLE)
        check_localized(p, f"{w}.text", item.get("text"), LEN_TEXT, newlines=True, required=False)


def validate_app(a, p, where, category_ids):
    if not isinstance(a, dict):
        p.add(where, "not an object")
        return
    check_keys(p, where, a, ("id", "source", "name", "summary", "description", "developer", "license", "homepage",
                             "desktopId", "icon", "categories"))
    if not isinstance(a.get("id"), str) or not APP_ID.match(a["id"]):
        p.add(where, "id does not match ^[A-Za-z0-9._-]{1,255}$")
    validate_source(a.get("source"), p, f"{where}.source")
    kind = a.get("source", {}).get("kind") if isinstance(a.get("source"), dict) else None
    check_localized(p, f"{where}.name", a.get("name"), LEN_TITLE, required=kind == "webapp")
    if kind == "webapp" and isinstance(a.get("name"), dict):
        # Omarchy's installer makes a file of the name (ADR-0037 e.5, S9): every language's name must be one.
        for lang, name in a["name"].items():
            problem = webapp_name_problem(name)
            if problem:
                p.add(f"{where}.name.{lang}", f"not a web app name: {problem}")
    check_localized(p, f"{where}.summary", a.get("summary"), LEN_TEXT, required=False)
    check_localized(p, f"{where}.description", a.get("description"), LEN_DESCRIPTION, newlines=True, required=False)
    check_localized(p, f"{where}.developer", a.get("developer"), LEN_TITLE, required=False)
    if "license" in a and (not isinstance(a["license"], str) or len(a["license"]) > 128 or
                           not LICENSE.match(a["license"])):
        p.add(where, "license is not an SPDX expression or LicenseRef-…")
    if "homepage" in a:
        problem = https_problem(a["homepage"])
        if problem:
            p.add(f"{where}.homepage", problem)
    if "desktopId" in a and (not isinstance(a["desktopId"], str) or not DESKTOP_ID.match(a["desktopId"])):
        p.add(where, "desktopId does not match ^[A-Za-z0-9._-]{1,250}\\.desktop$")
    icon = a.get("icon")
    if icon is not None:
        w = f"{where}.icon"
        if not isinstance(icon, dict):
            p.add(w, "not an object")
        else:
            check_keys(p, w, icon, ("sha256", "bytes", "license", "origin"))
            if not isinstance(icon.get("sha256"), str) or not SHA256.match(icon["sha256"]):
                p.add(w, "sha256 is not 64 lowercase hex digits")
            if not is_int(icon.get("bytes")) or not 0 < icon["bytes"] <= MAX_ICON:
                p.add(w, f"bytes not between 1 and {MAX_ICON}")
            if not isinstance(icon.get("license"), str) or not LICENSE.match(icon["license"]):
                p.add(w, "license is not an SPDX expression or LicenseRef-…")
            problem = https_problem(icon.get("origin"))
            if problem:
                p.add(f"{w}.origin", problem)
    elif kind == "webapp":
        p.add(where, "a web app needs an icon")
    cats = a.get("categories")
    if cats is not None:
        if not isinstance(cats, list) or not 1 <= len(cats) <= 4:
            p.add(where, "categories: 1 to 4 category ids")
        else:
            for c in cats:
                if not isinstance(c, str) or c not in category_ids:
                    p.add(where, f"category '{c}' is not in categories")


def validate_source(s, p, where):
    if not isinstance(s, dict):
        p.add(where, "missing or not an object")
        return
    kind = s.get("kind")
    if kind not in SOURCE_KINDS:
        p.add(where, f"kind not one of {', '.join(SOURCE_KINDS)}")
        return
    if kind == "repo":
        check_keys(p, where, s, ("kind", "repo", "package"))
        if s.get("repo") not in REPOS:
            p.add(where, f"repo not one of {', '.join(REPOS)}")
        if not isinstance(s.get("package"), str) or not PACKAGE.match(s["package"]):
            p.add(where, "package is not a package name")
    elif kind == "aur":
        check_keys(p, where, s, ("kind", "package"))
        if not isinstance(s.get("package"), str) or not PACKAGE.match(s["package"]):
            p.add(where, "package is not a package name")
    elif kind == "omarchy-setup":
        check_keys(p, where, s, ("kind", "install", "args", "remove", "removeArgs", "packages", "changes", "removes"))
        if not isinstance(s.get("install"), str) or not SETUP_INSTALL.match(s["install"]):
            p.add(where, "install does not match ^omarchy-install-[a-z0-9-]+$")
        if not isinstance(s.get("remove"), str) or not SETUP_REMOVE.match(s["remove"]):
            p.add(where, "remove does not match ^omarchy-remove-[a-z0-9-]+$")
        for key in ("args", "removeArgs"):
            args = s.get(key, [])
            if not isinstance(args, list) or len(args) > 4 or \
                    not all(isinstance(x, str) and RECIPE_ARG.match(x) for x in args):
                p.add(where, f"{key}: at most 4, each ^[a-z0-9][a-z0-9.-]{{0,63}}$")
        pkgs = s.get("packages")
        if not isinstance(pkgs, list) or not 1 <= len(pkgs) <= 16 or \
                not all(isinstance(x, str) and PACKAGE.match(x) for x in pkgs):
            p.add(where, "packages: 1 to 16 package names (they say when the setup is installed)")
        check_localized(p, f"{where}.changes", s.get("changes"), LEN_TEXT, newlines=True)
        check_localized(p, f"{where}.removes", s.get("removes"), LEN_TEXT, newlines=True, required=False)
    elif kind == "webapp":
        check_keys(p, where, s, ("kind", "url"))
        problem = https_problem(s.get("url"))
        if problem:
            p.add(f"{where}.url", problem)
    elif kind == "flatpak":
        check_keys(p, where, s, ("kind", "remote", "app"))
        if s.get("remote") != "flathub":
            p.add(where, "remote is not flathub")
        app = s.get("app")
        if not isinstance(app, str) or len(app.encode()) > 255 or not FLATPAK_ID.match(app):
            p.add(where, "app is not a Flatpak app id")


# --- sources --------------------------------------------------------------------------------------------------------

def read_json(path, p):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        p.add(path, f"cannot be read as UTF-8 JSON: {e or type(e).__name__}")
        return None


def no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"key '{key}' appears twice")
        out[key] = value
    return out


def png_size(data):
    """(width, height) of a PNG, or None. Only the signature and IHDR are read."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def load_sources(src, p):
    """The catalog object from catalog/, icons resolved, and the icon files to ship ({sha256: bytes})."""
    categories = read_json(os.path.join(src, "categories.json"), p)
    if isinstance(categories, dict) and set(categories) == {"categories"}:
        categories = categories["categories"]
    else:
        p.add("categories.json", 'not {"categories": [...]}')
        categories = []

    icons, icon_files = {}, {}
    icon_dir = os.path.join(src, "icons")
    for name in sorted(os.listdir(icon_dir)) if os.path.isdir(icon_dir) else []:
        stem, ext = os.path.splitext(name)
        path = os.path.join(icon_dir, name)
        if ext == ".json":
            if not os.path.exists(os.path.join(icon_dir, stem + ".png")):
                p.add(path, "no PNG beside it")
            continue
        if ext != ".png" or not ICON_NAME.match(stem):
            p.add(path, "icons/ holds only <name>.png and <name>.json, names like spotify or hey-mail")
            continue
        with open(path, "rb") as f:
            data = f.read()
        size = png_size(data)
        if size is None:
            p.add(path, "not a PNG")
            continue
        if len(data) > MAX_ICON or max(size) > MAX_ICON_SIDE or min(size) < 1:
            p.add(path, f"{len(data)} bytes, {size[0]}x{size[1]}: at most {MAX_ICON} bytes and {MAX_ICON_SIDE}x{MAX_ICON_SIDE}")
            continue
        meta = read_json(os.path.join(icon_dir, stem + ".json"), p) or {}
        if not isinstance(meta, dict):
            p.add(os.path.join(icon_dir, stem + ".json"), "not an object")
            meta = {}
        check_keys(p, path, meta, ("license", "origin", "review"))
        if meta.get("review") != "needs legal review":
            p.add(path, 'a publisher\'s icon is marked "review": "needs legal review" (owner decision ST10)')
        digest = hashlib.sha256(data).hexdigest()
        icons[stem] = {"sha256": digest, "bytes": len(data), "license": meta.get("license"),
                       "origin": meta.get("origin")}
        icon_files[digest] = data

    apps = []
    app_dir = os.path.join(src, "apps")
    for name in sorted(os.listdir(app_dir)) if os.path.isdir(app_dir) else []:
        path = os.path.join(app_dir, name)
        app = read_json(path, p)
        if not isinstance(app, dict):
            continue
        if name != f"{app.get('id')}.json":
            p.add(path, f"the file must be named after the app's id ({app.get('id')}.json)")
        if "icon" in app:
            ref = app["icon"]
            if not isinstance(ref, str) or ref not in icons:
                p.add(path, f"icon '{ref}' is not in icons/")
                del app["icon"]
            else:
                app["icon"] = dict(icons[ref])
        apps.append(app)

    used = {a["icon"]["sha256"] for a in apps if isinstance(a.get("icon"), dict) and "sha256" in a["icon"]}
    for stem, icon in icons.items():
        if icon["sha256"] not in used:
            p.add(f"icons/{stem}.png", "no app uses it")
    icon_files = {k: v for k, v in icon_files.items() if k in used}

    sections = []
    section_dir = os.path.join(src, "sections")
    for name in sorted(os.listdir(section_dir)) if os.path.isdir(section_dir) else []:
        path = os.path.join(section_dir, name)
        section = read_json(path, p)
        if not isinstance(section, dict):
            continue
        if name != f"{section.get('id')}.json":
            p.add(path, f"the file must be named after the section's id ({section.get('id')}.json)")
        order = section.pop("order", None)
        if not is_int(order):
            p.add(path, '"order" (an integer) is missing')
            order = 0
        sections.append((order, str(section.get("id") or ""), section))
    orders = [o for o, _, _ in sections]
    if len(set(orders)) != len(orders):
        p.add("sections", "two sections have the same order")
    sections = [s for _, _, s in sorted(sections, key=lambda t: (t[0], t[1]))]

    obj = {"version": 1, "channel": "stable", "serial": 1, "generated": "1970-01-01T00:00:01Z",
           "sections": sections, "categories": categories, "apps": apps}
    lock = os.path.join(src, "omarchy.lock")
    if os.path.isfile(lock):
        # The release and the pins, published for the Store (ADR-0037 g): it runs a setup only while every pinned file of
        # the installed Omarchy matches.
        try:
            lines = read_lines(lock)
            obj["omarchy"] = {"tag": next((l.split()[1] for l in lines if l.startswith("tag ")), None),
                              "commit": next((l.split()[1] for l in lines if l.startswith("commit ")), None),
                              "files": dict(sorted(read_pins(lock).items()))}
        except (OSError, ValueError, IndexError) as e:
            p.add("omarchy.lock", f"cannot be read: {e}")
    return obj, icon_files


# --- the system the catalog names (CI, in an Arch container with Omarchy's stable configuration) --------------------

def aur_packages(obj):
    """The package names of the catalog's AUR apps (catalog-facts.sh asks the AUR about them)."""
    apps = obj.get("apps") if isinstance(obj.get("apps"), list) else []
    names = {a["source"]["package"] for a in apps if isinstance(a, dict) and isinstance(a.get("source"), dict)
             and a["source"].get("kind") == "aur" and isinstance(a["source"].get("package"), str)}
    return sorted(n for n in names if PACKAGE.match(n))


def wanted_packages(obj):
    """Every package name a fact is needed for: repo apps and the packages of setups."""
    names = set()
    for a in obj.get("apps", []) if isinstance(obj.get("apps"), list) else []:
        s = a.get("source") if isinstance(a, dict) else None
        if not isinstance(s, dict):
            continue
        if s.get("kind") == "repo" and isinstance(s.get("package"), str):
            names.add(s["package"])
        if s.get("kind") == "omarchy-setup":
            names.update(x for x in s.get("packages", []) if isinstance(x, str))
    return sorted(n for n in names if PACKAGE.match(n))


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip() and not line.startswith("#")]


def omarchy_text(rel, text):
    """A file of Omarchy's with every name of Omarchy's own folder written ${OMARCHY_PATH} (a script's own folder too)."""
    text = SELF_DIR.sub("${OMARCHY_PATH}/" + os.path.dirname(rel), text)
    for pattern, root in OMARCHY_ROOTS:
        text = pattern.sub(root, text)
    return text


def recipe_closure(omarchy, name):
    """The recipe and every Omarchy script or file it calls or sources, transitively: (path, text) pairs."""
    seen, todo, out = set(), [os.path.join("bin", name)], []
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = os.path.join(omarchy, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = omarchy_text(rel, f.read())
        out.append((rel, text))
        for call in OMARCHY_CALL.findall(text):
            if os.path.isfile(os.path.join(omarchy, "bin", call)):
                todo.append(os.path.join("bin", call))
        for sourced in OMARCHY_SOURCE.findall(text):
            if os.path.isfile(os.path.join(omarchy, sourced)):
                todo.append(sourced)
    return out


def simple_commands(code, problems, notes, depth=0):
    """Each simple command of a shell text as its words after the wrappers that run it (the first word a base name).
    problems: what the reading refuses (text it cannot read, code made at run time, a script read from its input);
    notes: what a person reading the file should look at (a command named by a variable it cannot resolve)."""
    out = []
    if depth > 8:
        problems.append("shell nested too deeply to read")
        return out
    subs = []
    try:
        code, bodies = split_heredocs(code)
        tokens = shell_tokens(prepare(code, subs))
    except ValueError as e:
        problems.append(f"cannot be read as shell ({e})")
        return out
    for quoted, body in bodies:
        if not quoted:  # an unquoted heredoc runs its $(...) and `...`
            try:
                prepare(body, subs, heredoc=True)
            except ValueError as e:
                problems.append(f"cannot be read as shell ({e})")
    for inner in subs:
        out += simple_commands(inner, problems, notes, depth + 1)
    literals = literal_assignments(tokens)
    command, mode = [], None
    for token in tokens + [";"]:
        if mode == "redirect":  # a redirection's target: a file, never a command
            mode = None
            continue
        if mode in ("array", "case", "arith", "test"):
            end = {"array": (")",), "case": (")", "esac"), "arith": ("))",), "test": ("]]",)}[mode]
            if token in end:
                mode = None
            continue
        if token in REDIRECTS:
            mode = "redirect"
            continue
        lead = [w for w in command if w not in SHELL_KEYWORDS]  # if, while, do, !: what comes after them
        if not lead and token in ("((", "[["):
            mode = "arith" if token == "((" else "test"
            continue
        if token == "(" and command and ASSIGNMENT.match(command[-1]) and command[-1].endswith("="):
            mode = "array"
            continue
        if token in SHELL_OPERATORS:
            if lead and lead[0] == "case":
                mode = "case" if token != ")" else None
            elif command:
                out += read_command(command, literals, problems, notes, depth)
            if token in (";;", ";&", ";;&"):
                mode = "case"
            command = []
            continue
        command.append(token)
    return out


def split_heredocs(code):
    """The code without heredoc bodies, and the bodies: (quoted delimiter, text)."""
    lines, kept, bodies, i = code.split("\n"), [], [], 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for m in HEREDOC.finditer(line):
            quoted, delimiter, strip = bool(m.group(2)), m.group(3), bool(m.group(1))
            body = []
            while i < len(lines) and (lines[i].lstrip("\t") if strip else lines[i]) != delimiter:
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise ValueError(f"heredoc {delimiter} never ends")
            i += 1
            bodies.append((quoted, "\n".join(body)))
            if SHELL_FROM_INPUT.search(line[:m.start()]):
                raise ValueError("a heredoc fed to a shell or an interpreter: code read from its input")
    return "\n".join(kept), bodies


def closing(code, start, depth):
    """The index where `depth` open parentheses close, from start, quotes and escapes respected; ValueError if never."""
    i, quote = start, None
    while i < len(code):
        ch = code[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("a parenthesis never closes")


def prepare(code, subs, heredoc=False):
    """Shell text made easy to split: comments dropped, unquoted line ends as ';', every $(...), `...`, <(...), >(...) and
    $((...)) replaced by a placeholder word, the code inside added to subs (an arithmetic's own $(...) too). In a heredoc
    body only the substitutions count. ValueError when a quote or a parenthesis never closes."""
    code = LONE_SEMICOLON.sub(FIND_END, code)
    out, i, n, quote = [], 0, len(code), None
    while i < n:
        ch = code[i]
        if quote == "'" and not heredoc:
            out.append(ch)
            quote = None if ch == "'" else quote
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append("" if code[i + 1] == "\n" else ch + code[i + 1])  # a line continuation: nothing, as in bash
            i += 2
            continue
        if code.startswith("$((", i):
            end = closing(code, i + 3, 2)
            prepare(code[i + 3:end - 1], subs, heredoc=True)  # $(( ... )): only its substitutions run
            out.append(ARITH)
            i = end + 1
            continue
        if code.startswith("$(", i) or (quote is None and not heredoc and ch in "<>" and code.startswith("(", i + 1)):
            end = closing(code, i + 2, 1)
            subs.append(code[i + 2:end])
            out.append(PROCESS if ch in "<>" else SUBST)
            i = end + 1
            continue
        if ch == "`":
            end = code.find("`", i + 1)
            if end < 0:
                raise ValueError("a ` never closes")
            subs.append(code[i + 1:end])
            out.append(SUBST)
            i = end + 1
            continue
        if heredoc:
            i += 1
            continue
        if quote == '"':
            out.append(ch)
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1][-1:] in " \t\n;&|()"):
            while i < n and code[i] != "\n":
                i += 1
            continue
        elif ch == "\n":
            out.append(" ; ")
        else:
            out.append(ch)
        i += 1
    if quote and not heredoc:
        raise ValueError("a quote never closes")
    return "".join(out)


def shell_tokens(text):
    """Words and operators (&&, ||, ;;, <<, >&, (, ) ...): shlex's punctuation runs cut into the shell's own operators."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=SHELL_PUNCT)
    lexer.commenters = ""
    lexer.whitespace_split = True
    out = []
    for token in lexer:
        if token and set(token) <= set(SHELL_PUNCT):
            while token:
                op = next((o for o in SHELL_OPS_BY_LENGTH if token.startswith(o)), token[0])
                out.append(op)
                token = token[len(op):]
        else:
            out.append(token)
    return out


def literal_assignments(tokens):
    """{name: values} of the variables a file only ever sets to literal text (pm=pacman); None for one it computes."""
    seen = {}
    for t in tokens:
        m = ASSIGNMENT.match(t)
        if m and "[" not in t.split("=", 1)[0]:
            name, value = t.split("=", 1)
            name = name.rstrip("+")
            literal = value and not any(c in value for c in "$`") and PLACEHOLDER not in value
            if name in seen and seen[name] is None:
                continue
            seen[name] = (seen.get(name) or set()) | {value} if literal else None
    return seen


def path_problems(word):
    """A PATH assignment's folders the pins do not cover (an empty entry is the current folder)."""
    m = re.match(r"^PATH\+?=(.*)$", word)
    if not m:
        return []
    return [f"PATH set to a folder outside the pinned files ({entry or 'the current folder'})"
            for entry in m.group(1).split(":") if entry.rstrip("/") not in PATH_FOLDERS or not entry]


def run_time_name(word, literals):
    """The literal values of a command word that is one variable set only to literal text, else None."""
    m = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", word)
    return literals.get(m.group(1)) if m else None


def after_wrapper(words, problems):
    """The words after the wrapper words[0] and its options (WRAPPERS): the command it runs; None, with the problem, when
    an option is on neither of its lists (it could take the command's place, or run a command string of its own)."""
    wrapper = os.path.basename(words[0])
    takes, flags, plain = WRAPPERS[wrapper]
    words = words[1:]
    while words:
        word = words[0]
        if word == "--":
            return words[1:]
        if word.startswith("-") and word != "-" and "=" in word and word.split("=", 1)[0] in takes:
            words = words[1:]  # --unit=x
        elif word in takes:
            words = words[2:]
        elif word in flags or (re.fullmatch(r"-[A-Za-z0-9]{2,}", word) and all("-" + c in flags for c in word[1:])):
            words = words[1:]  # -n, or -nl: flags together
        elif word.startswith("-"):
            problems.append(f"{wrapper} {word}: an option the scan does not know (it may take an argument, which would "
                            "stand for the command, or run a command of its own)")
            return None
        elif ASSIGNMENT.match(word):
            problems.extend(path_problems(words[0]))  # env PATH=...
            words = words[1:]
        elif plain:
            plain, words = plain - 1, words[1:]
        else:
            break
    return words


def read_command(words, literals, problems, notes, depth):
    """The commands one simple command runs: itself after its wrappers, and what it hands on."""
    out = []
    while words:
        base = os.path.basename(words[0])
        if words[0] in SHELL_KEYWORDS or ASSIGNMENT.match(words[0]):
            problems.extend(path_problems(words[0]))
            words = words[1:]
        elif words[0] in SHELL_NOT_RUN:
            if words[0] in DECLARATIONS:
                for word in words[1:]:
                    problems.extend(path_problems(word))  # export PATH=...
            return out  # a test, a loop's list, a declaration: words, not a command (their $(...) are read)
        elif base in WRAPPERS:
            if base == "command" and len(words) > 1 and words[1] in ("-v", "-V"):
                return out  # command -v NAME: is NAME there, nothing run
            words = after_wrapper(words, problems)
            if words is None:
                return out
        else:
            break
    if not words:
        return out
    cmd = words[0]
    m = OMARCHY_FILE.match(cmd)
    if m and m.group(1).startswith("bin/"):
        cmd = os.path.basename(m.group(1))  # "$OMARCHY_PATH/bin/omarchy-x": that command
    elif m:
        out.append(words)  # "$OMARCHY_PATH/install/x.sh": a file of Omarchy's, judged against the pins (outside_closure)
        return out
    if PLACEHOLDER in cmd:
        problems.append("a command made at run time by a substitution")
        return out
    if DYNAMIC_OMARCHY.search(cmd):
        problems.append(f"an Omarchy command named at run time ({cmd})")
        return out
    if "$" in cmd:
        values = run_time_name(cmd, literals)
        if values:
            for value in sorted(values):
                out += read_command([value] + words[1:], literals, problems, notes, depth)
        else:
            notes.append(f"a command named at run time ({cmd}): read what it can be")
            out.append(words)  # a path made at run time names a file outside the pins (outside_closure)
        return out
    if "/" in cmd and not cmd.startswith(SYSTEM_BIN):
        out.append(words)  # ./x.sh, /tmp/x: a file, not a program found by name (outside_closure)
        return out
    words = [os.path.basename(cmd)] + words[1:]
    base, args = words[0], words[1:]
    reads_on = base == "gum" and "--" in args  # gum ... -- CMD: CMD is read below
    if base not in RUN_THROUGH | NAMES_AS_DATA | TERMINAL_RUNNERS | {"trap", "eval"} and not reads_on and \
            not base.startswith("omarchy-launch-"):
        for arg in args:
            values = run_time_name(arg, literals) if "$" in arg else None
            if values is None:
                last = os.path.basename(arg)
                values = None if "$" in last or "`" in last or PLACEHOLDER in last else {last}
            if values is None:
                # Omarchy's commands and the file's own functions are read where they are written.
                if WHOLE_RUN_TIME.match(arg) and not base.startswith("omarchy-"):
                    shown = re.sub(r"__(subst|subst_process)__", "$(...)", arg)
                    notes.append(f"{base} is handed {shown}, known only at run time: read what it can be")
                continue
            for value in sorted(v for v in values if os.path.basename(v) in RUN_THROUGH):
                problems.append(f"{base} is handed {value} ({arg}): a package manager or downloader it may run")
    if runs_what_it_is_handed(base):
        # chrt -f 1 bash x.sh, firejail python3 -c '...': a shell or an interpreter, by its name or a system folder's path,
        # with words after it, runs them; what it runs is read as a command (its script judged against the pins).
        for k, arg in enumerate(args[:-1]):
            if os.path.basename(arg) in SHELLS | INTERPRETERS and ("/" not in arg or arg.startswith(SYSTEM_BIN)):
                out += read_command(args[k:], literals, problems, notes, depth + 1)
                break
    if base == "eval":
        problems.append("eval: code made at run time")
    elif base in SHELLS:
        how, operand = shell_operand(args)
        if how == "c" and operand is not None:
            out += simple_commands(operand, problems, notes, depth + 1)
        elif how == "input" or (how == "file" and PLACEHOLDER in operand):
            problems.append(f"{base} runs a script from its input or a substitution (a pipe, a redirection, <(...))")
    elif base in INTERPRETERS:
        for flag in ("-c", "-e"):
            if flag in args and args.index(flag) + 1 < len(args) and NETWORK.search(args[args.index(flag) + 1]):
                words = ["curl"]  # a download written in the interpreter's own language
        if "-m" in args and args.index("-m") + 1 < len(args) and args[args.index("-m") + 1] in ("pip", "ensurepip"):
            words = ["curl"]
        if not [a for a in args if not a.startswith("-")] and "-c" not in args and "-e" not in args:
            problems.append(f"{base} runs code from its input (a pipe or a redirection)")
    elif base in ("source", ".") and (not args or PLACEHOLDER in args[0]):
        problems.append(f"{base} of code made at run time")
    elif base == "gum" and "--" in args:
        out += read_command(args[args.index("--") + 1:], literals, problems, notes, depth + 1)  # gum spin ... -- CMD
    elif base == "trap" and args and not args[0].startswith("-"):
        out += simple_commands(args[0], problems, notes, depth + 1)  # run later, when the signal comes
    elif base.startswith("omarchy-launch-") or base in TERMINAL_RUNNERS:
        command = [a for a in args if not a.startswith("-")]
        if len(command) == 1 and any(ch.isspace() for ch in command[0]):
            out += simple_commands(command[0], problems, notes, depth + 1)  # a terminal launcher's command line
        elif command:
            out += read_command(command, literals, problems, notes, depth + 1)
    elif base == "find":
        # find ... -exec CMD ... ; (or {} +), -execdir, -ok, -okdir: CMD runs on each file found, read as a command. A CMD
        # handed the files found ({}) is, after its wrappers, one of FIND_HANDS, else refused: the files themselves are
        # outside the pinned files. A "+" ends the action only right after "{}" (find's own rule).
        i = 0
        while i < len(args):
            if args[i] not in FIND_RUNS:
                i += 1
                continue
            j = i + 1
            while j < len(args) and not (args[j] == FIND_END or (args[j] == "+" and args[j - 1] == "{}")):
                j += 1
            run = args[i + 1:j]
            # Handed the files found, the action runs no wrapper (Omarchy's own find lines use none): its first word is
            # one of FIND_HANDS, else it is refused.
            if any("{}" in word for word in run) and os.path.basename(run[0]) not in FIND_HANDS:
                problems.append(f"find {args[i]} runs the files it finds: they are outside the pinned files")
            if run and "{}" not in run[0]:
                out += read_command(run, literals, problems, notes, depth + 1)  # what it runs, judged as any command
            i = j + 1
    elif base == "run-parts" and not (len(args) == 2 and args[0] in ("--list", "--test") and not args[1].startswith("-")):
        # Only a listing of a folder's files, or what would run: run-parts runs every file of a folder, outside the pins.
        problems.append("run-parts runs every file of a folder: they are outside the pinned files")
    out.append(words)
    return out


def shell_operand(args):
    """How a shell runs its code: ("c", the command text after -c, or None), ("file", the script it runs) or
    ("input", None) when it reads it from its input (-s, "-", or no operand)."""
    text, i = False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
        elif a.startswith("--"):
            i += 1
        elif a[:1] in ("-", "+") and len(a) > 1:
            if "s" in a[1:]:
                return "input", None
            text = text or "c" in a[1:]
            i += 1
        else:
            break
    if i >= len(args):
        return ("c", None) if text else ("input", None)
    if text:
        return "c", args[i]
    return ("input", None) if args[i] == "-" else ("file", args[i])


def interpreter_operand(args):
    """The script file an interpreter runs, or None when it runs code given as text (-c, -e), a module (-m) or its
    input (no operand, or "-")."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in INTERPRETER_TAKES:
            i += 2
        elif a[:2] in INTERPRETER_TAKES:
            i += 1  # -Idir, -Wignore: the argument in the same word
        elif a in ("--eval", "--print", "--module"):
            return None
        elif a.startswith("--"):
            i += 1
        elif a.startswith("-") and len(a) > 1:
            if set(a[1:]) & INTERPRETER_CODE:
                return None
            i += 1
        else:
            break
    return args[i] if i < len(args) and args[i] != "-" else None


def aur_names(names, repo):
    """Names an AUR install would build: those no repository serves, or that are known only at run time."""
    built = []
    for name in names:
        if "$" in name or "`" in name or not PACKAGE.match(name):
            built.append(f"{name} (known only at run time)")
        elif repo is not None and name not in repo:
            built.append(name)
    return built


def abbreviates(option, *names):
    """--ref, --sysu: pacman takes any unambiguous start of a long option."""
    return option.startswith("--") and len(option) >= 5 and any(n.startswith(option[2:]) for n in names)


def command_findings(code, repo=None, functions=()):
    """(syncs, downloads, AUR names built, problems, notes) of a shell text, read command by command. functions: shell
    functions defined elsewhere in the closure; a function's own body is read where it is written (a function that runs
    its arguments gets its note there), so what a call hands it is not noted again."""
    sync, download, built, problems, notes = False, False, [], [], []
    for words in simple_commands(code, problems, notes):
        cmd, args = words[0], words[1:]
        short = [a for a in args if a.startswith("-") and not a.startswith("--") and len(a) > 1]
        if cmd in PACKAGE_MANAGERS:
            if any("y" in a[1:] for a in short) or any(abbreviates(a, "refresh", "sysupgrade") for a in args):
                sync = True
            ops = [a for a in args if a.startswith("-") and not a.startswith("--")]
            run_time = [a for a in args if "$" in a or "`" in a or PLACEHOLDER in a]
            if any(a.startswith("-") for a in run_time) or (not ops and run_time):
                problems.append(f"{cmd}'s options known only at run time")
            elif any(PLACEHOLDER in a for a in run_time):
                problems.append(f"{cmd}'s arguments made by a substitution: they could be options")
            elif any("[@]" in a or "[*]" in a or a in ("$@", "$*") for a in run_time):
                notes.append(f"{cmd}'s arguments from an array or the script's own arguments: read what they can be")
            for a in run_time:
                if re.fullmatch(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", a):
                    notes.append(f"{cmd}'s argument from a variable ({a}): it could be an option (-y); read what it holds")
            if (ops and ops[0].startswith("-U")) or any(abbreviates(a, "upgrade") for a in args):
                problems.append(f"{cmd} -U: a package file from outside the repositories")
        if cmd in AUR_HELPERS:
            ops = [a for a in args if not a.startswith("--")]
            if not ops or not re.match(r"^-[SRQGPYDTUFBWVh]", ops[0]):
                sync = True  # no operation: -Syu; a term alone: an interactive search and AUR install
            if any(re.match(r"^-[A-Za-z]*[GB]", a) for a in short) or \
                    any(abbreviates(a, "getpkgbuild", "build") for a in args):
                download = True
            if ops and ops[0].startswith("-S") and not set(ops[0][2:]) & set("silgpc"):
                built += aur_names([a for a in args if not a.startswith("-")], repo)
        if cmd == "omarchy-pkg-aur-add":
            built += aur_names([a for a in args if not a.startswith("-")], repo)
        if cmd == "git" and GIT_FETCH & set(args):
            download = True
        if cmd in DOWNLOADERS and not (cmd == "mise" and args and args[0] in MISE_LOCAL):
            download = True
    if DYNAMIC_OMARCHY.search(code):
        problems.append("an Omarchy command named at run time")
    functions = set(functions) | {a or b for a, b in FUNCTION.findall(code)}
    notes = [n for n in notes if n.split(" is handed ", 1)[0] not in functions]
    return sync, download, built, problems, notes


def outside_closure(code, pinned, omarchy=None, notes=None):
    """An Omarchy command, or a file sourced or run, that the closure did not follow (so neither pinned nor scanned).
    omarchy: the checkout, to tell one of its folders from a file it lacks; notes: a list for what the person should
    look at, when given."""
    def is_pinned(word):
        m = OMARCHY_FILE.match(word)
        return m is not None and m.group(1) in pinned

    found = []
    for words in simple_commands(code, [], []):
        cmd, args = words[0], words[1:]
        if cmd.startswith("omarchy-") and f"bin/{cmd}" not in pinned:
            found.append(f"an Omarchy command outside the pinned files ({cmd})")
        if cmd in ("source", ".") and args and not is_pinned(args[0]):
            found.append(f"sources a file outside the pinned files ({args[0]})")
        if cmd in SHELLS:
            how, script = shell_operand(args)
            if how == "file" and PLACEHOLDER not in script and not is_pinned(script):
                found.append(f"{cmd} runs a script outside the pinned files ({script})")
        if cmd in INTERPRETERS:
            script = interpreter_operand(args)
            if script is not None and PLACEHOLDER not in script and not is_pinned(script):
                found.append(f"{cmd} runs a script outside the pinned files ({script})")
        if "/" in cmd and not is_pinned(cmd):  # a path made at run time, or a file of Omarchy's the closure lacks
            found.append(f"runs a file outside the pinned files ({cmd})")
        if not runs_what_it_is_handed(cmd):
            continue
        # A command the scan does not know may run what it is handed (grassfield #34's merge note): a file of Omarchy's
        # the closure did not pin (one the release lacks), an Omarchy command the release lacks, or a script outside the
        # pins is refused; one of Omarchy's folders (quickshell -p "$OMARCHY_PATH/shell") is a note: its files are not
        # pinned. Its other words (a path in the home folder, a device) are data the scan cannot tell from a program.
        for word in args:
            m = OMARCHY_FILE.match(word)
            if m and m.group(1) in pinned:
                continue
            if m and omarchy is not None and os.path.isdir(os.path.join(omarchy, m.group(1))):
                if notes is not None:
                    notes.append(f"{cmd} is handed Omarchy's folder {m.group(1).rstrip('/')}: its files are not pinned; "
                                 "read what it does with them")
            elif m:
                found.append(f"{cmd} is handed a file outside the pinned files ({word}): it may run it")
            elif OMARCHY_NAME.match(word) and f"bin/{word}" not in pinned:
                found.append(f"{cmd} is handed an Omarchy command outside the pinned files ({word}): it may run it")
            elif SCRIPT_FILE.search(word) and PLACEHOLDER not in word:
                found.append(f"{cmd} is handed a script outside the pinned files ({word}): it may run it")
    return found


def is_shell(rel, text):
    first = text.split("\n", 1)[0]
    return rel.endswith(".sh") or (first.startswith("#!") and re.search(r"\b(ba|z|da|k)?sh\b", first) is not None)


def recipe_problems(omarchy, name, args, repo=None, notes=None):
    """What the pattern scan refuses in a recipe and everything it calls or sources (the second line behind the pins,
    run at pin time to help the person who reads the files). repo: the package names Omarchy's stable mirror serves
    (None in tests that have no facts). notes: a list for what the person should look at, when given."""
    path = os.path.join(omarchy, "bin", name)
    if not os.path.isfile(path):
        return [f"{name} is not in the pinned Omarchy release"]
    problems = []
    closure = recipe_closure(omarchy, name)
    pinned = {rel for rel, _ in closure}
    functions = {a or b for rel, text in closure if is_shell(rel, text) for a, b in FUNCTION.findall(text)}
    for rel, text in closure:
        if not is_shell(rel, text):
            continue  # a data or QML file: pinned, never run as shell
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        plain = code.replace("\\\n", "").replace('"', "").replace("'", "")
        sync, download, built, other, seen = command_findings(code, repo, functions)
        outside = outside_closure(code, pinned, omarchy, seen)
        if notes is not None:
            notes += [f"{rel}: {note}" for note in sorted(set(seen))]
        if sync or SYNC.search(plain):
            problems.append(f"{name} syncs pacman's databases (through {rel}): a partial upgrade (ADR-0037 e.4)")
        if (download or DOWNLOAD.search(plain)) and rel not in DATA_DOWNLOADS:
            problems.append(f"{name} downloads outside pacman (through {rel}): not offered (ADR-0037 a)")
        # omarchy-pkg-aur-add's own yay -S "$@" is judged where it is called, with the names it is given.
        if rel == "bin/omarchy-pkg-aur-add":
            built = []
        if built:
            problems.append(f"{name} builds from the AUR (through {rel}): {', '.join(sorted(set(built)))} (ADR-0037 a)")
        for problem in sorted(set(other) | set(outside)):
            problems.append(f"{name} cannot be judged (through {rel}): {problem}")
    with open(path, encoding="utf-8", errors="replace") as f:
        own = f.read()
    for arg in args:
        if not re.search(rf"^\s*(\S+\|)*{re.escape(arg)}(\|\S+)*\)", own, re.M):
            problems.append(f"{name} has no case for '{arg}'")
    return problems

# --- pins: every Omarchy file the catalog's setups run or read (ADR-0037 g) -----------------------------------------------

# The AUR's two commands (ADR-0037 b.2, SD21): the Store installs and removes an AUR package only through Omarchy's
# own omarchy-pkg-aur-add and omarchy-pkg-drop, in Omarchy's terminal, and only while the catalog pins them and the
# installed files match. They are scanned and pinned always, whether or not the catalog lists an AUR app: an AUR search
# result the user opens takes the same path.
AUR_COMMANDS = ("omarchy-pkg-aur-add", "omarchy-pkg-drop")
# What the Store requires pinned before an AUR operation (grassfield's requiredPins): the two commands, and the
# omarchy-pkg-missing that omarchy-pkg-aur-add calls first (in their closure, so pin writes it).
AUR_PINS = ("bin/omarchy-pkg-aur-add", "bin/omarchy-pkg-missing", "bin/omarchy-pkg-drop")


def setup_recipes(obj):
    """(recipe, args) of every well-formed omarchy-setup of the catalog: its install and its remove recipes."""
    out = []
    for a in obj.get("apps", []) if isinstance(obj.get("apps"), list) else []:
        s = a.get("source") if isinstance(a, dict) else None
        q = Problems()
        validate_source(s, q, "app")
        if q or s.get("kind") != "omarchy-setup":
            continue
        out.append((s["install"], s.get("args", [])))
        out.append((s["remove"], s.get("removeArgs", [])))
    return out


def pinned_recipes(obj):
    """(command, args) of everything the pins cover: the setups' recipes, then the AUR's two commands (no case to
    check)."""
    return setup_recipes(obj) + [(command, []) for command in AUR_COMMANDS]


def pin_files(obj, omarchy):
    """{path relative to the Omarchy checkout: sha256} of every file the setups' recipes and the AUR's two commands run
    or read, transitively."""
    files = {}
    for recipe, _ in pinned_recipes(obj):
        for rel, _ in recipe_closure(omarchy, recipe):
            files[rel] = sha256_of(os.path.join(omarchy, rel))
    return files


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_pins(lock):
    """{path: sha256} of the lock's file lines; a file line that does not parse raises ValueError (fail closed)."""
    pins = {}
    for line in read_lines(lock):
        if line.startswith("file"):
            m = PIN.match(line)
            if not m or m.group(2) in pins:
                raise ValueError(f"{os.path.basename(lock)}: not a pin, or a path pinned twice: {line[:80]!r}")
            pins[m.group(2)] = m.group(1)
    return pins


def pin_problems(obj, omarchy, pins, p):
    """A file that differs from its pin, is missing or is not pinned: refused until a person reads it (catalog.py pin)."""
    current = pin_files(obj, omarchy)
    for rel, digest in sorted(current.items()):
        if rel not in pins:
            p.add(f"omarchy {rel}", "run or read by a setup or the AUR's commands, not pinned: read it, then "
                                    "catalog.py pin")
        elif pins[rel] != digest:
            p.add(f"omarchy {rel}", "differs from its pin in omarchy.lock: read the change, then catalog.py pin")
    for rel in sorted(set(pins) - set(current)):
        if not os.path.isfile(os.path.join(omarchy, rel)):
            p.add(f"omarchy {rel}", "pinned but missing from the Omarchy checkout")
        else:
            p.add(f"omarchy {rel}", "pinned but no longer run or read by any setup or the AUR's commands: "
                                    "catalog.py pin removes it")


def pin(src, omarchy, facts, p):
    """Writes the pins of catalog/omarchy.lock for the checkout, after the scan finds nothing; returns the changes."""
    lock = os.path.join(src, "omarchy.lock")
    commit = next((line.split()[1] for line in read_lines(lock) if line.startswith("commit ")), None)
    head = None
    if os.path.isdir(os.path.join(omarchy, ".git")):
        head = subprocess.run(["git", "-C", omarchy, "rev-parse", "HEAD"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL).stdout.strip()
    elif os.path.isfile(os.path.join(omarchy, ".commit")):
        with open(os.path.join(omarchy, ".commit"), encoding="utf-8") as f:
            head = f.read().strip()  # a checkout without git: catalog-facts.sh reads the same file
    if not commit or head != commit:
        p.add(omarchy, f"the checkout is at {head or 'an unknown commit (no .git, no .commit)'}, omarchy.lock names "
                       f"{commit}: pins are written only for the commit the lock names")
        return []
    obj, _ = load_sources(src, p)
    obj.pop("omarchy", None)  # what this command writes: the pins as they are now are not a rule here
    validate_catalog(obj, p, pins=False)
    repo = None
    if facts:
        repo = {line.split()[1] for line in read_lines(os.path.join(facts, "repo-packages.txt"))}
    notes = []
    for recipe, args in pinned_recipes(obj):
        for problem in recipe_problems(omarchy, recipe, args, repo, notes):
            p.add(f"recipe {recipe}", problem)
    if p:
        return []
    for note in sorted(set(notes)):
        print(f"read: {note}")
    old = read_pins(lock)
    new = pin_files(obj, omarchy)
    changes = [f"new      {rel}" for rel in sorted(set(new) - set(old))] + \
              [f"changed  {rel}" for rel in sorted(rel for rel in set(new) & set(old) if new[rel] != old[rel])] + \
              [f"removed  {rel}" for rel in sorted(set(old) - set(new))]
    with open(lock, encoding="utf-8") as f:
        kept = [line.rstrip("\n") for line in f if not line.startswith("file ")]
    while kept and not kept[-1].strip():
        kept.pop()
    data = "\n".join(kept + [""] + [f"file {new[rel]} {rel}" for rel in sorted(new)]) + "\n"
    write_file(lock, data.encode("utf-8"))
    return changes


def check_env(obj, facts, omarchy, p, pins=None):
    """pins: {path: sha256} from omarchy.lock (catalog.py check-env reads it); every pinned file is checked first."""
    if pins is not None:
        pin_problems(obj, omarchy, pins, p)
    try:
        repo = {}
        for line in read_lines(os.path.join(facts, "repo-packages.txt")):
            r, name = line.split()[:2]
            repo.setdefault(name, set()).add(r)
        entries = {}
        for line in read_lines(os.path.join(facts, "app-entries.txt")):
            name, path = line.split(None, 1)
            entries.setdefault(name, set()).add(path)
        appstream = {}
        for line in read_lines(os.path.join(facts, "appstream-ids.txt")):
            name, cid, ctype = line.split()[:3]
            if ctype == "desktop-application":
                appstream.setdefault(name, set()).add(cid)
        flathub_path = os.path.join(facts, "flathub-ids.txt")
        flathub = set(read_lines(flathub_path)) if os.path.exists(flathub_path) else None
        aur_path = os.path.join(facts, "aur-packages.txt")
        aur = {line.split()[0] for line in read_lines(aur_path)} if os.path.exists(aur_path) else None
    except (OSError, ValueError) as e:
        p.add(facts, f"facts cannot be read: {e}")
        return
    # The AUR's two commands, scanned as the setups' recipes are (pin writes their pins after the same scan).
    for command in AUR_COMMANDS:
        for problem in recipe_problems(omarchy, command, [], set(repo)):
            p.add(f"AUR command {command}", problem)
    for a in obj.get("apps", []) if isinstance(obj.get("apps"), list) else []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not isinstance(a.get("source"), dict):
            continue  # validate reports it
        s, where = a["source"], f"app {a['id']}"
        q = Problems()
        validate_source(s, q, where)
        if q:
            continue  # validate reports it; the facts are checked against well-formed sources only
        kind = s.get("kind")
        if kind == "repo":
            pkg = s.get("package")
            if s.get("repo") not in repo.get(pkg, ()):
                p.add(where, f"[{s.get('repo')}] has no package {pkg} on Omarchy's stable mirror")
            desktop = sorted(os.path.basename(x) for x in entries.get(pkg, ())
                             if re.match(r"^/?usr/share/applications/[^/]+\.desktop$", x))
            if not desktop:
                p.add(where, f"{pkg} owns no application entry (/usr/share/applications/*.desktop; SD1)")
            if "desktopId" in a and a["desktopId"] not in desktop:
                p.add(where, f"desktopId {a['desktopId']} is not one of {pkg}'s entries ({', '.join(desktop) or 'none'})")
            appstream_id_problem(p, where, a, pkg, appstream)
        elif kind == "omarchy-setup":
            for problem in recipe_problems(omarchy, s.get("install", ""), s.get("args", []), set(repo)):
                p.add(where, problem)
            for problem in recipe_problems(omarchy, s.get("remove", ""), s.get("removeArgs", []), set(repo)):
                p.add(where, problem)
            for pkg in s.get("packages", []):
                if pkg not in repo:
                    p.add(where, f"package {pkg} is on no repository of Omarchy's stable mirror")
            if s.get("packages"):
                appstream_id_problem(p, where, a, s["packages"][0], appstream)
        elif kind == "aur":
            # yay would install a repository's package of that name (the Store refuses it too); the AUR must know it.
            pkg = s.get("package")
            if pkg in repo:
                p.add(where, f"[{', '.join(sorted(repo[pkg]))}] has {pkg}: yay would install the repository's; "
                             "list it as a repo app")
            if aur is None:
                p.add(where, "no AUR facts (aur-packages.txt) to check it against")
            elif pkg not in aur:
                p.add(where, f"the AUR has no package {pkg}")
        elif kind == "flatpak":
            if flathub is None:
                p.add(where, "no Flathub facts (flathub-ids.txt) to check it against")
            elif s.get("app") not in flathub:
                p.add(where, f"Flathub's AppStream has no app {s.get('app')}")
        elif kind == "webapp":
            pass  # its URL is checked by validate (https); no fact can say more without visiting it


def appstream_id_problem(p, where, app, pkg, appstream):
    # The Store overlays our texts on AppStream's by id, exactly as AppStream spells it (some end in .desktop).
    ids = appstream.get(pkg)
    if ids and app.get("id") not in ids:
        p.add(where, f"AppStream knows {pkg} as {', '.join(sorted(ids))}: use that id, so our texts overlay it")


# --- build, sign, verify --------------------------------------------------------------------------------------------

def build(src, channel, serial, out, p):
    obj, icon_files = load_sources(src, p)
    obj["channel"], obj["serial"] = channel, serial
    obj["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(serial))
    obj["apps"].sort(key=lambda a: str(a.get("id")))
    validate_catalog(obj, p, channel)
    if p:
        return None
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_CATALOG:
        p.add(CATALOG_NAME, f"{len(data)} bytes, more than {MAX_CATALOG}")
        return None
    os.makedirs(os.path.join(out, "catalog"), exist_ok=True)
    write_file(os.path.join(out, CATALOG_NAME), data)
    for digest, icon in sorted(icon_files.items()):
        write_file(os.path.join(out, "catalog", f"{digest}.png"), icon)
    return os.path.join(out, CATALOG_NAME)


def write_file(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_fingerprints(path):
    """The fingerprints of a keyring list (grassfield-trusted: FPR:4:, grassfield-revoked: FPR), upper case, spaces
    around them ignored. Any other line (a grouped fingerprint, a 0x prefix, a trailing comment) raises ValueError: a list
    that cannot be read whole is not used, so a revoked entry written another way never leaves its key trusted."""
    out = set()
    for line in read_lines(path):
        fpr, _, rest = line.partition(":")
        fpr = fpr.strip().upper()
        if not FINGERPRINT.match(fpr) or not re.fullmatch(r"(\d+:)?\s*", rest):
            raise ValueError(f"{os.path.basename(path)}: a line is not a fingerprint: {line[:60]!r}")
        out.add(fpr)
    return out


def child_env(homedir):
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GNUPGHOME": homedir}


def sign(path, homedir, key):
    if not FINGERPRINT.match(key):
        raise SystemExit("sign: --key must be the signing key's 40-hex-digit fingerprint")
    sig = path + ".sig"
    if os.path.exists(sig):
        os.unlink(sig)
    subprocess.run(["gpg", "--batch", "--no-tty", "--yes", "--homedir", homedir, "--local-user", key + "!",
                    "--detach-sign", "--output", sig, path], check=True, stdin=subprocess.DEVNULL,
                   env=child_env(homedir))
    return sig


def signature_problem(path, keyring_dir):
    """None when path + ".sig" is a good signature by one key that grassfield-trusted lists and grassfield-revoked does
    not (ADR-0033 d.8, ADR-0037 g), checked by gpgv against the keyring folder; else why not."""
    if not keyring_dir:
        return "no keyring folder to check its signature with"
    keyring = os.path.join(keyring_dir, "grassfield.gpg")
    try:
        trusted = read_fingerprints(os.path.join(keyring_dir, "grassfield-trusted"))
        revoked_path = os.path.join(keyring_dir, "grassfield-revoked")
        revoked = read_fingerprints(revoked_path) if os.path.exists(revoked_path) else set()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f"keyring files cannot be read: {e}"
    if not trusted or not os.path.isfile(keyring) or not os.path.getsize(keyring):
        return "no trusted key: nothing signed is used"
    if not os.path.isfile(path) or not os.path.isfile(path + ".sig"):
        return "missing, or its .sig is"
    with tempfile.TemporaryDirectory() as home:
        run = subprocess.run(["gpgv", "--homedir", home, "--keyring", keyring, "--status-fd", "1",
                              path + ".sig", path], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             env=child_env(home))
    signers, plaintext = set(), False
    for line in run.stdout.splitlines():
        fields = line.split()
        plaintext = plaintext or fields[:2] == ["[GNUPG:]", "PLAINTEXT"]
        if fields[:2] == ["[GNUPG:]", "VALIDSIG"]:
            # VALIDSIG's argument 10: the primary key's fingerprint; a short line counts as an unreadable signer.
            signers.add(fields[11].upper() if len(fields) >= 12 else "")
    if run.returncode != 0 or not signers or plaintext:
        # PLAINTEXT: the .sig is a signed message of its own, never the detached signature of this file.
        return f"bad or missing signature (gpgv exit {run.returncode}{', a signed message, not a detached signature' if plaintext else ''})"
    if len(signers) > 1:
        return "signatures by more than one key: which one vouches for it is unknown (as the Store, refused)"
    signer = signers.pop()
    if not FINGERPRINT.match(signer) or signer not in trusted or signer in revoked:
        return f"signed by {signer or '?'}, which grassfield-trusted does not list or grassfield-revoked does"
    return None


def verify(directory, keyring_dir, channel, min_serial, p):
    """What the Store does before it uses a catalog (ADR-0037 g "Signature and verification"), for CI's own check."""
    path = os.path.join(directory, CATALOG_NAME)
    problem = signature_problem(path, keyring_dir)
    if problem:
        p.add(path, problem)
        return
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) > MAX_CATALOG:
        p.add(path, f"more than {MAX_CATALOG} bytes")
        return
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        p.add(path, f"signed, but not UTF-8 JSON: {e or type(e).__name__}")
        return
    validate_catalog(obj, p, channel)
    if not isinstance(obj, dict):
        return
    if is_int(obj.get("serial")) and obj["serial"] < min_serial:
        p.add(path, f"serial {obj['serial']} is lower than the one already accepted ({min_serial})")
    for a in obj.get("apps", []) if isinstance(obj, dict) and isinstance(obj.get("apps"), list) else []:
        icon = a.get("icon") if isinstance(a, dict) else None
        if isinstance(icon, dict) and isinstance(icon.get("sha256"), str):
            icon_path = os.path.join(directory, "catalog", icon["sha256"] + ".png")
            try:
                with open(icon_path, "rb") as f:
                    data = f.read()
            except OSError:
                p.add(icon_path, "missing")
                continue
            if hashlib.sha256(data).hexdigest() != icon["sha256"] or len(data) != icon.get("bytes"):
                p.add(icon_path, "does not match the hash and size the signed file lists")


# --- command line ---------------------------------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(prog="catalog.py", description="Grassfield Store catalog (ADR-0037 g)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "packages", "aur-packages", "check-env", "build", "pin"):
        s = sub.add_parser(name)
        s.add_argument("--src", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "catalog"))
        if name in ("check-env", "pin"):
            s.add_argument("--facts", required=name == "check-env")
            s.add_argument("--omarchy", required=True)
        if name == "build":
            s.add_argument("--channel", required=True, choices=CHANNELS)
            s.add_argument("--serial", required=True, type=int)
            s.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--homedir", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("file")
    s = sub.add_parser("verify")
    s.add_argument("--keyring-dir", required=True)
    s.add_argument("--channel", required=True, choices=CHANNELS)
    s.add_argument("--min-serial", type=int, default=0)
    s.add_argument("dir")
    args = ap.parse_args(argv)

    p = Problems()
    if args.cmd == "sign":
        print(sign(args.file, args.homedir, args.key))
        return 0
    if args.cmd == "verify":
        verify(args.dir, args.keyring_dir, args.channel, args.min_serial, p)
    elif args.cmd == "build":
        out = build(args.src, args.channel, args.serial, args.out, p)
        if out:
            print(out)
    elif args.cmd == "pin":
        changes = pin(args.src, args.omarchy, args.facts, p)
        if not p:
            print("\n".join(changes) or "nothing changed")
            print(f"catalog.py pin: omarchy.lock written ({len(changes)} change(s)); read each new or changed file "
                  "before committing it")
    else:
        obj, _ = load_sources(args.src, p)
        validate_catalog(obj, p)
        if args.cmd == "packages":
            print("\n".join(wanted_packages(obj)))
        elif args.cmd == "aur-packages":
            print("\n".join(aur_packages(obj)))
        elif args.cmd == "check-env":
            check_env(obj, args.facts, args.omarchy, p, read_pins(os.path.join(args.src, "omarchy.lock")))
    for item in p.items:
        print(item, file=sys.stderr)
    if p:
        print(f"catalog.py {args.cmd}: {len(p.items)} problem(s)", file=sys.stderr)
        return 1
    if args.cmd in ("validate", "check-env", "verify"):
        print(f"catalog.py {args.cmd}: ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, TypeError, RecursionError, subprocess.CalledProcessError) as e:
        print(f"catalog.py: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
