# Stable Selfhost Upstream Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebase the Readest Selfhost fork onto official Readest `v0.11.20`, preserve all selfhost behavior and official icons, then update the automation so future selfhost releases are produced only after a new strict stable upstream tag appears.

**Architecture:** Keep the selfhost changes as a replayable commit stack on top of an immutable upstream stable-tag commit. A scheduled GitHub Actions workflow fetches upstream tags into a private namespace, selects only `vMAJOR.MINOR.PATCH`, rebases and verifies a candidate, then atomically mirrors `main` and `selfhost-main` with explicit leases and creates `selfhost-vMAJOR.MINOR.PATCH`. The selfhost release workflow alone consumes that tag; the official Readest release workflow is guarded so it cannot run in the fork.

**Tech Stack:** Git, Bash, GitHub Actions, Node.js 24, pnpm 11, Next.js 16, Vitest, Biome, Rust/Tauri, Playwright.

## Global Constraints

- Current stable target: `v0.11.20`, commit `1df1505fc5033fc949463c9908f2d53bd0fbdfa6`, local ref `refs/codex/upstream-v0.11.20`.
- Follow only strict stable tags matching `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`; ignore prereleases, nightly builds, and `upstream/main` development commits.
- Preserve `Readest Selfhost`, `com.readest.selfhost`, the independent updater public key/signing configuration, the fork updater endpoint, and custom server switching.
- Preserve the official Readest icon surface already restored by commit `bd9e4b2b`; all scoped icon assets and declarations must remain identical to `v0.11.20`.
- A failed rebase, dependency install, lint, test, safety scan, Rust check, or Web build must prevent every branch and tag push.
- Update `main` and `selfhost-main` only after all verification passes, in one atomic push using explicit `--force-with-lease` expectations.
- Create `selfhost-vMAJOR.MINOR.PATCH` automatically only when it is absent; never move an existing selfhost release tag.
- Do not push, merge, or create a pull request during this local implementation session.
- Do not write the operator-provided live-library URL, credentials, browser state, screenshots, traces, or generated E2E files into the repository.
- Run memory-sensitive Node commands with `NODE_OPTIONS=--max-old-space-size=4096`.
- Work only in `/home/luoji/codex/readest-fix-restore-official-icons` on branch `fix/restore-official-icons`.

---

### Task 1: Replay the complete selfhost stack onto Readest v0.11.20

**Files:**

- Rebase: every commit after `4d1205fdf5297f9841e52e97ddae658d696ab008`.
- Preserve: all selfhost paths reported by `git diff --name-status 4d1205fd..HEAD`.
- Preserve exactly: the icon scope in `docs/superpowers/specs/2026-08-01-restore-official-icons-design.md`.
- Add: `docs/superpowers/plans/2026-08-01-sync-stable-selfhost.md`.

**Interfaces:**

- Consumes: the 30 local selfhost/icon commits and immutable upstream ref `refs/codex/upstream-v0.11.20`.
- Produces: the same selfhost commit stack based directly on official `v0.11.20`.

- [ ] **Step 1: Verify the immutable target and clean starting state**

```bash
test "$(git rev-parse refs/codex/upstream-v0.11.20^{commit})" = \
  "1df1505fc5033fc949463c9908f2d53bd0fbdfa6"
test -z "$(git status --porcelain --untracked-files=no)"
```

Expected: both assertions exit 0; only this untracked plan may be present.

- [ ] **Step 2: Commit this execution plan before rewriting history**

```bash
git add docs/superpowers/plans/2026-08-01-sync-stable-selfhost.md
git commit -m "docs: plan stable selfhost sync"
git branch backup/pre-v0.11.20-selfhost-sync HEAD
```

Expected: one documentation-only commit and a backup branch at the pre-rebase stack.

- [ ] **Step 3: Rebase the full local stack onto the stable tag**

```bash
git rebase --onto refs/codex/upstream-v0.11.20 \
  4d1205fdf5297f9841e52e97ddae658d696ab008 \
  fix/restore-official-icons
```

Expected: Git replays all selfhost, CI, documentation, and official-icon commits. For each conflict, preserve the upstream `v0.11.20` implementation as the base and reapply only the selfhost behavior named in Global Constraints; do not retain superseded upstream code merely to minimize the diff.

- [ ] **Step 4: Prove the new ancestry, version, identity, and icon surface**

```bash
git merge-base --is-ancestor refs/codex/upstream-v0.11.20 HEAD
test "$(node -p "require('./apps/readest-app/package.json').version")" = "0.11.20"
test "$(jq -r .productName apps/readest-app/src-tauri/tauri.conf.json)" = "Readest Selfhost"
test "$(jq -r .identifier apps/readest-app/src-tauri/tauri.conf.json)" = "com.readest.selfhost"
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

Expected: every command exits 0; no icon diff remains.

---

### Task 2: Restore v0.11.20 dependencies and repair selfhost compatibility

**Files:**

- Update only when required by upstream API changes: existing selfhost files under `apps/readest-app/src/` and their matching tests under `apps/readest-app/src/__tests__/`.
- Verify: `.gitmodules`, all recursive submodule gitlinks, `pnpm-lock.yaml`, and generated vendor assets ignored by Git.

**Interfaces:**

- Consumes: the rebased tree from Task 1.
- Produces: selfhost server selection, authentication, storage, updater, and settings code compatible with v0.11.20.

- [ ] **Step 1: Synchronize submodules and dependencies**

```bash
git submodule sync --recursive
git submodule update --init --recursive
pnpm install --frozen-lockfile
pnpm --filter @readest/readest-app setup-vendors
```

Expected: each command exits 0 and `git status --short` contains no generated vendor changes.

- [ ] **Step 2: Run focused selfhost tests before any compatibility edit**

```bash
NODE_OPTIONS=--max-old-space-size=4096 pnpm --filter @readest/readest-app test --run \
  src/__tests__/services/customServerConfig.test.ts \
  src/__tests__/services/environment.test.ts \
  src/__tests__/helpers/auth.test.ts \
  src/__tests__/helpers/updater.test.ts \
  src/__tests__/services/command-registry-extended.test.ts
```

Expected: all focused tests pass. If an upstream interface broke selfhost behavior, add one minimal failing assertion to the existing matching test, observe the expected failure, make the smallest compatibility edit, and rerun this exact command until green.

- [ ] **Step 3: Verify the updater patch using a temporary configuration**

```bash
tmp_config="$(mktemp)"
cp apps/readest-app/src-tauri/tauri.conf.json "$tmp_config"
TAURI_CONF_PATH="$tmp_config" node apps/readest-app/scripts/patch-tauri-selfhost.mjs
jq -e '
  .productName == "Readest Selfhost" and
  .identifier == "com.readest.selfhost" and
  .plugins.updater.endpoints == ["https://github.com/luoji12103/readest-self-hosted/releases/latest/download/latest.json"] and
  (.plugins.updater.pubkey | length > 31)
' "$tmp_config"
rm -f "$tmp_config"
```

Expected: the temporary config is patched, the fork endpoint assertion passes, and no tracked file changes.

- [ ] **Step 4: Commit only if compatibility edits were necessary**

```bash
git diff --check
git add apps/readest-app/src apps/readest-app/src-tauri/tauri.conf.json
git diff --cached --quiet || git commit -m "fix: adapt selfhost client to Readest 0.11.20"
```

Expected: no commit when the replayed selfhost code already passes; otherwise one test-backed compatibility commit.

---

### Task 3: Implement and test strict stable-tag selection

**Files:**

- Create: `scripts/select-latest-stable-tag.sh`.
- Create: `scripts/test-select-latest-stable-tag.sh`.

**Interfaces:**

- Consumes: tag names, one per line on standard input.
- Produces: exactly one highest strict stable tag on standard output, or a non-zero exit when none exists.

- [ ] **Step 1: Write the executable failing test**

Create `scripts/test-select-latest-stable-tag.sh` with these cases:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SELECTOR="$ROOT_DIR/scripts/select-latest-stable-tag.sh"

actual="$(printf '%s\n' v0.11.9 v0.11.20 v0.12.0-rc.1 nightly v1.0.0 | "$SELECTOR")"
test "$actual" = "v1.0.0"

actual="$(printf '%s\n' v2.9.0 v2.10.0 v10.0.0 v01.2.3 v1.02.3 | "$SELECTOR")"
test "$actual" = "v10.0.0"

if printf '%s\n' v1.2.3-beta.1 latest selfhost-v1.2.3 | "$SELECTOR" >/dev/null 2>&1; then
  echo "selector accepted input without a strict stable tag" >&2
  exit 1
fi

echo "Stable tag selector tests passed."
```

- [ ] **Step 2: Run the test and observe the missing-selector failure**

```bash
chmod +x scripts/test-select-latest-stable-tag.sh
bash scripts/test-select-latest-stable-tag.sh
```

Expected: non-zero exit because `scripts/select-latest-stable-tag.sh` does not exist.

- [ ] **Step 3: Add the minimal stable selector**

Create `scripts/select-latest-stable-tag.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

stable_tags=()
while IFS= read -r tag; do
  if [[ "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    stable_tags+=("$tag")
  fi
done

if [ "${#stable_tags[@]}" -eq 0 ]; then
  echo "No strict stable upstream tag was found." >&2
  exit 1
fi

printf '%s\n' "${stable_tags[@]}" | sort -V | tail -n 1
```

- [ ] **Step 4: Verify green and commit**

```bash
chmod +x scripts/select-latest-stable-tag.sh
bash scripts/test-select-latest-stable-tag.sh
git add scripts/select-latest-stable-tag.sh scripts/test-select-latest-stable-tag.sh
git commit -m "ci: select strict stable upstream tags"
```

Expected: `Stable tag selector tests passed.` followed by one focused commit.

---

### Task 4: Replace daily main rebasing with verified stable-release synchronization

**Files:**

- Modify: `.github/workflows/sync-upstream.yml`.
- Modify: `.github/workflows/build-selfhost.yml`.
- Modify: `.github/workflows/release.yml`.
- Modify: `.github/workflows/selfhost-safety.yml`.
- Modify: `scripts/scan-public-fork-safety.sh`.
- Create: `scripts/test-sync-upstream-workflow.sh`.

**Interfaces:**

- Consumes: upstream namespaced tags, `origin/main`, `origin/selfhost-main`, repository signing secrets, and the stable selector from Task 3.
- Produces: a verified candidate mirrored to both branches plus an immutable `selfhost-vMAJOR.MINOR.PATCH` tag that triggers exactly one selfhost release workflow.

- [ ] **Step 1: Write a failing workflow contract test**

Create `scripts/test-sync-upstream-workflow.sh` that asserts all of these exact contracts with `rg -q` and exits non-zero on the current workflow:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

sync=.github/workflows/sync-upstream.yml
build=.github/workflows/build-selfhost.yml
release=.github/workflows/release.yml

rg -q "refs/tags/upstream/v\*" "$sync"
rg -q "scripts/select-latest-stable-tag\.sh" "$sync"
rg -q "git merge-base --is-ancestor" "$sync"
rg -q "git rebase --onto" "$sync"
rg -q -- "--atomic" "$sync"
rg -q -- "--force-with-lease=refs/heads/main:" "$sync"
rg -q -- "--force-with-lease=refs/heads/selfhost-main:" "$sync"
rg -q 'HEAD:refs/tags/selfhost-\$latest_tag' "$sync"
rg -q "pnpm lint" "$sync"
rg -q "pnpm --filter @readest/readest-app test --run" "$sync"
rg -q "pnpm --filter @readest/readest-app build-web" "$sync"
! rg -q "git rebase upstream/main" "$sync"
! sed -n '/^  push:/,/^permissions:/p' "$build" | rg -q .
sed -n '/^  get-release:/,/^  update-release:/p' "$release" | \
  rg -q "if: github.repository == 'readest/readest'"

echo "Stable sync workflow contract tests passed."
```

- [ ] **Step 2: Run the contract test and observe the policy failure**

```bash
chmod +x scripts/test-sync-upstream-workflow.sh
bash scripts/test-sync-upstream-workflow.sh
```

Expected: non-zero exit because the current workflow rebases onto `upstream/main`, lacks namespaced stable-tag selection, does not use leases, and allows duplicate tag-triggered builds.

- [ ] **Step 3: Implement the stable sync transaction**

Replace the rebase step in `.github/workflows/sync-upstream.yml` with a candidate flow that performs these commands in this order:

```bash
git remote add upstream https://github.com/readest/readest.git
git fetch --no-tags upstream main:refs/remotes/upstream/main
git fetch --no-recurse-submodules upstream '+refs/tags/v*:refs/tags/upstream/v*'
git fetch --no-tags origin main selfhost-main
git fetch --no-recurse-submodules origin '+refs/tags/selfhost-v*:refs/tags/origin/selfhost-v*'

latest_tag="$(git for-each-ref --format='%(refname:strip=3)' refs/tags/upstream | \
  bash scripts/select-latest-stable-tag.sh)"
target_ref="refs/tags/upstream/${latest_tag}"
target_commit="$(git rev-parse "${target_ref}^{commit}")"
git merge-base --is-ancestor "$target_commit" refs/remotes/upstream/main

git checkout -B sync-candidate refs/remotes/origin/selfhost-main
if ! git merge-base --is-ancestor "$target_commit" HEAD; then
  current_tag="$(
    while IFS= read -r tag; do
      if git merge-base --is-ancestor "refs/tags/upstream/${tag}^{commit}" HEAD; then
        printf '%s\n' "$tag"
      fi
    done < <(git for-each-ref --format='%(refname:strip=3)' refs/tags/upstream) |
      bash scripts/select-latest-stable-tag.sh
  )"
  git rebase --onto "$target_commit" "refs/tags/upstream/${current_tag}^{commit}"
fi
```

Store the original `origin/main` and `origin/selfhost-main` object IDs before verification. After dependency setup, focused config tests, the public-fork scan, stable-sync contract tests, `pnpm lint`, the full unit suite, Rust format/Clippy, and the Web production build all pass, update a new stable version with this one transaction:

```bash
git push --atomic origin \
  "--force-with-lease=refs/heads/main:${expected_main}" \
  "--force-with-lease=refs/heads/selfhost-main:${expected_selfhost}" \
  HEAD:refs/heads/main \
  HEAD:refs/heads/selfhost-main \
  HEAD:refs/tags/selfhost-$latest_tag
```

If the stable commit is already an ancestor and the corresponding selfhost tag already points at `HEAD`, exit without pushing. If the branch is current but the tag is missing, run all verification and push only `HEAD:refs/tags/selfhost-$latest_tag`. If the remote selfhost tag exists at another commit, fail without moving it.

- [ ] **Step 4: Ensure a selfhost tag starts exactly one release pipeline**

Remove the `push.tags` trigger from `.github/workflows/build-selfhost.yml`; keep `workflow_call` and `workflow_dispatch`. Keep the strict `selfhost-v*` tag trigger in `.github/workflows/release-selfhost.yml`, which calls the build workflow and publishes the fork-owned `latest.json`.

- [ ] **Step 5: Guard the official release workflow in the fork**

Add this job condition to `.github/workflows/release.yml` under `get-release`:

```yaml
    if: github.repository == 'readest/readest'
```

Expected: all downstream official release jobs skip because each depends on `get-release`; the same workflow remains functional in the official repository.

- [ ] **Step 6: Extend safety checks and run the contract tests**

Make `scripts/scan-public-fork-safety.sh` reject a sync workflow that follows `upstream/main`, lacks strict-tag/lease/atomic-push markers, or lacks the official release guard. Add both shell tests to `.github/workflows/selfhost-safety.yml` before the existing public-fork scan.

```bash
bash scripts/test-select-latest-stable-tag.sh
bash scripts/test-sync-upstream-workflow.sh
bash scripts/scan-public-fork-safety.sh
```

Expected: all three commands exit 0.

- [ ] **Step 7: Commit the stable-release automation**

```bash
git add \
  .github/workflows/sync-upstream.yml \
  .github/workflows/build-selfhost.yml \
  .github/workflows/release.yml \
  .github/workflows/selfhost-safety.yml \
  scripts/scan-public-fork-safety.sh \
  scripts/test-sync-upstream-workflow.sh
git commit -m "ci: sync selfhost on stable releases"
```

Expected: one commit containing only automation and its executable safety tests.

---

### Task 5: Run the complete local quality gate

**Files:**

- Verify: the entire rebased tree.
- Temporary logs only: `/tmp/readest-selfhost-*.log`, removed after inspection.

**Interfaces:**

- Consumes: the v0.11.20 selfhost client and stable-release automation.
- Produces: fresh evidence that the repository is safe, buildable, and ready for user-controlled integration.

- [ ] **Step 1: Run safety, formatting, lint, and focused selfhost checks**

```bash
bash scripts/test-select-latest-stable-tag.sh
bash scripts/test-sync-upstream-workflow.sh
bash scripts/scan-public-fork-safety.sh
git diff --check refs/codex/upstream-v0.11.20..HEAD
NODE_OPTIONS=--max-old-space-size=4096 pnpm lint
pnpm fmt:check
pnpm clippy:check
```

Expected: every command exits 0 with no warning promoted to failure.

- [ ] **Step 2: Run the complete unit suite**

```bash
NODE_OPTIONS=--max-old-space-size=4096 \
  pnpm --filter @readest/readest-app test --run
```

Expected: exit 0. The prior nested-CBZ failure must be reevaluated against the updated `foliate-js` submodule rather than carried forward as an assumed exception.

- [ ] **Step 3: Run a production Web build**

```bash
NODE_OPTIONS=--max-old-space-size=4096 \
  pnpm --filter @readest/readest-app build-web
```

Expected: Next.js production build exits 0.

- [ ] **Step 4: Recheck stable ancestry, identity, updater, icons, and repository cleanliness**

```bash
git merge-base --is-ancestor refs/codex/upstream-v0.11.20 HEAD
git diff --exit-code refs/codex/upstream-v0.11.20 -- \
  apps/readest-app/public/manifest.json \
  apps/readest-app/src/app/layout.tsx \
  apps/readest-app/src-tauri/icons \
  fastlane/metadata/android/en-US/images/icon.png \
  data/icons/readest-book.png
bash scripts/scan-public-fork-safety.sh
git status --short --branch
```

Expected: all commands exit 0 and the worktree is clean.

---

### Task 6: Run an artifact-free real-library smoke test

**Files:**

- Repository files: none.
- Runtime-only input: `READEST_E2E_BASE_URL` supplied in the active process.
- Browser artifacts: none.

**Interfaces:**

- Consumes: the operator-provided selfhost library URL and an ephemeral Playwright Firefox session.
- Produces: terminal-only evidence that the deployed library loads, lists books, and opens a reader after the v0.11.20 adaptation.

- [ ] **Step 1: Start an ephemeral browser session using only a process environment variable**

```bash
test -n "${READEST_E2E_BASE_URL:?set this only in the active process}"
PLAYWRIGHT_CLI_SESSION=readest-selfhost-stable \
  "$PWCLI" open "$READEST_E2E_BASE_URL" --browser firefox
```

Expected: the live selfhost library loads without storing the URL in any repository file.

- [ ] **Step 2: Verify the library and reader flow**

Use Playwright snapshots and DOM inspection only. Confirm that the library renders at least one book, open one visible book, and confirm the reader content appears. Do not take screenshots, start tracing, save storage state, or generate a Playwright test file.

- [ ] **Step 3: Close the browser and prove no artifact entered Git**

```bash
"$PWCLI" close
git status --short --branch
```

Expected: the Playwright session closes and the worktree remains clean.
