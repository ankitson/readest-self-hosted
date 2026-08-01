# Restore Official Readest Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every self-hosted application icon and Web icon declaration match official Readest `v0.11.20` while preserving the self-hosted product identity and behavior.

**Architecture:** Treat upstream tag `1df1505fc5033fc949463c9908f2d53bd0fbdfa6` as the immutable asset source. Restore binary assets byte-for-byte, minimally edit the two Web metadata files, remove the three self-host-only PWA images, and prove equality with Git tree and SHA-256 comparisons. Validate the local build first, then run an artifact-free Playwright smoke test against an operator-provided live library URL.

**Tech Stack:** Git, PNG/ICO/ICNS application assets, Next.js metadata, Web App Manifest JSON, pnpm, Vitest, Biome, Tauri, Playwright CLI.

## Global Constraints

- Official source tag: `refs/codex/upstream-v0.11.20`, commit `1df1505fc5033fc949463c9908f2d53bd0fbdfa6`.
- Preserve `Readest Selfhost`, `com.readest.selfhost`, the self-host updater/signing configuration, and custom server switching.
- Do not regenerate, resize, optimize, or recompress official binary icons.
- Do not change browser-extension icons, document icons, UI glyphs, or unrelated images.
- Do not write the operator-provided live library URL, credentials, browser state, traces, screenshots, or generated E2E files into the repository.
- Known clean-baseline exception: `src/__tests__/document/series-metadata.test.ts` has one pre-existing nested-CBZ failure in both the main checkout and isolated worktree; no additional test failure is acceptable.
- Work only in `/home/luoji/codex/readest-fix-restore-official-icons` on branch `fix/restore-official-icons`.

---

### Task 1: Restore the upstream icon surface

**Files:**

- Modify: `apps/readest-app/public/apple-touch-icon.png`
- Delete: `apps/readest-app/public/icon-192.png`
- Delete: `apps/readest-app/public/icon-256.png`
- Delete: `apps/readest-app/public/icon-512.png`
- Modify: `apps/readest-app/public/manifest.json`
- Modify: `apps/readest-app/src/app/layout.tsx`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-hdpi/ic_launcher.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-hdpi/ic_launcher_monochrome.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-hdpi/ic_launcher_round.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-mdpi/ic_launcher_monochrome.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-xhdpi/ic_launcher_monochrome.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-xxhdpi/ic_launcher_monochrome.png`
- Modify: `apps/readest-app/src-tauri/icons/android/mipmap-xxxhdpi/ic_launcher_monochrome.png`
- Verify unchanged/equal: all other files under `apps/readest-app/src-tauri/icons/`
- Verify unchanged/equal: `apps/readest-app/public/favicon.ico`
- Verify unchanged/equal: `apps/readest-app/public/icon.png`
- Verify unchanged/equal: `apps/readest-app/public/icon-tiny.png`
- Verify unchanged/equal: `fastlane/metadata/android/en-US/images/icon.png`
- Verify unchanged/equal: `data/icons/readest-book.png`

**Interfaces:**

- Consumes: official icon assets and metadata from `refs/codex/upstream-v0.11.20`.
- Produces: a working tree whose complete scoped icon surface is identical to the official tag.

- [ ] **Step 1: Run the pre-change comparison and verify it fails for the expected files**

```bash
git diff --exit-code refs/codex/upstream-v0.11.20 -- \
  apps/readest-app/public/apple-touch-icon.png \
  apps/readest-app/public/favicon.ico \
  apps/readest-app/public/icon.png \
  apps/readest-app/public/icon-tiny.png \
  apps/readest-app/public/icon-192.png \
  apps/readest-app/public/icon-256.png \
  apps/readest-app/public/icon-512.png \
  apps/readest-app/public/manifest.json \
  apps/readest-app/src/app/layout.tsx \
  apps/readest-app/src-tauri/icons \
  fastlane/metadata/android/en-US/images/icon.png \
  data/icons/readest-book.png
```

Expected: non-zero exit with only the three extra PWA icons, `apple-touch-icon.png`, `manifest.json`, `layout.tsx`, and seven Android launcher/monochrome assets reported.

- [ ] **Step 2: Restore official binary assets without recompression**

```bash
git restore --source=refs/codex/upstream-v0.11.20 -- \
  apps/readest-app/public/apple-touch-icon.png \
  apps/readest-app/src-tauri/icons \
  fastlane/metadata/android/en-US/images/icon.png \
  data/icons/readest-book.png

git rm \
  apps/readest-app/public/icon-192.png \
  apps/readest-app/public/icon-256.png \
  apps/readest-app/public/icon-512.png
```

Expected: the official binary blobs are staged as modifications and the three upstream-absent PWA files are staged as deletions.

- [ ] **Step 3: Restore the official Web App Manifest icon declarations**

Apply this exact change to `apps/readest-app/public/manifest.json`:

```diff
       "icons": [
         {
-          "src": "/icon-192.png",
+          "src": "/icon.png",
           "type": "image/png",
-          "sizes": "192x192",
-          "purpose": "any"
+          "sizes": "192x192"
         },
         {
-          "src": "/icon-256.png",
+          "src": "/icon.png",
           "type": "image/png",
-          "sizes": "256x256",
-          "purpose": "any"
+          "sizes": "256x256"
         },
         {
-          "src": "/icon-512.png",
+          "src": "/icon.png",
           "type": "image/png",
-          "sizes": "512x512",
-          "purpose": "any"
+          "sizes": "512x512"
         }
       ],
```

- [ ] **Step 4: Restore the official Next.js icon metadata**

Apply this exact change to `apps/readest-app/src/app/layout.tsx`:

```diff
   icons: {
-    icon: [{ url: '/icon-512.png', sizes: '512x512', type: 'image/png' }, { url: '/favicon.ico' }],
-    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
+    icon: [{ url: '/icon.png' }, { url: '/favicon.ico' }],
+    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180' }],
   },
```

- [ ] **Step 5: Run the post-change equality check**

```bash
git diff --exit-code refs/codex/upstream-v0.11.20 -- \
  apps/readest-app/public/apple-touch-icon.png \
  apps/readest-app/public/favicon.ico \
  apps/readest-app/public/icon.png \
  apps/readest-app/public/icon-tiny.png \
  apps/readest-app/public/icon-192.png \
  apps/readest-app/public/icon-256.png \
  apps/readest-app/public/icon-512.png \
  apps/readest-app/public/manifest.json \
  apps/readest-app/src/app/layout.tsx \
  apps/readest-app/src-tauri/icons \
  fastlane/metadata/android/en-US/images/icon.png \
  data/icons/readest-book.png
```

Expected: exit 0 with no output.

- [ ] **Step 6: Verify self-hosted configuration did not change**

```bash
git diff --exit-code HEAD -- \
  apps/readest-app/scripts/patch-tauri-selfhost.mjs \
  apps/readest-app/src-tauri/tauri.conf.json \
  apps/readest-app/src/services/customServerConfig.ts \
  apps/readest-app/src/services/runtimeConfig.ts \
  .github/workflows/build-selfhost.yml \
  .github/workflows/release-selfhost.yml
```

Expected: exit 0 with no output.

- [ ] **Step 7: Commit the official icon restoration**

```bash
git add \
  apps/readest-app/public \
  apps/readest-app/src/app/layout.tsx \
  apps/readest-app/src-tauri/icons
git commit -m "fix: restore official Readest icons"
```

Expected: one implementation commit containing only icon assets and icon declarations.

---

### Task 2: Validate assets, source checks, and production Web build

**Files:**

- Verify: `apps/readest-app/public/manifest.json`
- Verify: `apps/readest-app/src/app/layout.tsx`
- Verify: the latest implementation commit only
- Temporary output only: `/tmp/readest-icon-vitest.log`

**Interfaces:**

- Consumes: the official icon surface from Task 1.
- Produces: fresh lint, build, and test evidence with no new failures.

- [ ] **Step 1: Validate JSON, formatting, and icon references**

```bash
jq -e '.icons | length == 3 and all(.src == "/icon.png")' \
  apps/readest-app/public/manifest.json

test -z "$(rg -n 'icon-(192|256|512)\.png' \
  apps/readest-app/public/manifest.json \
  apps/readest-app/src/app/layout.tsx || true)"

icon_commit="$(git rev-parse ':/^fix: restore official Readest icons$')"
git diff --check "$icon_commit^..$icon_commit"
```

Expected: all commands exit 0 and no removed icon filename remains referenced.

- [ ] **Step 2: Run full lint**

```bash
GOMEMLIMIT=1600MiB pnpm lint
```

Expected: TypeScript, Biome, and LuaJIT checks exit 0.

- [ ] **Step 3: Run a production Web build**

```bash
NODE_OPTIONS=--max-old-space-size=4096 pnpm --filter @readest/readest-app build-web
```

Expected: Next.js production build exits 0.

- [ ] **Step 4: Re-run the full unit suite and prove no regression beyond the known baseline**

```bash
set +e
pnpm --filter @readest/readest-app exec vitest run 2>&1 | tee /tmp/readest-icon-vitest.log
status=${PIPESTATUS[0]}
set -e

test "$status" -eq 1
test "$(rg -c '^ FAIL ' /tmp/readest-icon-vitest.log)" -eq 1
rg -q 'src/__tests__/document/series-metadata.test.ts' /tmp/readest-icon-vitest.log
rg -q '1 failed .* 299 passed .* 2 skipped' /tmp/readest-icon-vitest.log
rm -f /tmp/readest-icon-vitest.log
```

Expected: exactly the pre-existing nested-CBZ test fails; 299 test files pass and no new failure appears.

- [ ] **Step 5: Audit the committed implementation paths**

```bash
icon_commit="$(git rev-parse ':/^fix: restore official Readest icons$')"
git diff-tree --no-commit-id --name-only -r "$icon_commit" | sort
git status --short --branch
```

Expected: the diff contains only the icon-related paths listed in Task 1, and the worktree is clean.

---

### Task 3: Run local and live-library Playwright smoke tests without repository artifacts

**Files:**

- Repository files: none.
- Runtime input: `READEST_E2E_BASE_URL`, supplied in the shell only.
- Browser artifacts: none; do not call screenshot, tracing, PDF, or state-save commands.

**Interfaces:**

- Consumes: the production Web build from Task 2 and the operator-provided live library URL.
- Produces: terminal-only evidence that local icon metadata works and the live library remains reachable.

- [ ] **Step 1: Start the built local Web app**

```bash
pnpm --filter @readest/readest-app start-web
```

Expected: the production server listens on `http://localhost:3000` in a managed terminal session.

- [ ] **Step 2: Open the local app and inspect the icon surface**

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
export PLAYWRIGHT_CLI_SESSION=readest-icon-local

"$PWCLI" open http://localhost:3000
"$PWCLI" snapshot
"$PWCLI" eval "document.querySelector('link[rel~=\"icon\"]')?.getAttribute('href')"
"$PWCLI" eval "document.querySelector('link[rel=\"manifest\"]')?.getAttribute('href')"
"$PWCLI" eval "async () => { const r = await fetch('/manifest.json'); const m = await r.json(); return { status: r.status, icons: m.icons }; }"
"$PWCLI" close
```

Expected: the local page loads, icon metadata references `/icon.png` and `/favicon.ico`, and all three manifest icon entries reference `/icon.png`.

- [ ] **Step 3: Open the operator-provided live library without persisting its URL**

Set `READEST_E2E_BASE_URL` in the active shell from the operator-provided value. Do not place the assignment in a repository file, shell history helper, Git configuration, or plan update.

```bash
export PLAYWRIGHT_CLI_SESSION=readest-live-smoke
"$PWCLI" open "$READEST_E2E_BASE_URL"
"$PWCLI" snapshot
"$PWCLI" eval "({ title: document.title, url: location.origin, ready: document.readyState })"
"$PWCLI" console error
"$PWCLI" network
```

Expected: the live app reaches `readyState=complete`, renders the Readest authentication or library surface, and has no icon-related request failure. If authentication is required for the requested library flow, accept credentials interactively at execution time only and never save storage state.

- [ ] **Step 4: Exercise the available library flow and close the ephemeral session**

Use element references from the fresh snapshot for any available login/library navigation. Re-run `snapshot` after every navigation or modal transition. Then close the session:

```bash
"$PWCLI" close
unset PLAYWRIGHT_CLI_SESSION
unset READEST_E2E_BASE_URL
```

Expected: the available library flow completes without an icon/manifest regression, and no browser state is intentionally persisted.

- [ ] **Step 5: Prove E2E execution did not modify the repository**

```bash
git status --short --branch
```

Expected: clean worktree on `fix/restore-official-icons`.

---

### Task 4: Final evidence and handoff

**Files:**

- Verify only: Git history and worktree.

**Interfaces:**

- Consumes: committed icon restoration plus validation evidence.
- Produces: a concise handoff with exact commits, checks, baseline exception, and E2E scope.

- [ ] **Step 1: Inspect final history and diff summary**

```bash
git log --oneline --decorate -3
git diff --stat origin/main..HEAD
git status --short --branch
```

Expected: the design/plan and icon restoration commits are present, the diff is limited to documentation and icon-related paths, and the worktree is clean.

- [ ] **Step 2: Report verification evidence**

Report:

- official source tag and commit;
- exact icon equality result;
- lint and production Web build results;
- unit-test count and the unchanged nested-CBZ baseline failure;
- local Playwright icon/manifest result;
- live-library smoke-test scope and result without disclosing the runtime URL or credentials;
- branch and commit IDs;
- confirmation that no remote branch, tag, or release was modified.
