# Official WebUI Client Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the selfhost Tauri client connect to official Readest Docker WebUI deployments through safe automatic discovery or a one-time manual public-config fallback, then deliver only a signed Android arm64 validation APK.

**Architecture:** Keep the existing `readest_custom_server_config_v1` storage contract and add bounded native-HTTP discovery for two JSON endpoints plus a strictly parsed runtime script. When discovery cannot produce a complete safe config, the settings panel expands a manual compatibility form whose input is normalized, security-checked, independently probed against Readest and Supabase, and saved through the existing runtime-config path.

**Tech Stack:** TypeScript, React 19, Vitest/jsdom, Tauri v2 HTTP plugin, pnpm, Bash contract tests, GitHub Actions, Android SDK `apksigner`/`aapt`.

## Global Constraints

- The implementation follows `docs/superpowers/specs/2026-08-02-official-webui-client-compat-design.md`.
- Production public endpoints require HTTPS; local/private HTTP remains development-only.
- Discovery order is exactly `/.well-known/readest-client-config.json`, `/api/public/runtime-config`, `/runtime-config.js`.
- The runtime script must be parsed as one fixed `window.__READEST_RUNTIME_CONFIG=<JSON>;` assignment and must never be executed.
- Discovery and probing use `@tauri-apps/plugin-http` on Tauri unless a test supplies `fetchImpl`.
- Accept only a JWT whose payload role is `anon` or a syntactically valid key with the `sb_publishable_` prefix.
- Reject JWT role `service_role`, keys with the `sb_secret_` prefix, dangerous server fields, credentials in URLs, malformed values, oversized responses, and timeouts.
- Username and password are never used for discovery or connectivity probing; the existing Supabase sign-in flow remains unchanged.
- Existing stored `readest_custom_server_config_v1` values remain loadable without migration.
- Clear the old auth session only when the normalized server/API/Supabase identity changes or an active custom config is removed.
- UI uses existing `BoxedList` and `SettingsRow` primitives, logical-direction classes, e-ink-safe borders, masked key input, and `btn-contrast` for Save.
- Version is exactly `0.11.21-selfhost.1`; Android package ID is `com.readest.selfhost`; Android version code is `11021`.
- Phase 1 builds only Android `arm64-v8a`, uploads a repository Actions artifact, creates no GitHub Release, and does not modify `selfhost-v0.11.20`.
- The private real-server URL and all deployment values remain environment-only and never appear in tracked files, Actions logs, artifacts, commits, or release notes.
- `.trellis/` is absent in this worktree, so there are no Trellis package specs to load; applicable project rules are `apps/readest-app/AGENTS.md`, `apps/readest-app/.claude/rules/test-first.md`, `typescript.md`, `verification.md`, `apps/readest-app/docs/i18n.md`, and `apps/readest-app/DESIGN.md`.

---

### Task 1: Native discovery transport, strict runtime parser, and public-key validation

**Files:**
- Modify: `apps/readest-app/src/services/customServerConfig.ts`
- Modify: `apps/readest-app/src/__tests__/services/customServerConfig.test.ts`

**Interfaces:**
- Consumes: `isTauriAppPlatform(): boolean`, Tauri HTTP `fetch`, optional injected `fetchImpl`.
- Produces: `getCustomServerFetch(fetchImpl?: typeof fetch): typeof fetch`, `parseRuntimeConfigScript(source: string): unknown`, and enhanced `fetchPublicClientConfig(serverBaseUrlInput, options): Promise<PublicReadestClientConfig>`.
- Produces error metadata through `new CustomServerConfigError(code, message, suggestedConfig?)`, where `suggestedConfig?: PublicReadestClientConfig` is used only for safe manual prefilling.

- [x] **Step 1: Add failing tests for transport selection and discovery priority**

Mock `@tauri-apps/plugin-http` and `@/services/environment`, then add tests that assert an injected fetch wins, Tauri selects the native fetch, web selects `globalThis.fetch`, and the third request is `/runtime-config.js` after the two JSON endpoints fail. Use a valid JWT anon key generated in the test:

```ts
const encodeBase64Url = (value: unknown) =>
  Buffer.from(JSON.stringify(value)).toString('base64url');
const anonJwt = `${encodeBase64Url({ alg: 'HS256', typ: 'JWT' })}.${encodeBase64Url({ role: 'anon' })}.signature`;

test('discovers runtime-config.js after both JSON endpoints fail', async () => {
  const fetchImpl = vi
    .fn()
    .mockResolvedValueOnce(new Response('', { status: 404 }))
    .mockResolvedValueOnce(new Response('', { status: 404 }))
    .mockResolvedValueOnce(
      new Response(
        `window.__READEST_RUNTIME_CONFIG={"apiBaseUrl":"https://api.example.com","supabaseUrl":"https://supabase.example.com","supabaseAnonKey":"${anonJwt}"};`,
        { status: 200 },
      ),
    ) as unknown as typeof fetch;

  await expect(
    fetchPublicClientConfig('https://readest.example.com', { fetchImpl }),
  ).resolves.toMatchObject({ apiBaseUrl: 'https://api.example.com' });
  expect(fetchImpl).toHaveBeenNthCalledWith(
    3,
    'https://readest.example.com/runtime-config.js',
    expect.objectContaining({ method: 'GET' }),
  );
});
```

- [x] **Step 2: Run Task 1 discovery tests and verify RED**

Run:

```bash
cd apps/readest-app
pnpm exec vitest run src/__tests__/services/customServerConfig.test.ts --reporter=verbose
```

Expected: FAIL because `getCustomServerFetch`, `/runtime-config.js`, and `parseRuntimeConfigScript` do not exist.

- [x] **Step 3: Add failing parser, response-bound, timeout, and key-shape tests**

Add separate tests that accept whitespace around the fixed assignment, reject a second statement or non-object JSON, reject a response above `maxResponseBytes`, map an aborted request to `manual-config-required`, accept `anonJwt` and `sb_publishable_example_public_key_123456`, and reject `service_role` JWT, `sb_secret_example`, and malformed text.

```ts
expect(
  parseRuntimeConfigScript(
    ' window.__READEST_RUNTIME_CONFIG = {"apiBaseUrl":"https://api.example.com"};\n',
  ),
).toEqual({ apiBaseUrl: 'https://api.example.com' });
expect(() =>
  parseRuntimeConfigScript('window.__READEST_RUNTIME_CONFIG={};alert(1);'),
).toThrowError(CustomServerConfigError);
```

- [x] **Step 4: Run the expanded tests and verify RED**

Run the Task 1 command again.

Expected: FAIL on strict parsing, bounded reads, timeout classification, and key validation.

- [x] **Step 5: Implement the minimal bounded native discovery path**

Add the native imports, limits, transport selector, strict parser, bounded request helper, key validation, and third discovery source:

```ts
import { fetch as tauriFetch } from '@tauri-apps/plugin-http';
import { jwtDecode } from 'jwt-decode';
import { isTauriAppPlatform } from './environment';

const DEFAULT_REQUEST_TIMEOUT_MS = 8_000;
const DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024;
const RUNTIME_CONFIG_PATH = '/runtime-config.js';

export const getCustomServerFetch = (fetchImpl?: typeof fetch): typeof fetch => {
  if (fetchImpl) return fetchImpl;
  if (isTauriAppPlatform()) return tauriFetch as unknown as typeof fetch;
  if (!globalThis.fetch) {
    throw new CustomServerConfigError('server-not-reachable', 'Fetch API is not available.');
  }
  return globalThis.fetch.bind(globalThis);
};

export const parseRuntimeConfigScript = (source: string): unknown => {
  const match = source.match(
    /^\s*window\.__READEST_RUNTIME_CONFIG\s*=\s*(\{[\s\S]*\})\s*;\s*$/,
  );
  if (!match?.[1]) {
    throw new CustomServerConfigError('invalid-config', 'Runtime config script has an invalid envelope.');
  }
  try {
    return JSON.parse(match[1]) as unknown;
  } catch {
    throw new CustomServerConfigError('invalid-config', 'Runtime config script contains invalid JSON.');
  }
};
```

Extend `ResolveCustomServerConfigOptions` with `timeoutMs?: number` and `maxResponseBytes?: number`. Use an `AbortController`, clear its timer in `finally`, read `Response.text()`, enforce both `Content-Length` and encoded body size, and call `JSON.parse` for the JSON endpoints. Validate key shape before returning a config. Swallow absent/unreachable/structurally invalid sources, preserve only safe partial fields for the manual form, and immediately rethrow `dangerous-secret`.

- [x] **Step 6: Run Task 1 tests and verify GREEN**

Run the Task 1 command.

Expected: all discovery, parser, bounds, timeout, and key tests PASS with no warnings.

- [x] **Step 7: Commit Task 1**

```bash
git add apps/readest-app/src/services/customServerConfig.ts apps/readest-app/src/__tests__/services/customServerConfig.test.ts
git commit -m "feat: discover official WebUI client config"
```

### Task 2: Manual public config, independent connectivity probes, and session identity

**Files:**
- Modify: `apps/readest-app/src/services/customServerConfig.ts`
- Modify: `apps/readest-app/src/__tests__/services/customServerConfig.test.ts`

**Interfaces:**
- Consumes: Task 1 URL/key validation and `getCustomServerFetch`.
- Produces: `ManualCustomServerConfigInput`, `createManualCustomServerConfig(input, options): Promise<CustomServerConfig>`, and `validateCustomServerConnectivity(config, options): Promise<void>`.
- Produces error codes: `request-timeout`, `tls-error`, `api-unreachable`, `supabase-unreachable`, and `manual-config-required` in addition to existing codes.

- [ ] **Step 1: Add failing manual-config and probe tests**

Add tests that assert API base defaults to the normalized server URL, `/api/sync` accepts 200/401/403, `/auth/v1/settings` receives both `apikey` and `Authorization: Bearer`, Supabase non-2xx becomes `supabase-unreachable`, API 404/5xx becomes `api-unreachable`, abort becomes `request-timeout`, TLS/certificate errors become `tls-error`, and failed validation leaves the input object unchanged.

```ts
const input = {
  serverBaseUrl: 'https://readest.example.com/',
  apiBaseUrl: '',
  supabaseUrl: 'https://supabase.example.com/',
  supabaseAnonKey: anonJwt,
};
const fetchImpl = vi
  .fn()
  .mockResolvedValueOnce(new Response('', { status: 403 }))
  .mockResolvedValueOnce(jsonResponse({ external: {} })) as unknown as typeof fetch;

await expect(
  createManualCustomServerConfig(input, { fetchImpl, now: () => 321 }),
).resolves.toMatchObject({
  serverBaseUrl: 'https://readest.example.com',
  apiBaseUrl: 'https://readest.example.com',
  supabaseUrl: 'https://supabase.example.com',
  fetchedAt: 321,
});
expect(fetchImpl).toHaveBeenNthCalledWith(
  2,
  'https://supabase.example.com/auth/v1/settings',
  expect.objectContaining({
    headers: expect.objectContaining({ apikey: anonJwt, Authorization: `Bearer ${anonJwt}` }),
  }),
);
```

- [ ] **Step 2: Run manual-config tests and verify RED**

Run the Task 1 Vitest command.

Expected: FAIL because the manual interfaces and endpoint-specific errors do not exist.

- [ ] **Step 3: Implement manual construction and independent probes**

Add:

```ts
export interface ManualCustomServerConfigInput {
  serverBaseUrl: string;
  apiBaseUrl?: string | undefined;
  supabaseUrl: string;
  supabaseAnonKey: string;
}

export const createManualCustomServerConfig = async (
  input: ManualCustomServerConfigInput,
  options: ResolveCustomServerConfigOptions = {},
): Promise<CustomServerConfig> => {
  const serverBaseUrl = normalizeServerBaseUrl(input.serverBaseUrl, options);
  const validated = validatePublicConfig(
    serverBaseUrl,
    {
      apiBaseUrl: input.apiBaseUrl?.trim() || serverBaseUrl,
      supabaseUrl: input.supabaseUrl,
      supabaseAnonKey: input.supabaseAnonKey,
    },
    options,
  );
  const config: CustomServerConfig = {
    serverBaseUrl,
    apiBaseUrl: validated.apiBaseUrl ?? serverBaseUrl,
    supabaseUrl: validated.supabaseUrl,
    supabaseAnonKey: validated.supabaseAnonKey,
    fetchedAt: options.now?.() ?? Date.now(),
  };
  await validateCustomServerConnectivity(config, options);
  return config;
};
```

Probe `${apiBaseUrl}/api/sync` first and accept only `response.ok`, 401, or 403. Probe `${supabaseUrl}/auth/v1/settings` second with the public key headers and require `response.ok`. A shared request wrapper must preserve the endpoint label while mapping abort, TLS/certificate text, and other failures to the exact error codes above.

- [ ] **Step 4: Add failing effective-identity storage tests**

Add tests proving that changing only API URL, Supabase URL, or key clears auth once, while re-saving an equivalent normalized identity does not clear auth. Retain the existing load test with the v1 storage shape.

- [ ] **Step 5: Run storage tests and verify RED**

Run the Task 1 Vitest command.

Expected: FAIL because session clearing currently compares only `serverBaseUrl`.

- [ ] **Step 6: Compare the complete effective identity before clearing session**

Add a helper that compares `serverBaseUrl`, `apiBaseUrl`, `supabaseUrl ?? ''`, and `supabaseAnonKey ?? ''`; use it in `saveCustomServerConfig`. Do not validate old stored values during `loadCustomServerConfig`, so valid v1 storage continues to load.

- [ ] **Step 7: Run Task 2 tests and verify GREEN**

Run the Task 1 Vitest command.

Expected: all manual config, connectivity, and storage tests PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add apps/readest-app/src/services/customServerConfig.ts apps/readest-app/src/__tests__/services/customServerConfig.test.ts
git commit -m "feat: validate official Docker compatibility config"
```

### Task 3: Automatic and explicit compatibility mode in Server Settings

**Files:**
- Create: `apps/readest-app/src/__tests__/components/ServerSettingsPanel.test.tsx`
- Modify: `apps/readest-app/src/components/settings/ServerSettingsPanel.tsx`

**Interfaces:**
- Consumes: `CustomServerConfigError.suggestedConfig`, `createManualCustomServerConfig`, existing discovery/save/load/reset services.
- Produces: accessible inputs named `Server URL`, `API base URL`, `Supabase public URL`, and `Supabase anon or publishable key`; an `Official Docker compatibility` disclosure; automatic expansion on `manual-config-required`.

- [ ] **Step 1: Add failing component tests for automatic expansion and safe prefilling**

Mock translation as identity, mock Tauri platform true, partially mock the config service, render the panel, enter a server URL, and make `resolveCustomServerConfig` reject:

```ts
new CustomServerConfigError(
  'manual-config-required',
  'Public client config is not discoverable.',
  {
    apiBaseUrl: 'https://readest.example.com',
    supabaseUrl: 'https://supabase.example.com',
  },
)
```

Assert that the three compatibility fields appear, the server/API/Supabase URL values are prefilled, and the key input has `type="password"`.

- [ ] **Step 2: Run the new component test and verify RED**

Run:

```bash
cd apps/readest-app
pnpm exec vitest run src/__tests__/components/ServerSettingsPanel.test.tsx --reporter=verbose
```

Expected: FAIL because the compatibility disclosure and fields do not exist.

- [ ] **Step 3: Add failing save, reset, and input-preservation component tests**

Test that Save calls `createManualCustomServerConfig` with all four current values and then calls `saveCustomServerConfig(config, { resetSession: true })` with the returned config. Make manual validation reject once and assert every input retains its value. Test that Reset clears and collapses compatibility mode. Test that the disclosure can be opened before a failed discovery attempt.

- [ ] **Step 4: Run component tests and verify RED**

Run the Task 3 command.

Expected: FAIL on manual save, reset/collapse, explicit opening, and preservation.

- [ ] **Step 5: Implement the minimal compatibility UI**

Add state for `compatibilityExpanded`, `apiBaseUrl`, `supabaseUrl`, and `supabaseAnonKey`. On mount, prefill them from a saved config but keep the disclosure collapsed. On automatic discovery failure with `manual-config-required`, retain the normalized entered server, fill only safe blank fields from `error.suggestedConfig`, expand the disclosure, and show `Public client config was not found. Enter the official Docker public settings below.`

Render the compatibility fields as `SettingsRow` inputs with `aria-label`, `input-bordered`, `eink-bordered`, logical `text-end`, and the key as `type='password'`. Render an explicit disclosure button named `Official Docker compatibility`. When expanded, Save uses `createManualCustomServerConfig`; otherwise it retains the automatic discovery path. Change Save to `btn btn-contrast btn-sm`.

Map error codes to specific user-facing English keys: `Request timed out`, `TLS connection failed`, `Readest API is not reachable`, `Supabase is not reachable`, `Invalid public client config`, and the existing URL/secret messages. Translation keys use the repository's English-key-as-content fallback and no private values.

- [ ] **Step 6: Run component and service tests and verify GREEN**

Run:

```bash
cd apps/readest-app
pnpm exec vitest run src/__tests__/components/ServerSettingsPanel.test.tsx src/__tests__/services/customServerConfig.test.ts --reporter=verbose
```

Expected: both files PASS with no React act warnings.

- [ ] **Step 7: Commit Task 3**

```bash
git add apps/readest-app/src/components/settings/ServerSettingsPanel.tsx apps/readest-app/src/__tests__/components/ServerSettingsPanel.test.tsx
git commit -m "feat: add official Docker compatibility settings"
```

### Task 4: Version, documentation, safety contract, and arm64-only artifact workflow

**Files:**
- Modify: `apps/readest-app/package.json`
- Modify: `docs/selfhost-client.md`
- Create: `.github/workflows/build-selfhost-android-arm64.yml`
- Create: `scripts/test-selfhost-android-arm64-workflow.sh`
- Modify: `.github/workflows/selfhost-safety.yml`
- Modify: `scripts/scan-public-fork-safety.sh`

**Interfaces:**
- Consumes: existing Android signing secrets and pinned certificate digest.
- Produces: manual `workflow_dispatch` input `release_version`, one `arm64-v8a` signed APK, `SHA256SUMS.txt`, `apk-audit.txt`, and Actions artifact `selfhost-android-arm64-<version>`.

- [ ] **Step 1: Write the failing workflow contract test**

Create an executable Bash test that requires the workflow file and exact markers for `aarch64-linux-android`, `pnpm tauri android build -t aarch64 --apk`, ABI assertion `arm64-v8a`, package `com.readest.selfhost`, version `0.11.21-selfhost.1`, version code `11021`, pinned certificate digest, `apksigner verify`, `aapt dump badging`, `actions/upload-artifact`, and `retention-days: 14`. It must fail if the workflow contains `matrix:`, `release create`, `gh release`, desktop targets, `armv7`, `i686`, `x86_64-linux-android`, or a `release:` trigger.

- [ ] **Step 2: Run the workflow contract and verify RED**

Run:

```bash
bash scripts/test-selfhost-android-arm64-workflow.sh
```

Expected: FAIL because `.github/workflows/build-selfhost-android-arm64.yml` does not exist.

- [ ] **Step 3: Create the arm64-only workflow and make the contract GREEN**

Create a workflow with `contents: read`, one Ubuntu job, pinned checkout/setup actions, frozen pnpm install, vendor setup, Rust `aarch64-linux-android`, release-version validation, existing Tauri selfhost patch, Android init and official icon generation, step-scoped signing secrets, and one build command:

```bash
pnpm tauri android build -t aarch64 --apk
```

Select the sole release APK whose ZIP libraries are exactly `arm64-v8a`, copy it to `Readest-Selfhost_${version}_arm64.apk`, re-sign it with the repository keystore, verify the pinned certificate, verify package/version/versionCode/ABI with `aapt` and `unzip`, write the certificate/package/version/ABI/SHA-256 facts to `apk-audit.txt`, write `SHA256SUMS.txt`, and upload only those three files as a 14-day Actions artifact. Do not call any release workflow or GitHub Release command.

Run the Task 4 contract again.

Expected: PASS.

- [ ] **Step 4: Add the contract to selfhost safety and public-fork scanning**

Add `bash scripts/test-selfhost-android-arm64-workflow.sh` to `.github/workflows/selfhost-safety.yml`. Add the new workflow and component test to the safety scanner's selfhost/URL scan paths so an environment-specific host cannot be committed.

- [ ] **Step 5: Set the staged version and update public documentation**

Set `apps/readest-app/package.json` version to `0.11.21-selfhost.1`. Rewrite the manual-configuration section to document the three discovery sources, the fixed non-executed runtime assignment, the in-app official Docker form, accepted public key shapes, rejected server secrets, `/api/sync` and Supabase settings probes, unchanged username/password login, session behavior, and the arm64 validation-artifact stage. Correct the upstream-sync section to describe stable-tag synchronization rather than daily `upstream/main` rebases.

- [ ] **Step 6: Run workflow, safety, and version checks**

Run:

```bash
bash scripts/test-selfhost-android-arm64-workflow.sh
bash scripts/test-selfhost-release-workflow.sh
bash scripts/scan-public-fork-safety.sh
test "$(node -p "require('./apps/readest-app/package.json').version")" = '0.11.21-selfhost.1'
git diff --check
```

Expected: every command exits 0; the safety scan reports PASS and no private host appears in `git diff`.

- [ ] **Step 7: Commit Task 4**

```bash
git add apps/readest-app/package.json docs/selfhost-client.md .github/workflows/build-selfhost-android-arm64.yml .github/workflows/selfhost-safety.yml scripts/test-selfhost-android-arm64-workflow.sh scripts/scan-public-fork-safety.sh
git commit -m "ci: add signed Android arm64 validation build"
```

### Task 5: Full verification, review, branch delivery, and signed APK audit

**Files:**
- Verify all files changed in Tasks 1–4.
- Artifact download target: `/home/luoji/codex/readest-fix-restore-official-icons/dist/phase1-android-arm64/` (untracked).

**Interfaces:**
- Consumes: all Task 1–4 commits and repository GitHub Actions secrets.
- Produces: pushed commits on `main` and `selfhost-main`, one successful arm64-only workflow run, and a locally audited signed APK for user testing.

- [ ] **Step 1: Run focused and full local verification**

Run:

```bash
pnpm --filter @readest/readest-app test -- --watch=false
pnpm --filter @readest/readest-app lint
pnpm format:check
bash scripts/test-selfhost-android-arm64-workflow.sh
bash scripts/test-selfhost-release-workflow.sh
bash scripts/test-sync-upstream-workflow.sh
bash scripts/scan-public-fork-safety.sh
git diff --check origin/main...HEAD
```

Expected: all applicable checks pass. Rust-only checks are not required because no Rust source or Tauri Rust config is modified.

- [ ] **Step 2: Review the complete diff against the design and safety boundary**

Run:

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- apps/readest-app/src/services/customServerConfig.ts apps/readest-app/src/components/settings/ServerSettingsPanel.tsx .github/workflows/build-selfhost-android-arm64.yml docs/selfhost-client.md
bash scripts/scan-public-fork-safety.sh
```

Expected: implementation matches every design section; the generic public-fork URL allowlist reports no unexpected host; no Release mutation or non-arm64 build exists.

- [ ] **Step 3: Commit any verification-only corrections and push the validated commit**

If formatting or review required corrections, repeat the relevant RED/GREEN test, commit only those corrections, and rerun Step 1. Then fast-forward the two fork branches atomically:

```bash
git fetch origin main selfhost-main
test "$(git rev-parse origin/main)" = "$(git rev-parse origin/selfhost-main)"
git push --atomic origin HEAD:main HEAD:selfhost-main
```

Expected: both remote branches point at the same verified commit; no tag or Release is created.

- [ ] **Step 4: Dispatch only the arm64 validation workflow and wait**

Run:

```bash
gh workflow run build-selfhost-android-arm64.yml --ref main -f release_version=0.11.21-selfhost.1
run_id=$(gh run list --workflow build-selfhost-android-arm64.yml --branch main --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --exit-status
```

Expected: the one Android arm64 job succeeds; no other platform workflow is dispatched.

- [ ] **Step 5: Download and independently audit the artifact**

Run:

```bash
artifact_dir=/home/luoji/codex/readest-fix-restore-official-icons/dist/phase1-android-arm64
rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"
gh run download "$run_id" --name selfhost-android-arm64-0.11.21-selfhost.1 --dir "$artifact_dir"
apk="$artifact_dir/Readest-Selfhost_0.11.21-selfhost.1_arm64.apk"
test -s "$apk"
build_tools=$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n 1)
verification=$("$build_tools/apksigner" verify --verbose --print-certs "$apk")
certificate_digest=$(bash scripts/extract-android-certificate-sha256.sh <<< "$verification")
test "$certificate_digest" = '903bf29bdf76ec24766e48eb8eafc0f0d228572be347008956b3f6aa63d753be'
badging=$("$build_tools/aapt" dump badging "$apk")
rg -Fq "package: name='com.readest.selfhost' versionCode='11021' versionName='0.11.21-selfhost.1'" <<< "$badging"
test "$(unzip -Z1 "$apk" | sed -n 's#^lib/\([^/]*\)/.*#\1#p' | sort -u)" = 'arm64-v8a'
(cd "$artifact_dir" && sha256sum -c SHA256SUMS.txt)
```

Expected: certificate, package, version code/name, sole ABI, and SHA-256 all match. Keep the APK local and stop before any full matrix or GitHub Release.

- [ ] **Step 6: Hand off Phase 1 for real-device validation**

Report the absolute APK path, SHA-256, workflow run URL, package/version/signing/ABI audit, and concise install/test steps. Explicitly state that Phase 2 remains intentionally unbuilt and unpublished until the user confirms Android testing succeeds.
