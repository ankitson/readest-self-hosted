# What this fork changes, and why

This repository tracks `readest/readest` and carries a deliberately small set of
changes on top. Upstream moves fast — 513 commits landed between the 2026-07-19
and 2026-09-19 merges — so the only way this stays cheap is to keep the delta
small, keep it *inventoried*, and delete our version of anything upstream
adopts.

**Before every upstream merge, read this file top to bottom.** Each entry says
what to do when upstream touches the same ground.

## The rule that matters

> When upstream ships its own fix for something we patched, **take theirs and
> delete ours** — even when ours works, even when ours shipped first.

Divergence in a file upstream edits often is a recurring tax, and the realistic
failure is not a loud conflict: it is upstream updates quietly ceasing to land.
At the 0.12.8 merge this rule removed three of our patches, one of them
committed an hour earlier. See `wiki/engineering/forking-hot-upstream-code`.

## Current delta

Regenerate the file list with `just fork-delta`.

### Self-hosting (the reason this fork exists)

| Area | Where |
|---|---|
| Runtime server switcher + custom server config | `services/customServerConfig.ts`, `services/runtimeConfig.ts`, `components/settings/ServerSettingsPanel.tsx` |
| Server switcher on the sign-in screen | `app/auth/page.tsx` — re-place it inside whatever layout upstream currently uses |
| Updater pointed at our releases, not upstream's | `helpers/updater.ts`, `hooks/useAutoUpdateCheck.ts` |
| KOReader plugin self-update disabled | `apps/readest.koplugin/` |
| `repo@commit` in About | `components/AboutWindow.tsx`, `utils/build.ts` — sits *under* upstream's copyable version label, never replacing it |

### Reading-recency clock (`last_read_at`)

Upstream has no equivalent column. Since #6470 (merged 2026-10-08) upstream
treats `updated_at` as its Date Read key and stops grouping, tagging and
metadata edits from bumping it, which covers most of what this clock was for.
It still does not separate imports or server-side scripts from reading, which
our migration tools rely on, so we kept ours. Revisit at the next merge: if
nothing on the server writes books outside the app any more, dropping this is
the cheaper path.

`docker/volumes/db/init/schema.sql`, `docker/volumes/db/migrations/901_add_last_read_at.sql`,
`types/book.ts`, `types/records.ts`, `utils/transform.ts`,
`services/sync/file/merge.ts`, `app/library/utils/libraryUtils.ts`
(`getBookDateReadAt`), `services/bookshelves/presentation.ts`
(`generateBookshelfItems`, moved there from `BookshelfItem.tsx` upstream),
`store/bookDataStore.ts`, `store/libraryStore.ts`.

If upstream ever adds its own reading-recency column, drop all of this and take
theirs.

### Apple Books annotation import

`services/annotation/providers/appleBooks.ts`,
`app/reader/hooks/useAppleBooksAnnotationImport.ts`, plus rows in
`Annotator.tsx` / `ImportAnnotationsDialog.tsx`. Upstream now ships Readest and
ReadEra importers in the same dialog; ours sits alongside them.
`onImportAppleBooks` is **optional** so upstream's own dialog tests construct
the component unchanged — keep it that way.

### Author lists render "A, B, C"

`utils/book.ts`: `listFormater` takes a `type` and `formatAuthors` passes
`'unit'`. A credit line is a list, not prose. Two lines; re-apply by hand if a
merge eats them.

### Build and release

Unsigned-IPA iOS build, desktop auto-update, Docker image with build
provenance, Vercel-deploy skip when secrets are absent, Android job disabled.
All under `.github/workflows/` and `scripts/`.

The iOS build runs `tauri ios build --no-sign` (since 2026-10-09).
`scripts/sideload/prepare-project.py` first strips what a free personal team
cannot sign (app extensions, entitlements); the CLI then does the frontend
build, the Info.plist merge, cargo and the archive. The sideload bundle id is
stamped onto the built Info.plist afterwards, because the config identifier
also names the app's data directory and must not change.

`scripts/sideload/verify-ipa.py` runs in CI before publishing and fails the
build if the IPA drifts from the Tauri config's plist sources, so upstream
additions are checked without anyone having to remember. Its `ALLOWED` and
`UNREGISTERED_EXTENSIONS` lists are the only sanctioned deviations.

The old path that drove cargo and `xcodebuild` by hand stays selectable
(`SIDELOAD_PIPELINE=bypass`) as a fallback for one release. It had to
reproduce every CLI step and twice shipped builds that missed one: a dev-mode
binary, then an unmerged Info.plist that turned into a black screen once tao
0.37 needed a scene manifest. Delete it once the CLI pipeline has been on
devices for a release.

Desktop builds (`build-desktop.yml` wrapping `build-selfhost.yml`) are
versioned `<package.json base>-selfhost.<run>`, so the updater always sees a
newer semver. The Linux leg copies upstream's `release.yml` Linux steps (CEF
tauri CLI rev, staged runtime libraries, AppImage content check); when an
upstream merge changes those steps, carry the change over, or the AppImage
stops bundling as it did after the 0.12.8 merge.

### Migrations

**Fork-local migrations use the 9xx range.** `900_local_plan_claim_hook.sql`,
`901_add_last_read_at.sql`. Never take a number upstream might use — 901 was
`019` and collided head-on with upstream's `019_stat_pages_upsert_rpc.sql`.

## Deliberately NOT carried

| Dropped | Superseded by |
|---|---|
| `resolveMetadataMerge` / `pickFresherMetadata` combined clock | upstream's split metadata + `group_updated_at` clocks (#5438, #5911, #5912) |
| Stats-push URI-length fix | upstream's `upsert_stat_pages(jsonb)` RPC (#5832) — needs migration `019_stat_pages_upsert_rpc.sql` applied server-side |
| `getBookWithUpdatedMetadata` freezing `updatedAt` | upstream advances the row clock and merges on `metadata_updated_at`; our Date Read is protected by `last_read_at` instead |
| `metadata-sync-helper.test.ts` | upstream's `metadata-sync-helpers`, `sync-group-merge`, `group-clock` tests |

## Merge procedure

```bash
git fetch readest
git checkout -b merge/upstream-$(date +%Y%m%d)
git merge readest/main
```

Then, in this order:

1. **Read this file.** For each conflict, decide *drop ours* or *keep ours*
   against the inventory above.
2. **Never `git checkout --theirs` a file that also carries an unrelated change
   of ours.** It takes the whole upstream file and silently discards our
   clean-merged hunks in it. At the 0.12.8 merge that ate the author-list fix,
   the file-sync `lastReadAt` and `getBookDateReadAt` before the typechecker
   caught it. Resolve those files hunk by hunk instead.
3. `git submodule update --init --recursive && pnpm install`
4. `npx tsc --noEmit -p apps/readest-app/tsconfig.json` — **this is the step
   that catches silent auto-merges.** Git merged `metadataUpdatedAt` into
   `book.ts`, `records.ts` and `transform.ts` *twice each* with no conflict
   markers; only the typechecker saw it.
5. `pnpm --filter @readest/readest-app test:pr:web:unit`
6. `just fork-delta` and update this file if the delta changed.
7. Apply any new upstream migrations server-side **before** deploying the image.

## Known drift

- `.github/workflows/sync-upstream.yml` runs nightly against the
  **`selfhost-main`** branch, while day-to-day work happens on `main`. Either
  point it at `main` or stop treating `main` as the integration branch; as it
  stands the automation maintains a branch nobody merges from.
- `apps/readest-app/src/__tests__/libs/pdf-worker-compat.test.ts` fails
  typecheck. The file is byte-identical to upstream's — their issue, not ours.
