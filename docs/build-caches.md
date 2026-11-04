# Build caches, timings, compression and the tag poll

Scope: `.github/workflows/build.yml` (build job), `scripts/build-channel.sh`, `scripts/build-summary.sh`,
`.github/workflows/poll.yml`. Written 2026-11-05 for the owner's points 1-4.

## What the build job does now

- `build-channel.sh` keeps statistics in `/build/stats` (step times, a process sample every 5 s, ccache counters) and
  time-stamps makepkg's lines in `build.log`. The job summary shows: the steps, makepkg's phases (dependency install,
  sources, build, check, package), the time between two CMake configures (a build directory's cost), the wall time of
  each tool (pacman, cc1plus, qmlcachegen, python = the icon composer, wallpaper shrink, rsvg-convert, zstd...) and the
  ccache hit rate. Names, times and counters only. This answers "where do the 27 minutes go" on the first run after merge;
  the table is in the summary of every run, and `out/build.log` keeps the detail.
- ccache (`GRASSFIELD_CCACHE_DIR`): the compiler wrappers go first in makepkg's PATH (what makepkg's own `ccache`
  BUILDENV does; cmake finds `c++`/`cc` there), `CCACHE_COMPILERCHECK=content`, `CCACHE_BASEDIR=/build`, 2 GB. PKGBUILD
  is untouched.
- pacman cache: `/var/cache/pacman/pkg` is a mounted folder. Key `pacman-<scope>-<image digest>-<hash of pacman.conf,
  build-channel.sh, PKGBUILD>`, saved as `...-<hash of the final listing>` only when the listing changed; restore-keys:
  same scope and digest, then main's. After the build `pacman -Sc` removes what is not installed, so the saved folder is
  this build's package set and does not grow.
- compression: see below.
- data products (`GRASSFIELD_DATA_CACHE`): plumbing only, see "Data packages".

## Cache security (the signing pipeline reads these)

### Who can write a cache a release build reads

GitHub's rule: a run restores caches saved by its own ref, and by the default branch (for a pull request also its base).
It never restores a sibling branch's or another pull request's. A cache saved by a run on `refs/pull/N/merge` is
visible to that pull request only. This workflow has no `pull_request` trigger at all, and a fork's pull request has no
write access to this repository's caches. The release job requires `github.ref == refs/heads/main`; the artifact it signs
is made by the build job of the same run, so the build job of a release is a run of main: it reads main's caches only.
Who writes main's caches: a run whose ref is main, i.e. code of main's workflow files (anyone who can write main can also
change the release job, so this is not a new principal), plus whatever runs inside those runs.

Guards added:

1. Key names carry the scope (`main` or `dev`; every branch other than main is `dev`). A run of main restores only
   `*-main-*` names, and the step "A run of main restored only what main saved" asks the API (`actions: read`, the only
   permission added, on the build job only) that a cache of that exact name exists with `ref == refs/heads/main`; otherwise
   the job fails before the container starts.
2. main saves ccache and data caches only from a build of a `v*` input (a tag), never from a commit run: main's caches are
   written by release-bound builds only. A dispatch from another branch saves into that branch's scope, which main never
   reads.
3. All actions are pinned by SHA (actions/cache v4.2.3 = 5a3ec84eff668545956fd18022155c47e93e2684, checked against
   api.github.com).

### The ccache threat, and the recommendation

The threat: a planted object file served for a hash that a release compiles, so that the signed package carries code
nobody reviewed. ccache's key is the hash of the preprocessed source, the compiler (content) and the flags: the attacker
cannot make a legitimate source hash to a different object, only write an entry under the right name, and ccache
checks entries only for corruption (its own checksum, which a writer computes). So the whole risk is "who can write
the folder main restores". With the scoping above, that is a run of main. Residual risk is not nil: a one-time compromise
inside a run of main (a bad package from the mirror, a tool in the build container) could plant entries that outlive the
compromise, because the entries keep being hit until evicted (GitHub evicts after 7 days unused or at the 10 GB limit),
while a direct compromise of the same run would only have affected that run. Entries are also invisible to review, unlike a
workflow change.

**Recommendation (implemented as the default): release builds bypass ccache and the data cache.**
`build_cache` is false for a run of main with a `v*` ref unless the repository variable `GRASSFIELD_RELEASE_CACHE` is
`on`. ccache and the data cache then serve dispatches from branches (the owner's and the integrator's test and dev builds,
and the measurements below), and releases are compiled from source in a fresh container. The pacman cache stays on for
releases: pacman verifies every cached package at install (database checksum from the freshly fetched, signed-where-present
database, then the package signature, `SigLevel = Required DatabaseOptional` in `build/pacman.conf`, with the
"checking package integrity" step that also covers cached files), so a planted file is rejected, and a missing `.sig` is
refused by `Required`. If the owner later accepts the residual risk for speed, `GRASSFIELD_RELEASE_CACHE=on` enables
the caches for tags with guards 1-2 in force. The cost of the default: tag builds do not get the compile speed-up (they
get the pacman download savings and the timing report).

No secret is in a cache, a log or the summary: the build container holds only a throwaway key made inside it (never
mounted or saved); the folders mounted are `cache/pacman`, `cache/ccache`, `cache/data`; the summary prints
names, times and counters.

## Compression (point 3)

Arch's `makepkg.conf` already has `COMPRESSZST=(zstd -c -T0 -)`: all cores, level 3. It is now written down in
`/etc/makepkg.conf.d/grassfield.conf` (`-T0 -3`) so a change of Arch's default is a change here. Measured on this
machine with the installed grassfield data (tar, `zstd -T0`, 8 cores):

| content | tar size | level 3 | level 19 |
|---|---:|---|---|
| icons theme (grassfield-icons) | 82.8 MB | 22.4 MB, 0.4 s | 20.6 MB, 25.8 s (-8%) |
| wallpapers | 43.9 MB | 43.9 MB, 0.14 s | 43.8 MB, 13.6 s (-0.2%) |

Compression is seconds, not minutes, at level 3; a higher level costs 50-100x the time for 0-8%. No change of level.

## Data packages (point 2)

The icon composition (`icons-compose.py`), the photograph shrink (`grassfield-wallpaper-shrink`), the cursor build and the
Plymouth images run inside grassfield's `packaging/arch/PKGBUILD` `build()`, which this repository cannot change (grassfield
owns it) and which gives a hook nowhere. This PR therefore only adds the packages side: when the build is allowed to use
caches the folder `GRASSFIELD_DATA_CACHE=/cache/data` exists and is saved as `data-<scope>-<digest>-<hash of the inputs>`
(`icon*`, `wallpaper*`, `branding/icons/theme`, `branding/cursors`, `packaging/plymouth`, `apps/wallpaper-tool` of the tag),
only when the exact key did not exist. Nothing is saved while the folder is empty, so it is inert until grassfield's
PKGBUILD uses it. Proposed change for grassfield (an ADR-free build-only change, to be done by the grassfield owner):

```bash
# in build(), around the icons composition (same shape for the photographs and the Plymouth images)
_gf_cached() { # name, inputs-hash, output-dir, command... : restore output-dir from $GRASSFIELD_DATA_CACHE or make and keep it
  local name=$1 hash=$2 out=$3; shift 3
  local c=${GRASSFIELD_DATA_CACHE:+$GRASSFIELD_DATA_CACHE/$name-$hash}
  if [[ -n $c && -f $c/.complete ]]; then cp -a "$c/." "$out/"; return; fi
  "$@"
  if [[ -n $c ]]; then rm -rf "$c" && mkdir -p "$c" && cp -a "$out/." "$c/" && : >"$c/.complete"; fi
}
```
The hash must cover every input (the stamp of `scripts/dev/icons.sh` is the model: pins, composer, list, branding files).
The same poisoning argument applies as for ccache (a restored product goes into a signed package), hence the same default:
not used by release builds.

## Starting a build on a tag (point 4)

`repository_dispatch` needs a token that can call this repository from grassfield (a secret only the owner can create, a
CI workflow in grassfield that has none today). The poll needs nothing new: `poll.yml` exists and uses the deploy key to
list tags. It now runs at :07, :17, :27, :37, :47, :57 (every 10 minutes, off the top of the hour where GitHub delays
most), and starts a build only for a `v*` tag with no `build <tag>` run and not listed in the public beta channel's signed
notes (so a tag whose release is stored does not raise an approval prompt; the notes also list earlier releases from the
tags, so the poll never goes back to a tag older than the newest published one). At most 3 per poll; one poll at a time.
Latency: at most 10 minutes plus GitHub's scheduling delay. The poll starts `build.yml` on main with `gh workflow run`;
the release job and publish.yml still wait for the owner's approval of publish-stable and publish-beta.
Variable to set: **`GRASSFIELD_TAG_POLL` = `on`** (repository variable; the secret `GRASSFIELD_DEPLOY_KEY` already exists).
Optional: `GRASSFIELD_RELEASE_CACHE` = `on` only if the owner chooses speed over the recommendation above.

## Measurements

NOT VERIFIED. The agent has no GitHub login (`gh auth status`: not logged in) and no docker socket, so it could not
dispatch `build.yml` from the branch with `-f ref=v1.0.0-rc3`, cold then warm. Local measurement of compression is above.
After the merge or from the branch the integrator can run
`gh workflow run build.yml --ref feat/faster-builds -f ref=v1.0.0-rc3` twice; the summary of each run prints the table
and the hit rate, which fills in the two lines below.

| run | build job | ccache hit rate |
|---|---|---|
| cold (branch, empty caches) | (to measure) | 0% |
| warm (same branch, second run) | (to measure) | (to measure) |
