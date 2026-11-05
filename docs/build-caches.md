# Build caches, timings, compression and the tag poll

Scope: `.github/workflows/build.yml` (build job), `scripts/build-channel.sh`, `scripts/build-summary.sh`,
`.github/workflows/poll.yml`, `tests/test_workflows.py`. Written 2026-11-05 for the owner's points 1-4, amended after the
security review the same day.

## The rule

**A run that can reach the release job restores and saves no cache of any kind** (no pacman, no ccache, no data cache).
Caches serve builds from a branch other than main, which never reach the release job. Why: actions/cache unpacks an entry
with `tar -P` into the runner's workspace, so an entry can write anywhere there, absolute paths included (for example
`packages/scripts/build-channel.sh`), and pacman's signature check covers package files only, not what else an entry
wrote. Main-scope entries can be written by any run on main (build, poll, catalog, publish, watch-hyprland), so one
compromise of one of them would reach the next signed release. Before this work the release path restored no cache, and it
still restores none.

Structure: the build job has one switch, the job env `USE_CACHE`
(`github.ref != 'refs/heads/main' && startsWith(github.ref, 'refs/heads/')`: false for main, tags and pull request refs).
Every step that restores or saves a cache carries `if: env.USE_CACHE == 'true'` as a conjunct, the container gets no cache
mount and no cache variable otherwise, and no other workflow uses a cache. `tests/test_workflows.py` checks this over the
YAML on every edit (every `actions/cache` step guarded, no `||` in the guard, the switch false for main, no cache in the
release job or in any other workflow, actions pinned by SHA). It needs PyYAML and skips without it: the integrator's
check runs it where PyYAML is installed (the unit-test container of `tests/run-in-container.sh` has none).
There is no opt-in for release builds.

## What a branch build does

- `build-channel.sh` keeps statistics in `/build/stats` (step times, a process sample every 5 s, ccache counters) and
  time-stamps makepkg's lines in `build.log`. The job summary of every build (cache or not) shows the steps, makepkg's
  phases, the time between two CMake configures, the wall time of each tool (pacman, cc1plus, qmlcachegen, python = the
  icon composer, wallpaper shrink, rsvg-convert, zstd...) and, with caches, the ccache hit rate. Names, times, counters.
  The summary step copies regular files of `out/` only, never following a symlink the container may have planted.
- ccache (`GRASSFIELD_CCACHE_DIR`): compiler wrappers first in makepkg's PATH (what makepkg's `ccache` BUILDENV does),
  `CCACHE_COMPILERCHECK=content`, `CCACHE_BASEDIR=/build`, 2 GB. PKGBUILD is untouched.
- pacman cache: `/var/cache/pacman/pkg` is a mounted folder, key `pacman-dev-<image digest>-<hash of pacman.conf,
  build-channel.sh, PKGBUILD>`, saved with the hash of the final listing appended only when the listing changed;
  `pacman -Sc` afterwards leaves this build's package set. pacman still verifies each cached package (checksum from the
  database, signature) at install, which protects against a bad package, not against the other files of an entry: that is
  why release-capable runs do not use it.
- data products (`GRASSFIELD_DATA_CACHE`): plumbing only, see below.
- Entries are visible to the branch that saved them. GitHub also lets a branch read main's entries; main saves none.

## Compression (point 3)

Arch's `makepkg.conf` already has `COMPRESSZST=(zstd -c -T0 -)`: all cores, level 3. It is now written down in
`/etc/makepkg.conf.d/grassfield.conf` (`-T0 -3`) so a change of Arch's default is a change here. Measured here with the
installed grassfield data (tar, `zstd -T0`, 8 cores):

| content | tar size | level 3 | level 19 |
|---|---:|---|---|
| icons theme (grassfield-icons) | 82.8 MB | 22.4 MB, 0.4 s | 20.6 MB, 25.8 s (-8%) |
| wallpapers | 43.9 MB | 43.9 MB, 0.14 s | 43.8 MB, 13.6 s (-0.2%) |

Compression is seconds at level 3; a higher level costs 50-100x the time for 0-8%. No change of level.

## Data packages (point 2)

The icon composition (`icons-compose.py`), the photograph shrink (`grassfield-wallpaper-shrink`), the cursor build and the
Plymouth images run inside grassfield's `packaging/arch/PKGBUILD` `build()`, which this repository cannot change. This
repository adds the packages side only: in a branch build the folder `GRASSFIELD_DATA_CACHE=/cache/data` exists and is
saved as `data-dev-<digest>-<hash of the inputs>` (`icon*`, `wallpaper*`, `branding/icons/theme`, `branding/cursors`,
`packaging/plymouth`, `apps/wallpaper-tool` of the tag), only when the folder is not empty (an empty folder is not saved:
an empty 193-byte entry was observed and would shadow the real one) and the exact key did not exist. A cache key is
first-writer-wins: an entry is never overwritten, so within a branch the first entry saved for a given input hash is what
every later build of that hash restores, a bad one included, until it is deleted (`gh cache delete`) or evicted
(unused for 7 days, or the repository's 10 GB limit). That concerns dev builds only (never signed for clients: the test
job signs with a throwaway key); delete the entry to refresh it. Proposed change for grassfield (a build-only change for
its owner, the same shape for the photographs and the Plymouth images):

```bash
_gf_cached() { # name, inputs-hash, output-dir, command... : restore output-dir from $GRASSFIELD_DATA_CACHE or make and keep it
  local name=$1 hash=$2 out=$3; shift 3
  local c=${GRASSFIELD_DATA_CACHE:+$GRASSFIELD_DATA_CACHE/$name-$hash}
  if [[ -n $c && -f $c/.complete ]]; then cp -a "$c/." "$out/"; return; fi
  "$@"
  if [[ -n $c ]]; then rm -rf "$c" && mkdir -p "$c" && cp -a "$out/." "$c/" && : >"$c/.complete"; fi
}
```
The hash must cover every input (the stamp of grassfield's `scripts/dev/icons.sh` is the model).

## Starting a build on a tag (point 4)

`repository_dispatch` needs a token that can call this repository from grassfield (a secret only the owner can create, and a
CI workflow in grassfield, which has none today). The poll needs nothing new: `poll.yml` exists and uses the deploy key
to list tags. It runs at :07, :17, :27, :37, :47, :57 and starts a build only for a `v*` tag with no `build <tag>` run of
main (runs of other branches do not count: they never reach the release job) and not listed by the public beta channel's
signed notes (a stored tag must not raise an approval prompt; the notes list at most 20 releases, older tags fall back to
the run check). At most 3 per poll, one poll at a time. Latency: at most 10 minutes plus GitHub's scheduling delay. It
starts `build.yml` on main with `gh workflow run`; the release job and publish.yml still wait for the owner's approval of
publish-stable and publish-beta.
Variable to set: **`GRASSFIELD_TAG_POLL` = `on`** (repository variable; the secret `GRASSFIELD_DEPLOY_KEY` exists).

## Measurements

Dev (branch) builds of `v1.0.0-rc3`, `build.yml` dispatched from `feat/faster-builds` by the integrator:

| run | build job |
|---|---|
| cold, empty caches (41936088220) | 24 min 48 s |
| warm, same branch (41939837100) | 17 min 45 s |

The ccache hit rate and the per-tool table are in the summary of each run. A release build (main, a `v*` ref) uses no
cache: it stays at about 25-27 minutes, as before this work. The speed-up exists for dev and test builds only, by design:
the release path is the signing path.
