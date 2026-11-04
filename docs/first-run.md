# First publication, step by step

Owner decision of 2026-11-04: the repository goes live at https://packages.grassfield.site now, unannounced. The legal review
stays mandatory before any announcement. Nothing below is run by an agent: each step names who does it.

Already in place: the repository is public; the environments `publish-stable` and `publish-beta` (required reviewer: the
owner; deployments from `main` only) hold `GRASSFIELD_SIGNING_KEY`, `GRASSFIELD_SIGNING_PASSPHRASE`, the S3 pair and the
variables `GRASSFIELD_S3_BUCKET` (`grassfield`) and `GRASSFIELD_S3_ENDPOINT`; the repository holds `GRASSFIELD_DEPLOY_KEY`;
the R2 bucket `grassfield` is behind `packages.grassfield.site`. The tag poll stays off (`GRASSFIELD_TAG_POLL` unset).

## What runs

| Step | Where | Who approves |
|---|---|---|
| build and test with a throwaway key | `build.yml` jobs `build`, `test` (no secret but the deploy key) | none |
| sign a tag's tested release builds with the project's key, keep them under `releases/<channel>/` | `build.yml` job `release`, environment `publish-<channel>` | the owner, per channel |
| build the catalog, sign it, publish the snapshot, write the pointer | `publish.yml`, environment `publish-<channel>`, one concurrency group per channel | the owner, per channel |
| the pointer rule and cache headers at the edge | `edge/` Worker | deployed by hand (below) |

`release` runs only for a tag (`inputs.ref` starts with `v`) of `main`'s workflow. A plain tag (`vX.Y.Z`) goes to stable and
beta; a `-betaN` or `-rcN` tag to beta only (`build-channel.sh`, O15); for the other channel the `release` job finds no
release build and stops with "this tag does not go to ...": approve or reject it, nothing is written either way.
`publish.yml` does nothing for a channel with no release build and no pointer (a catalog alone cannot start a channel).

## Steps

1. **Integrator**: merge the PR of this change to `main`. `publish.yml` starts on the push and asks the approval of each
   channel: with no release built yet it ends at "nothing to publish". Approving or rejecting is harmless.
2. **Owner (or integrator)**: deploy the Worker, from this repository's `edge/`, with a Cloudflare account that owns the zone
   `grassfield.site` and the bucket `grassfield` (a token with Workers Scripts: Edit and Workers Routes: Edit, or
   `wrangler login`; nothing of it goes to GitHub):

       cd edge
       npm ci                          # wrangler 4.150.0, from package-lock.json
       npm test                        # the Worker against scripts/serve.py, no network
       npx wrangler deploy --dry-run   # shows the binding and the route, writes nothing
       npx wrangler deploy             # six routes on packages.grassfield.site (the fixed names only), R2 binding BUCKET -> grassfield

   If `curl -sI https://packages.grassfield.site/stable/x86_64/grassfield.db` after step 7 answers a plain R2 404 and not
   the Worker's, the route is not in front of the bucket's custom domain (ADR-0033 h.5 marks this NOT VERIFIED): stop and
   report, do not work around it with copies of the database.
3. **Owner**: tag grassfield (`vX.Y.Z`, its `packaging/release-notes/<VERSION>.en.txt` present, `repository.conf` pinning
   fingerprint `E4921A382C349308BAA50D2F44C31B5D862EBEFA`, `packaging/pacman/` carrying the same key as `keyring/` here).
4. **Owner**: start the build by hand (the poll is off):

       gh workflow run build.yml -R grassfieldhq/grassfield-packages --ref main -f ref=vX.Y.Z

   It builds in a throwaway Arch container (about an hour), then `test` installs the packages in a fresh container.
5. **Owner**: approve the `release` job of each channel the tag goes to (`publish-stable` and `publish-beta` for `vX.Y.Z`). It prepares without
   the key, signs with it (no network), checks as a client checks (keyring byte for byte `keyring/`), and uploads under
   `releases/<channel>/<version>/`, the database last.
6. **Owner**: approve the `publish` runs (one per channel) that start when `build` completes. It checks every signature against
   `keyring/`, never goes backwards, uploads packages, then the snapshot, then writes `<channel>/x86_64/pointer` last.
7. **Checks** (anyone, from any machine):

       base=https://packages.grassfield.site/stable/x86_64
       curl -sI $base/grassfield.db                       # 302, Location: /stable/x86_64/snap/<id>/grassfield.db, Cache-Control: no-store
       curl -sI $base/pointer                             # 200, no-store
       d=$(mktemp -d)
       curl -fsSL -o $d/grassfield.db     $base/grassfield.db
       curl -fsSL -o $d/grassfield.db.sig $base/grassfield.db.sig
       gpgv --homedir $d --keyring ./keyring/grassfield.gpg $d/grassfield.db.sig $d/grassfield.db
       # expect: Good signature ... key E4921A382C349308BAA50D2F44C31B5D862EBEFA
       curl -sI $base/snap/<id>/grassfield.db             # 200, Cache-Control: public, max-age=31536000, immutable
       curl -s -o /dev/null -w '%{http_code}\n' $base/nothing.pkg.tar.zst   # 404, Cache-Control: no-store

   Install, in a throwaway Arch container (never on a real machine):

       docker run --rm -v "$PWD/keyring:/k:ro" archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0 bash -euxc '
         pacman-key --init && pacman-key --populate archlinux
         pacman-key --add /k/grassfield.gpg && pacman-key --lsign-key E4921A382C349308BAA50D2F44C31B5D862EBEFA
         printf "[grassfield]\nSigLevel = Required DatabaseOptional\nServer = https://packages.grassfield.site/stable/\$arch\n" >> /etc/pacman.conf
         pacman -Sy && pacman -Si grassfield-keyring grassfield-desktop
         pacman -Sw --noconfirm grassfield-keyring'

   (`tests/e2e.sh` is the full exercise on the local trees; it needs docker and about an hour.)
8. Beta: the same with a `-betaN` tag and `publish-beta`.

## Availability: the Worker's request quota (an owner decision, not coded)

The Worker runs on Cloudflare's free plan: about 100,000 requests a day. Past that, requests the Worker would answer fail,
and those are exactly the fixed names (`grassfield.db`, `.files`, notes, catalog, each with `.sig`): pacman cannot read the
database, so every Omarchy update fails for everyone until the next day or a paid plan. The integrator raises it with the
owner. What was done to keep the use small: `edge/wrangler.toml` has six narrow routes (the fixed names of each channel,
`grassfield.*`, `grassfield-notes.json*`, `grassfield-catalog.v1.json*`; Cloudflare patterns take a wildcard only at the
end), so packages, snapshot files, icons and the pointer never go through the Worker; they are served by the bucket's
custom domain with the headers the publisher sets at upload. Route patterns in front of an R2 custom domain are NOT
VERIFIED (step 2); `worker.js` also answers any other path it is given.

## Not verified before the first run

- R2's S3 API on `put-object --cache-control`, `--metadata`, and `aws-cli-v2` from Arch's `[extra]` in the publish container
  (the first run shows it); the pointer's conditional write is not used (serialization by the concurrency group, pointer read
  again before its write).
- That the Worker route runs in front of the bucket's custom domain (step 2).
- Cloudflare's own cache: the Worker sets the headers; Cache Rules of ADR-0033 h.5 (bypass for the fixed names and `pointer`,
  one year for immutable names, no caching of 4xx and 5xx) are still the owner's dashboard step if edge caching is wanted.
  R2 egress is free, so serving without them is correct, only slower.
- docker was denied in the session that wrote this: `tests/run-in-container.sh`, `tests/release-build.sh` and the keyring
  package build (`makepkg`, `scripts/keyring-check.sh`) were not run there; the CI `catalog.yml` and the first build run them.
