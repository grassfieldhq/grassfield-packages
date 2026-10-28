# The Grassfield Store catalog

What Grassfield edits for Grassfield Store: the sections (Discover first), the categories, and our short texts. The format, the
rules and how the Store checks it are grassfieldhq/grassfield `docs/decisions/ADR-0037-store.md` section g. CI builds one
`grassfield-catalog.v1.json` per channel from these files, signs it, and keeps it as an artifact. Nothing is published
until the owner decides (CLAUDE.md).

## Layout
| Path | What |
|---|---|
| `categories.json` | `{"categories": [...]}`: id, title, symbol, the freedesktop categories each one gathers (at most 32) |
| `sections/<id>.json` | one section each, with `"order"` (an integer, sorted ascending, dropped by the build); `discover` comes first (at most 8 sections, 12 blocks each) |
| `apps/<id>.json` | one app each, the file named after its id; the id is the app's AppStream id when it has one, spelled exactly as AppStream spells it (CI checks it) |
| `icons/<name>.png`, `icons/<name>.json` | an icon for an app with no metadata, and its `{"license", "origin", "review": "needs legal review"}` |
| `omarchy.lock` | the Omarchy release the recipes and package names are checked against (the owner's version), and the pins: the SHA-256 of every Omarchy file the setups and the AUR's two commands run or read |

## Adding an app
1. Pick its source, in this order when it has several: an Omarchy setup (it configures what Omarchy configures), an Arch or
   `[omarchy]` package, Flathub, the AUR.
2. Write `apps/<id>.json`:
   - a package: `{"id": "org.gimp.GIMP", "source": {"kind": "repo", "repo": "extra", "package": "gimp"},
     "categories": ["graphics"]}`. Only packages that own an application entry (`/usr/share/applications/*.desktop`): the
     Store can then remove whatever it installs (ADR-0037 SD1).
   - an Omarchy setup: `install` and `remove` recipes (`omarchy-install-…`, `omarchy-remove-…`), their arguments, the
     `packages` that say it is installed, `changes` (what the recipe does, in plain words, written after reading it) and
     `removes` (the user data its removal deletes, when it deletes any). Recipes that sync pacman's databases or download
     code are refused.
   - an AUR package: `{"id": "example-app", "source": {"kind": "aur", "package": "example-app"}}`. CI refuses a name a
     repository of Omarchy's stable mirror has (yay would install the repository's: list it as a `repo` app) and a name
     the AUR does not know. The Store builds it through Omarchy's `omarchy-pkg-aur-add` in Omarchy's terminal, with its
     warning every time (ADR-0037 b.2).
   - an app without AppStream metadata (most `[omarchy]` packages, web apps): `name`, `summary`, `developer`, `license`,
     `homepage`, and `desktopId` when the package has several entries.
3. Put it in a section or a category, then run the checks below.

## Texts
- Our own words, plain text: no markup, no links, no control or bidirectional characters. English (`en`) is required,
  French (`fr`) expected; v1 reads no other language.
- Lengths in characters: section and category titles 40, eyebrows 40, titles and names 80, texts and summaries 200,
  descriptions 4000. Line breaks only in texts, summaries and descriptions.
- Never Apple's names ("App Store", "Arcade"), editorial texts or assets. The section and category names, and the
  publishers' icons, need legal review before any publication (ADR-0037 e.10, owner decision ST10). Category names are
  neutral words that keep macOS's structure ("Graphics", "Photos and Video", "Development"), never the Mac App Store's own
  list ("Graphics & Design", "Photo & Video", "Developer Tools"); whether a closer name may be used is the owner's legal
  question (docs/STATE.md).

## Checks
```sh
python3 -I tools/catalog.py validate                    # the format, offline
tests/run-in-container.sh                               # the unit tests, with throwaway keys, in a container
# The facts, in a throwaway Arch container with an Omarchy checkout at the pinned commit:
docker run --rm -v "$PWD":/src:ro -v <omarchy>:/omarchy:ro -v /tmp/facts:/out archlinux:base \
  bash -c 'pacman -Syu --noconfirm git >/dev/null && git config --global --add safe.directory /omarchy &&
           bash /src/tools/catalog-facts.sh /omarchy /src/catalog /out'
python3 -I tools/catalog.py check-env --facts /tmp/facts --omarchy <omarchy>
```
CI (`.github/workflows/catalog.yml`) runs all of them, then builds both channels, signs them with a throwaway key made in
its container, verifies them as the Store does, and keeps the result as an artifact for 7 days.

## A setup, or a new Omarchy release: the pins
A setup runs Omarchy's own files: its recipe and everything the recipe calls or sources. So does an AUR package, through
Omarchy's `omarchy-pkg-aur-add` and `omarchy-pkg-drop`: these two are pinned and scanned always, whether or not the catalog
lists an AUR app, since the Store's AUR search results take the same path (ADR-0037 SD21). CI does not try to judge those
files by reading them; it refuses any of them whose SHA-256 differs from its pin in `omarchy.lock`, is missing, or is not
pinned (ADR-0037 g). So adding a setup, or moving to another Omarchy release (bump `tag` and `commit` together):
1. Gather the facts (above), then run, with an Omarchy checkout at the commit `omarchy.lock` names:
   `python3 -I tools/catalog.py pin --omarchy <omarchy> --facts /tmp/facts`.
2. `pin` first runs the scan, the second line: it refuses to write any pin when a file syncs pacman's databases, downloads
   code, builds from the AUR, uses `eval`, reads a script from a pipe or a heredoc, names a command it cannot know (an
   Omarchy command named at run time, a command made by a substitution), runs or sources a file the pins do not cover
   (`bash "$OMARCHY_PATH/$h/run.sh"`, `./hidden.sh`, a path made at run time, a `PATH` naming another folder, the files
   `find -exec` finds, a folder `run-parts` runs, a script an interpreter runs), hands to a command it does not know a
   package manager or a downloader (`firejail "$pm" -Sy`), a file of Omarchy's the release lacks, an Omarchy command the
   release lacks or a script outside the pins (`chrt -f 1 "$OMARCHY_PATH/hidden/run"`, `firejail /tmp/x.sh`), or cannot
   be read as shell. A shell or an interpreter with words after it, handed to a command the scan does not know
   (`chrt -f 1 bash x.sh`, `firejail python3 -c '...'`), is read as a command it runs. The command `find -exec`,
   `-execdir`, `-ok` or `-okdir` runs is read as a command; handed the files found (`{}`), it must be, with no wrapper in front, one that only copies, moves,
   removes, changes or reads a file (`rm`, `cp`, `chmod`...), and a `+` ends it only right after `{}`; `run-parts` is
   accepted only as `--list DIR` or `--test DIR`. A wrapper's option the scan does not list (`env -a`, `env -S`,
   `flock -c`, `sudo -s`...) is refused wherever it appears. Such a setup is not offered.
3. Otherwise it writes the pins and lists every new, changed and removed file, and what it could not resolve ("read: …":
   a command named by a variable, a variable or a substitution handed to a command it does not know, one of Omarchy's
   folders handed to one: `quickshell -p "$OMARCHY_PATH/shell"`, whose files are not pinned). Read each listed file
   before committing `omarchy.lock`: the pin says nobody changed it, not that it is safe.
4. `build` publishes the release and the pins in the catalog (`"omarchy": {"tag", "commit", "files"}`, ADR-0037 g): the
   Store runs a setup, or one of the AUR's two commands, only while every pinned file of the installed Omarchy matches, and
   otherwise says it waits for the catalog to catch up with that Omarchy.
