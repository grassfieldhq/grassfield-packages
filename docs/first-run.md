# First publication, step by step

Owner decision of 2026-11-04: the repository goes live at https://packages.grassfield.site now, unannounced. The legal review
stays mandatory before any announcement. Nothing below is run by an agent. The first publication is **tag `v1.0.0-rc2`, beta
only** (O15): stable stays empty until after the legal review. Steps 3 to 6 are run by the integrator under the owner's
delegation of 2026-11-04, which covers the tag, the approvals and the Worker deploy once the reviews pass; the owner remains
the required reviewer in GitHub.

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
   channel: with no release built yet it ends at "nothing to publish". Approving or rejecting is harmless. Done: the first
   run after the merge (run 41755056292) ended at "nothing to publish" on both channels, with the S3 credentials working.
2. **Owner (or integrator)**: deploy the Worker (**VERIFIED**: the integrator deployed it on 2026-11-04, version `b5e62229`,
   wrangler 4.150.0, six routes),  from this repository's `edge/`, with a Cloudflare account that owns the zone
   `grassfield.site` and the bucket `grassfield` (a token with Workers Scripts: Edit and Workers Routes: Edit, or
   `wrangler login`; nothing of it goes to GitHub):

       cd edge
       npm ci                          # wrangler 4.150.0, from package-lock.json
       npm test                        # the Worker against scripts/serve.py, no network
       npx wrangler deploy --dry-run   # shows the binding and the route, writes nothing
       npx wrangler deploy             # six routes on packages.grassfield.site (the fixed names only), R2 binding BUCKET -> grassfield

   The routes run in front of the bucket's custom domain (verified on 2026-11-04, before any publication): a route path
   (for example `.../stable/x86_64/grassfield.db` with no pointer yet) answers the Worker's 404, `content-type: text/plain;
   charset=utf-8` and `cache-control: no-store`; any other path (`nothing.pkg.tar.zst`, `pointer`) answers R2's own 404,
   `text/plain;charset=UTF-8`, `cf-cache-status: DYNAMIC`, no `cache-control`. If a redeploy ever shows a route path answered
   by R2, stop and report; do not work around it with copies of the database.
3. **Integrator (owner's delegation)**: tag grassfield (first publication: `v1.0.0-rc2`; in general `vX.Y.Z`, its `packaging/release-notes/<VERSION>.en.txt` present, `repository.conf` pinning
   fingerprint `E4921A382C349308BAA50D2F44C31B5D862EBEFA`, `packaging/pacman/` carrying the same key as `keyring/` here).
4. **Integrator**: start the build by hand (the poll is off):

       gh workflow run build.yml -R grassfieldhq/grassfield-packages --ref main -f ref=vX.Y.Z

   It builds in a throwaway Arch container (about an hour), then `test` installs the packages in a fresh container.
5. **Integrator**: approve the `release` job of each channel the tag goes to (`publish-beta` alone for `v1.0.0-rc2`; the
   `publish-stable` job finds no release build and writes nothing; `publish-stable` and `publish-beta` for a plain `vX.Y.Z`,
   after the legal review). It prepares without
   the key, signs with it (no network), checks as a client checks (keyring byte for byte `keyring/`), and uploads under
   `releases/<channel>/<version>/`, the database last.
6. **Integrator**: approve the `publish` runs (one per channel) that start when `build` completes. It checks every signature against
   `keyring/`, never goes backwards, uploads packages, then the snapshot, then writes `<channel>/x86_64/pointer` last.
7. **Checks** (anyone, from any machine):

       base=https://packages.grassfield.site/beta/x86_64     # stable only after the legal review
       curl -sI $base/grassfield.db                       # 302, Location: /beta/x86_64/snap/<id>/grassfield.db, Cache-Control: no-store (the Worker)
       curl -sI $base/pointer                             # 200, no-store (R2, from the publisher's upload metadata)
       d=$(mktemp -d)
       curl -fsSL -o $d/grassfield.db     $base/grassfield.db
       curl -fsSL -o $d/grassfield.db.sig $base/grassfield.db.sig
       gpgv --homedir $d --keyring ./keyring/grassfield.gpg $d/grassfield.db.sig $d/grassfield.db
       # expect: Good signature ... key E4921A382C349308BAA50D2F44C31B5D862EBEFA
       curl -sI $base/snap/<id>/grassfield.db             # 200, Cache-Control: public, max-age=31536000, immutable (the upload's metadata)
       # and a Last-Modified header on that response, from R2's object time: NOT VERIFIED until the first publish. pacman
       # keeps it as the database's mtime; without it a client could be answered 304 for a newer snapshot.
       curl -sI $base/snap/<id>/grassfield.db | grep -i '^last-modified'
       curl -s -o /dev/null -w '%{http_code}\n' $base/nothing.pkg.tar.zst   # 404 from R2 itself: no cache-control (not no-store)

   Install, in a throwaway Arch container (never on a real machine):

       docker run --rm -v "$PWD/keyring:/k:ro" archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0 bash -euxc '
         pacman-key --init && pacman-key --populate archlinux
         pacman-key --add /k/grassfield.gpg && pacman-key --lsign-key E4921A382C349308BAA50D2F44C31B5D862EBEFA
         printf "[grassfield]\nSigLevel = Required DatabaseOptional\nServer = https://packages.grassfield.site/beta/\$arch\n" >> /etc/pacman.conf
         pacman -Sy && pacman -Si grassfield-keyring grassfield-desktop
         pacman -Sw --noconfirm grassfield-keyring'

   (`tests/e2e.sh` is the full exercise on the local trees; it needs docker and about an hour.)
8. Stable, after the legal review: the same with a plain `vX.Y.Z` tag (it goes to stable and beta), and `base` and `Server`
   pointing at `stable`.

## Availability: the Worker's request quota (an owner decision, not coded)

The Worker runs on Cloudflare's free plan: about 100,000 requests a day. Past that, requests the Worker would answer fail,
and those are exactly the fixed names (`grassfield.db`, `.files`, notes, catalog, each with `.sig`): pacman cannot read the
database, so every Omarchy update fails for everyone until the next day or a paid plan. The integrator raises it with the
owner. What was done to keep the use small: `edge/wrangler.toml` has six narrow routes (the fixed names of each channel,
`grassfield.*`, `grassfield-notes.json*`, `grassfield-catalog.v1.json*`; Cloudflare patterns take a wildcard only at the
end), so packages, snapshot files, icons and the pointer never go through the Worker; they are served by the bucket's
custom domain with the headers the publisher sets at upload. The routes run in front of the custom domain (verified,
step 2); `worker.js` also answers any other path it is given.

## Cache rules (the owner's dashboard step)

No Cloudflare cache rule exists yet. Default edge caching may keep a 404 for a guessed future package name for a few
minutes (R2's 404 carries no `cache-control`), so a package requested just before its upload could stay "not found" briefly.
Recommendation to the owner: add ADR-0033 h.5's rule that stores no 4xx or 5xx (`status_code_ttl`), with the rules of h.5
(bypass for the fixed names and `pointer`, one year for immutable names), as a dashboard step. Nothing in this repository
creates it.

## Not verified before the first run

- R2's S3 API on `put-object --cache-control`, `--metadata`, and `aws-cli-v2` from Arch's `[extra]` in the publish container
  (the first run shows it); the pointer's conditional write is not used (serialization by the concurrency group, pointer read
  again before its write).
- `Last-Modified` on `snap/<id>/grassfield.db` as served by the custom domain (step 7), until the first publish.
- Cloudflare's own cache: the Worker sets the headers only for the fixed names; packages, snapshots and the pointer carry the
  publisher's upload metadata. The Cache Rules of ADR-0033 h.5 are still the owner's dashboard step (section above).
  R2 egress is free, so serving without them is correct, only slower.
- docker was denied in the session that wrote this: `tests/run-in-container.sh`, `tests/release-build.sh` and the keyring
  package build (`makepkg`, `scripts/keyring-check.sh`) were not run there; the CI `catalog.yml` and the first build run them.
