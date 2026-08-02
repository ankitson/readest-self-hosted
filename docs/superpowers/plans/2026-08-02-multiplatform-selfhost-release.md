# Readest Selfhost Multi-platform Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish the complete Readest Selfhost `0.11.20` native package matrix as GitHub Release `selfhost-v0.11.20`.

**Architecture:** GitHub-hosted native runners build Windows, Linux, macOS, and Android artifacts in the reusable selfhost build workflow. A standalone Node release-preparation script validates the flattened artifact set and generates one deterministic `latest.json`; the release workflow publishes only after every build leg and validation succeeds.

**Tech Stack:** GitHub Actions, Bash, Node.js 24, pnpm, Tauri v2, Rust stable, Android SDK/NDK `28.2.13676358`, Java 17, GitHub CLI.

## Global Constraints

- Release version is exactly `0.11.20`; release tag is exactly `selfhost-v0.11.20`.
- Product name remains `Readest Selfhost`; application identifier remains `com.readest.selfhost`.
- Updater URLs may reference only `luoji12103/readest-self-hosted`.
- Tauri updater files use the existing selfhost updater private key; Android APKs use the existing selfhost Android keystore.
- No private key, Apple credential, or private real-library URL may enter tracked files, logs, release notes, or release assets.
- macOS is Universal x86_64+aarch64, ad-hoc signed where required, and explicitly not Apple-notarized.
- iOS IPA is outside this GitHub Release because no Apple distribution profile or App Store credentials exist.
- A public Release is created or updated only after all build legs and manifest validation pass.
- Remote `main` and `selfhost-main` are updated atomically with explicit `--force-with-lease`; no pull request is created.

---

### Task 1: Deterministic release asset validator and manifest generator

**Files:**
- Create: `scripts/test-prepare-selfhost-release.sh`
- Create: `scripts/prepare-selfhost-release.mjs`

**Interfaces:**
- Consumes environment variables `RELEASE_TAG`, `GITHUB_REPOSITORY`, `SELFHOST_RESOLVED_RELEASE_VERSION`, optional `SELFHOST_RELEASE_ASSETS_DIR`, and optional `SELFHOST_RELEASE_NOTES_PATH`.
- Consumes exactly named release assets in `SELFHOST_RELEASE_ASSETS_DIR`.
- Produces `<assets-dir>/latest.json` and the Markdown file at `SELFHOST_RELEASE_NOTES_PATH`.

- [ ] **Step 1: Write the failing manifest contract test**

Create a Bash test that builds a temporary fake asset directory for version
`0.11.20`. It must create these 33 pre-manifest files:

```text
Readest-Selfhost_0.11.20_x64-setup.exe
Readest-Selfhost_0.11.20_x64-setup.exe.sig
Readest-Selfhost_0.11.20_x64-portable.exe
Readest-Selfhost_0.11.20_x64-portable.exe.sig
Readest-Selfhost_0.11.20_arm64-setup.exe
Readest-Selfhost_0.11.20_arm64-setup.exe.sig
Readest-Selfhost_0.11.20_arm64-portable.exe
Readest-Selfhost_0.11.20_arm64-portable.exe.sig
Readest-Selfhost_0.11.20_amd64.AppImage
Readest-Selfhost_0.11.20_amd64.AppImage.sig
Readest-Selfhost_0.11.20_amd64.deb
Readest-Selfhost_0.11.20_amd64.deb.sig
Readest-Selfhost-0.11.20-1.x86_64.rpm
Readest-Selfhost-0.11.20-1.x86_64.rpm.sig
Readest-Selfhost_0.11.20_aarch64.AppImage
Readest-Selfhost_0.11.20_aarch64.AppImage.sig
Readest-Selfhost_0.11.20_arm64.deb
Readest-Selfhost_0.11.20_arm64.deb.sig
Readest-Selfhost-0.11.20-1.aarch64.rpm
Readest-Selfhost-0.11.20-1.aarch64.rpm.sig
Readest-Selfhost_0.11.20_universal.dmg
Readest-Selfhost_0.11.20_universal.app.tar.gz
Readest-Selfhost_0.11.20_universal.app.tar.gz.sig
Readest-Selfhost_0.11.20_universal.apk
Readest-Selfhost_0.11.20_universal.apk.sig
Readest-Selfhost_0.11.20_arm64.apk
Readest-Selfhost_0.11.20_arm64.apk.sig
Readest-Selfhost_0.11.20_armv7.apk
Readest-Selfhost_0.11.20_armv7.apk.sig
Readest-Selfhost_0.11.20_x64.apk
Readest-Selfhost_0.11.20_x64.apk.sig
Readest-Selfhost_0.11.20_x86.apk
Readest-Selfhost_0.11.20_x86.apk.sig
```

The test invokes the Node script, asserts version `0.11.20`, asserts the exact
25 platform keys below, rejects URLs outside the fork tag, verifies the macOS
warning in release notes, then removes one signature and asserts a non-zero
exit status:

```text
android-arm64 android-armv7 android-i686 android-universal android-x86_64
darwin-aarch64 darwin-aarch64-app darwin-universal darwin-universal-app
darwin-x86_64 darwin-x86_64-app
linux-aarch64 linux-aarch64-appimage linux-aarch64-deb linux-aarch64-rpm
linux-x86_64 linux-x86_64-appimage linux-x86_64-deb linux-x86_64-rpm
windows-aarch64 windows-aarch64-nsis windows-aarch64-portable
windows-x86_64 windows-x86_64-nsis windows-x86_64-portable
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
bash scripts/test-prepare-selfhost-release.sh
```

Expected: non-zero exit because `scripts/prepare-selfhost-release.mjs` does not
exist.

- [ ] **Step 3: Implement exact asset validation and manifest generation**

Implement `scripts/prepare-selfhost-release.mjs` using only `node:fs` and
`node:path`. Validate the version with
`/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/`, validate tag
`selfhost-v${version}`, compare sorted directory entries with the 33 expected
names, and reject missing or unexpected files. Read every `.sig`, trim it, and
reject empty signatures.

Generate platform entries through this interface:

```js
const entry = (assetName) => ({
  signature: readSignature(assetName),
  url: `${baseUrl}/${encodeURIComponent(assetName)}`,
});
```

Default and format-specific aliases point to the same signed package: Windows
defaults point to NSIS; Linux defaults point to AppImage; all Darwin aliases
point to the universal `.app.tar.gz`. Android keys point to the five APKs.
Write release notes containing the exact sentence:

```text
The macOS build is ad-hoc signed but is not Apple Developer ID signed or notarized; macOS Gatekeeper may display a warning.
```

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```bash
bash scripts/test-prepare-selfhost-release.sh
```

Expected: `Selfhost release asset preparation tests passed.`

- [ ] **Step 5: Commit the validator**

```bash
git add scripts/prepare-selfhost-release.mjs scripts/test-prepare-selfhost-release.sh
git commit -m "ci: validate selfhost release assets"
```

### Task 2: Full native build and gated release workflows

**Files:**
- Create: `scripts/test-selfhost-release-workflow.sh`
- Modify: `.github/workflows/build-selfhost.yml`
- Modify: `.github/workflows/release-selfhost.yml`
- Modify: `.github/workflows/selfhost-safety.yml`

**Interfaces:**
- `build-selfhost.yml` accepts `release_version` and inherited selfhost signing secrets, then emits uniquely named Actions artifacts containing the 33 files from Task 1.
- `release-selfhost.yml` flattens those artifacts without basename collisions and invokes `scripts/prepare-selfhost-release.mjs` before any public Release mutation.
- `selfhost-safety.yml` executes both release contract test scripts.

- [ ] **Step 1: Write the failing workflow contract test**

Create `scripts/test-selfhost-release-workflow.sh` with `set -euo pipefail` and
`rg -q` assertions for:

```text
windows-latest
x86_64-pc-windows-msvc
aarch64-pc-windows-msvc
ubuntu-22.04
ubuntu-22.04-arm
x86_64-unknown-linux-gnu
aarch64-unknown-linux-gnu
macos-latest
universal-apple-darwin
APPLE_SIGNING_IDENTITY: '-'
pnpm tauri android build --apk
pnpm tauri android build --split-per-abi --apk
Readest-Selfhost_${version}_universal.apk
Readest-Selfhost_${version}_x64-portable.exe
Readest-Selfhost_${version}_arm64-portable.exe
Readest-Selfhost_${version}_universal.dmg
Readest-Selfhost_${version}_amd64.AppImage
Readest-Selfhost_${version}_aarch64.AppImage
scripts/prepare-selfhost-release.mjs
--draft
--draft=false
--latest
```

Also assert `fail-fast: false`, ensure the publish job needs the reusable build,
and ensure the old embedded `const androidPlatforms` manifest generator no
longer exists.

- [ ] **Step 2: Run the workflow test and verify RED**

Run:

```bash
bash scripts/test-selfhost-release-workflow.sh
```

Expected: non-zero exit at the first missing Windows ARM64 or Linux marker.

- [ ] **Step 3: Expand Windows to x86_64 and aarch64 installers and portable binaries**

Change the Windows job to `strategy.fail-fast: false` with two include rows:

```yaml
include:
  - arch: x64
    rust_target: x86_64-pc-windows-msvc
  - arch: arm64
    rust_target: aarch64-pc-windows-msvc
```

Build NSIS, copy and sign the deterministic setup asset, append
`NEXT_PUBLIC_PORTABLE_APP=true` to `.env.local`, rebuild, copy
`target/<rust-target>/release/readest.exe` as the portable asset, sign it, and
upload `selfhost-windows-${{ matrix.config.arch }}`.

- [ ] **Step 4: Add native Linux x86_64 and aarch64 package legs**

Use `ubuntu-22.04` for x86_64 and `ubuntu-22.04-arm` for aarch64. Mirror the
upstream stable Linux dependencies and pinned truly-portable AppImage tooling.
Run `cargo tauri build` after `patch-tauri-selfhost`, locate exactly one
AppImage, DEB, and RPM per leg, copy them to the Task 1 deterministic names,
copy an existing Tauri `.sig` or invoke `pnpm tauri signer sign`, and upload
`selfhost-linux-${{ matrix.config.arch }}`.

- [ ] **Step 5: Add the macOS Universal package leg**

Install `x86_64-apple-darwin,aarch64-apple-darwin`, set:

```yaml
APPLE_SIGNING_IDENTITY: '-'
```

Run:

```bash
pnpm tauri build --target universal-apple-darwin --bundles dmg
```

Collect one DMG and one `.app.tar.gz`, copy them to the Task 1 deterministic
names, preserve or generate the updater archive signature, and upload
`selfhost-macos-universal`.

- [ ] **Step 6: Add the universal Android APK while preserving all split APKs**

After the existing Gradle signing injection, first run
`pnpm tauri android build --apk` and preserve the universal APK. Then run
`pnpm tauri android build --split-per-abi --apk`, retain arm64, armv7, x64, and
x86 mapping, and sign all five copied APKs with the Tauri updater signer.

- [ ] **Step 7: Gate release publication on exact artifact validation**

In `release-selfhost.yml`, detect duplicate basenames before flattening Actions
artifacts, copy them into `release-assets`, and run:

```yaml
env:
  SELFHOST_RESOLVED_RELEASE_VERSION: ${{ needs.release-metadata.outputs.release_version }}
  SELFHOST_RELEASE_ASSETS_DIR: release-assets
  SELFHOST_RELEASE_NOTES_PATH: release-notes-selfhost.md
run: node scripts/prepare-selfhost-release.mjs
```

Create a draft Release with `--notes-file release-notes-selfhost.md`, upload
only `release-assets/* --clobber`, and switch it to non-draft with `--latest`
only after every upload succeeds. Keep tag creation as an idempotent fallback,
verify any existing tag points to `GITHUB_SHA`, and keep `publish.needs`
dependent on both metadata and the complete reusable build.

- [ ] **Step 8: Add the release tests to selfhost safety CI**

Add these commands to `.github/workflows/selfhost-safety.yml`:

```bash
bash scripts/test-prepare-selfhost-release.sh
bash scripts/test-selfhost-release-workflow.sh
```

- [ ] **Step 9: Run workflow tests and verify GREEN**

Run:

```bash
bash scripts/test-prepare-selfhost-release.sh
bash scripts/test-selfhost-release-workflow.sh
bash scripts/test-sync-upstream-workflow.sh
bash scripts/scan-public-fork-safety.sh
```

Expected: all four scripts exit zero and print their success messages.

- [ ] **Step 10: Commit the workflows**

```bash
git add .github/workflows/build-selfhost.yml .github/workflows/release-selfhost.yml .github/workflows/selfhost-safety.yml scripts/test-selfhost-release-workflow.sh
git commit -m "ci: build full selfhost release matrix"
```

### Task 3: Pre-release verification gate

**Files:**
- Verify only; modify Task 1 or Task 2 files only if a check exposes a defect.

**Interfaces:**
- Consumes the final candidate commit.
- Produces local evidence that repository, application, Rust, Lua, and workflow gates pass before remote publication.

- [ ] **Step 1: Validate workflow syntax and repository formatting**

Run:

```bash
actionlint .github/workflows/build-selfhost.yml .github/workflows/release-selfhost.yml .github/workflows/selfhost-safety.yml .github/workflows/sync-upstream.yml
pnpm format:check
pnpm lint
git diff --check HEAD~2..HEAD
```

Expected: all commands exit zero.

- [ ] **Step 2: Run all selfhost policy and manifest tests**

Run:

```bash
bash scripts/test-select-latest-stable-tag.sh
bash scripts/test-sync-upstream-workflow.sh
bash scripts/test-prepare-selfhost-release.sh
bash scripts/test-selfhost-release-workflow.sh
bash scripts/scan-public-fork-safety.sh
```

Expected: all commands exit zero.

- [ ] **Step 3: Run application, Lua, Rust, and Web production gates**

Run:

```bash
pnpm --filter @readest/readest-app test --run
pnpm --filter @readest/readest-app test:lua
pnpm fmt:check
pnpm clippy:check
NODE_OPTIONS=--max-old-space-size=4096 pnpm --filter @readest/readest-app build-web
```

Expected: unit and Lua suites have zero failures, Rust formatting and Clippy
exit zero, and the Web production build completes. Upstream deprecation warnings
without a non-zero exit remain informational.

- [ ] **Step 4: Verify identity and sensitive-data exclusions**

Run:

```bash
git status --short
bash scripts/scan-public-fork-safety.sh
jq -r '.productName, .identifier, .plugins.updater.endpoints[]' apps/readest-app/src-tauri/tauri.conf.json
```

Expected: worktree is clean, the sensitive scan has no matches, and the values
are `Readest Selfhost`, `com.readest.selfhost`, and the fork `latest.json` URL.

### Task 4: Atomic stable branch publication and release dispatch

**Files:**
- No file modifications.

**Interfaces:**
- Consumes the verified local `HEAD` and current remote `main`/`selfhost-main` object IDs.
- Produces identical remote `main` and `selfhost-main` refs, then dispatches the
  release build that creates `selfhost-v0.11.20` only after all native jobs pass.

- [ ] **Step 1: Fetch and capture remote lease values**

```bash
git fetch --no-tags origin main selfhost-main
expected_main=$(git rev-parse refs/remotes/origin/main)
expected_selfhost=$(git rev-parse refs/remotes/origin/selfhost-main)
```

- [ ] **Step 2: Reject a conflicting existing release tag**

```bash
git ls-remote --exit-code --tags origin refs/tags/selfhost-v0.11.20
```

Expected before first publication: exit code 2 and no output. If a tag exists,
verify it equals `HEAD`; never move a published tag to a different commit.

- [ ] **Step 3: Push both stable branches atomically**

```bash
git push --atomic origin \
  --force-with-lease=refs/heads/main:${expected_main} \
  --force-with-lease=refs/heads/selfhost-main:${expected_selfhost} \
  HEAD:refs/heads/main \
  HEAD:refs/heads/selfhost-main
```

Expected: both branches update to the same verified `HEAD`.

- [ ] **Step 4: Dispatch the release from the verified main branch**

```bash
gh workflow run release-selfhost.yml \
  --ref main \
  -f tag=selfhost-v0.11.20 \
  -f release_version=0.11.20
```

Expected: exactly one `workflow_dispatch` Release Selfhost run starts at the
verified `main` commit. The publish job creates the tag and draft only after all
native build jobs and manifest validation pass, uploads all assets, then makes
the Release public.

### Task 5: Monitor, diagnose, and complete the remote release

**Files:**
- Modify workflow or script files only if remote native execution reveals a reproducible defect; add or extend a failing contract test before each fix.

**Interfaces:**
- Consumes the manually dispatched GitHub Actions run at verified `main`.
- Produces a successful Release Selfhost run and public release assets.

- [ ] **Step 1: Locate and monitor the dispatched run**

```bash
gh run list --workflow release-selfhost.yml --branch main --limit 5
gh run watch <run-id> --interval 20
```

Expected: release metadata, Windows x64/ARM64, Linux x64/ARM64, macOS Universal,
Android, and publish jobs all conclude `success`.

- [ ] **Step 2: Diagnose any native-runner failure from job logs**

For a failed run, invoke the systematic-debugging skill, then run:

```bash
gh run view <run-id> --log-failed
```

Reproduce the contract locally where possible, add a failing test, fix the
smallest root cause, rerun Task 3, commit, update both branches atomically, and
dispatch `release-selfhost.yml` from corrected `main`. If the failed publish
left a draft and tag, delete that unpublished draft and tag before redispatch.
Never move a tag that already belongs to a public Release; publish a new patch
tag instead.

- [ ] **Step 3: Confirm Docker release build behavior**

```bash
gh run list --workflow docker-image.yml --limit 5
```

Expected: the run triggered by the new Release is visible; if it runs, its
amd64/arm64 image publication concludes successfully.

### Task 6: Authoritative release completion audit

**Files:**
- No tracked file modifications.

**Interfaces:**
- Consumes GitHub Release API state and published assets.
- Produces evidence for every requirement in the approved design.

- [ ] **Step 1: Verify Release identity and asset inventory**

```bash
gh release view selfhost-v0.11.20 --json tagName,name,isDraft,isPrerelease,publishedAt,url,targetCommitish,body,assets
```

Expected: tag `selfhost-v0.11.20`, draft and prerelease both false, macOS warning
present, exactly the 33 validated pre-manifest assets plus `latest.json`, and
every asset size greater than zero.

- [ ] **Step 2: Download and validate updater metadata and signatures**

```bash
rm -rf /tmp/readest-selfhost-v0.11.20-audit
mkdir -p /tmp/readest-selfhost-v0.11.20-audit
gh release download selfhost-v0.11.20 --pattern latest.json --pattern '*.sig' --dir /tmp/readest-selfhost-v0.11.20-audit
jq -e '.version == "0.11.20" and (.platforms | length == 25)' /tmp/readest-selfhost-v0.11.20-audit/latest.json
find /tmp/readest-selfhost-v0.11.20-audit -name '*.sig' -size 0 -print -quit
```

Expected: `jq` returns true, 16 signature files are downloaded, and the empty
signature search prints nothing.

- [ ] **Step 3: Verify all published download URLs resolve**

Use the Release JSON asset URLs and issue `curl -fsSIL` for each browser download
URL. Expected: every request follows redirects to a successful 2xx response
without downloading the package body.

- [ ] **Step 4: Verify remote refs and updater URL isolation**

```bash
git ls-remote origin refs/heads/main refs/heads/selfhost-main refs/tags/selfhost-v0.11.20
jq -r '.platforms[].url' /tmp/readest-selfhost-v0.11.20-audit/latest.json | sort -u
```

Expected: all three refs resolve to the verified release commit and every URL is
under `https://github.com/luoji12103/readest-self-hosted/releases/download/selfhost-v0.11.20/`.

- [ ] **Step 5: Mark the persistent goal complete**

Only after Tasks 1-6 have authoritative passing evidence, call the goal status
tool with `complete` and report the Release URL and artifact matrix.
