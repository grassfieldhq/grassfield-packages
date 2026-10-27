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
SECTION_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
APP_ID = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
PACKAGE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]{0,127}$")
SETUP_INSTALL = re.compile(r"^omarchy-install-[a-z0-9-]+$")
SETUP_REMOVE = re.compile(r"^omarchy-remove-[a-z0-9-]+$")
RECIPE_ARG = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
DESKTOP_ID = re.compile(r"^[A-Za-z0-9._-]{1,250}\.desktop$")
FLATPAK_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
SYMBOL = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
FREEDESKTOP = re.compile(r"^[A-Za-z0-9-]{1,64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LICENSE = re.compile(r"^[A-Za-z0-9.+()-]+( (AND|OR|WITH) [A-Za-z0-9.+()-]+)*$")
GENERATED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ICON_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FINGERPRINT = re.compile(r"^[0-9A-F]{40}$")

# Lengths in code points (ADR-0037 g).
LEN_SECTION_TITLE, LEN_EYEBROW, LEN_TITLE, LEN_TEXT, LEN_DESCRIPTION = 40, 40, 80, 200, 4000
# Bidirectional formatting characters: plain text never needs them, and they can make a text read other than it is.
BIDI = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")

# Recipes: what the catalog may not name (ADR-0037 a and e.4). A sync makes the next install a partial upgrade (S12):
# any short-option cluster with y (-Sy, -Syu, -S -y), --refresh or --sysupgrade on a pacman, yay or paru command, and a
# yay or paru with no operation (alone it is -Syu; with a term, an interactive AUR install). A download runs code pacman
# never checked: curl, wget, makepkg, git clone/pull/fetch, yay or paru -G or -B, the language installers (mise, npm, pipx,
# cargo, uv and their kin), and an AUR build (omarchy-pkg-aur-add, or yay/paru -S, of a name no repository serves or one
# known only at run time). The setups Omarchy marks as such (GeForce NOW, Battle.net, dev-env, Hermes) are refused.
# The text is read as shell, failing closed: line continuations joined, quotes removed, every command found after the
# wrappers that run it (sudo -u x, env, command, exec, ...), and quoted text with spaces read as commands too (bash -c,
# sh -c and Omarchy's terminal launchers run their string). The two patterns below are a second, plainer reading.
SYNC = re.compile(r"\b(pacman|yay|paru)\b[^\n;&|]*?\s(-[A-Za-z]*y[A-Za-z]*|--refresh|--sysupgrade)\b")
DOWNLOAD = re.compile(r"\b(curl|wget|makepkg)\b|\bgit\b[^\n;&|]*\s(clone|pull|fetch)\b|"
                      r"\b(yay|paru)\b[^\n;&|]*\s(-G|--getpkgbuild|-B|--build)\b")
SHELL_BREAK = re.compile(r"[\n;&|(){}`]")
SHELL_KEYWORDS = {"if", "then", "do", "else", "elif", "while", "until", "!", "time", "[[", "]]"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Programs that run the command after them: (their options that take an argument, how many plain arguments come first).
WRAPPERS = {
    "sudo": ({"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D", "-R", "-T", "--user", "--group"}, 0),
    "doas": ({"-u", "-C"}, 0), "run0": ({"-u", "--user", "-g", "--group", "-D", "--chdir"}, 0), "pkexec": ({"--user"}, 0),
    "env": ({"-u", "-C", "-S", "--unset", "--chdir"}, 0), "command": (set(), 0), "builtin": (set(), 0),
    "exec": ({"-a"}, 0), "nohup": (set(), 0), "setsid": (set(), 0), "nice": ({"-n"}, 0), "ionice": ({"-c", "-n"}, 0),
    "stdbuf": ({"-i", "-o", "-e"}, 0), "timeout": ({"-s", "-k", "--signal", "--kill-after"}, 1),
    "flock": ({"-w", "-E", "--timeout", "--conflict-exit-code"}, 1), "xargs": ({"-I", "-n", "-P", "-d", "-a", "-L"}, 0),
    "uwsm-app": (set(), 0),
}
PACKAGE_MANAGERS = {"pacman", "yay", "paru"}
AUR_HELPERS = {"yay", "paru"}
DOWNLOADERS = {"curl", "wget", "makepkg", "mise", "npm", "npx", "pnpm", "yarn", "bun", "bunx", "pipx", "pip", "pip3",
               "cargo", "rustup", "uv", "uvx", "go", "gem"}
# What mise does without fetching anything (where, ls, rm...); every other mise command may install.
MISE_LOCAL = {"where", "ls", "list", "current", "which", "rm", "remove", "uninstall", "unuse", "activate", "version",
              "--version"}
OMARCHY_CALL = re.compile(r"\b(omarchy-[a-z0-9-]+)\b")
# Omarchy's two launcher makers download an icon (data, never run: ADR-0037 S9), not code; read again at each pin bump.
DATA_DOWNLOADS = {"bin/omarchy-webapp-install", "bin/omarchy-tui-install"}
OMARCHY_SOURCE = re.compile(r"\$\{?OMARCHY_PATH\}?/([A-Za-z0-9_./-]+)")


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

def validate_catalog(obj, p, channel=None):
    """The rules of the built file. The Store applies the same ones; CI refuses any break."""
    if not isinstance(obj, dict):
        p.add("catalog", "not a JSON object")
        return
    check_keys(p, "catalog", obj, ("version", "channel", "serial", "generated", "sections", "categories", "apps"))
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
    return obj, icon_files


# --- the system the catalog names (CI, in an Arch container with Omarchy's stable configuration) --------------------

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
            text = f.read()
        out.append((rel, text))
        for call in OMARCHY_CALL.findall(text):
            if os.path.isfile(os.path.join(omarchy, "bin", call)):
                todo.append(os.path.join("bin", call))
        for sourced in OMARCHY_SOURCE.findall(text):
            if os.path.isfile(os.path.join(omarchy, sourced)):
                todo.append(sourced)
    return out


def simple_commands(code, depth=0):
    """Each simple command of a shell text, as its words after the wrappers that run it (the first word a base name)."""
    out = []
    for piece in SHELL_BREAK.split(code.replace("\\\n", " ")):
        try:
            words = shlex.split(piece)
        except ValueError:
            words = piece.replace('"', " ").replace("'", " ").split()
        if depth < 4:
            for i, w in enumerate(words):
                if any(ch.isspace() for ch in w) or (i and words[i - 1] == "-c"):
                    out.extend(simple_commands(w, depth + 1))  # bash -c "...", a terminal launcher's command
        while words:
            base = os.path.basename(words[0])
            if words[0] in SHELL_KEYWORDS or ASSIGNMENT.match(words[0]):
                words = words[1:]
            elif base in WRAPPERS:
                takes, plain = WRAPPERS[base]
                words = words[1:]
                while words:
                    if words[0] == "--":
                        words = words[1:]
                        break
                    if words[0].startswith("-"):
                        words = words[2:] if words[0] in takes else words[1:]
                    elif ASSIGNMENT.match(words[0]):
                        words = words[1:]
                    elif plain:
                        plain, words = plain - 1, words[1:]
                    else:
                        break
            else:
                break
        if words:
            out.append([os.path.basename(words[0])] + words[1:])
    return out


def aur_names(names, repo):
    """Names an AUR install would build: those no repository serves, or that are known only at run time."""
    built = []
    for name in names:
        if "$" in name or "`" in name or not PACKAGE.match(name):
            built.append(f"{name} (known only at run time)")
        elif repo is not None and name not in repo:
            built.append(name)
    return built


def command_findings(code, repo=None):
    """(syncs, downloads, AUR names built) of a shell text, read command by command."""
    sync, download, built = False, False, []
    for words in simple_commands(code):
        cmd, args = words[0], words[1:]
        short = [a for a in args if a.startswith("-") and not a.startswith("--") and len(a) > 1]
        if cmd in PACKAGE_MANAGERS and (any("y" in a[1:] for a in short) or {"--refresh", "--sysupgrade"} & set(args)):
            sync = True
        if cmd in AUR_HELPERS:
            ops = [a for a in args if not a.startswith("--")]
            if not ops or not re.match(r"^-[SRQGPYDTUFBWVh]", ops[0]):
                sync = True  # no operation: -Syu; a term alone: an interactive search and AUR install
            if any(re.match(r"^-[A-Za-z]*[GB]", a) for a in short) or {"--getpkgbuild", "--build"} & set(args):
                download = True
            if ops and ops[0].startswith("-S") and not set(ops[0][2:]) & set("silgpc"):
                built += aur_names([a for a in args if not a.startswith("-")], repo)
        if cmd == "omarchy-pkg-aur-add":
            built += aur_names([a for a in args if not a.startswith("-")], repo)
        if cmd == "git" and {"clone", "pull", "fetch"} & set(args):
            download = True
        if cmd in DOWNLOADERS and not (cmd == "mise" and args and args[0] in MISE_LOCAL):
            download = True
    return sync, download, built


def recipe_problems(omarchy, name, args, repo=None):
    """repo: the package names Omarchy's stable mirror serves (None in tests that have no facts)."""
    path = os.path.join(omarchy, "bin", name)
    if not os.path.isfile(path):
        return [f"{name} is not in the pinned Omarchy release"]
    problems = []
    for rel, text in recipe_closure(omarchy, name):
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        plain = code.replace("\\\n", " ").replace('"', "").replace("'", "")
        sync, download, built = command_findings(code, repo)
        if sync or SYNC.search(plain):
            problems.append(f"{name} syncs pacman's databases (through {rel}): a partial upgrade (ADR-0037 e.4)")
        if (download or DOWNLOAD.search(plain)) and rel not in DATA_DOWNLOADS:
            problems.append(f"{name} downloads outside pacman (through {rel}): not offered (ADR-0037 a)")
        # omarchy-pkg-aur-add's own yay -S "$@" is judged where it is called, with the names it is given.
        if rel == "bin/omarchy-pkg-aur-add":
            built = []
        if built:
            problems.append(f"{name} builds from the AUR (through {rel}): {', '.join(sorted(set(built)))} (ADR-0037 a)")
    with open(path, encoding="utf-8", errors="replace") as f:
        own = f.read()
    for arg in args:
        if not re.search(rf"^\s*(\S+\|)*{re.escape(arg)}(\|\S+)*\)", own, re.M):
            problems.append(f"{name} has no case for '{arg}'")
    return problems


def check_env(obj, facts, omarchy, p):
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
    except (OSError, ValueError) as e:
        p.add(facts, f"facts cannot be read: {e}")
        return
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
    signers = set()
    for line in run.stdout.splitlines():
        fields = line.split()
        if fields[:2] == ["[GNUPG:]", "VALIDSIG"]:
            # VALIDSIG's argument 10: the primary key's fingerprint; a short line counts as an unreadable signer.
            signers.add(fields[11].upper() if len(fields) >= 12 else "")
    if run.returncode != 0 or not signers:
        return f"bad or missing signature (gpgv exit {run.returncode})"
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
    for name in ("validate", "packages", "check-env", "build"):
        s = sub.add_parser(name)
        s.add_argument("--src", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "catalog"))
        if name == "check-env":
            s.add_argument("--facts", required=True)
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
    else:
        obj, _ = load_sources(args.src, p)
        validate_catalog(obj, p)
        if args.cmd == "packages":
            print("\n".join(wanted_packages(obj)))
        elif args.cmd == "check-env":
            check_env(obj, args.facts, args.omarchy, p)
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
