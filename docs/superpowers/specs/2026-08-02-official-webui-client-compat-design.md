# Official WebUI Client Compatibility Design

## Problem

The selfhost Tauri clients currently treat a server as connectable only when it exposes one of two JSON discovery endpoints. Official Readest Docker Compose deployments can serve the WebUI and API correctly without exposing either endpoint. A browser can therefore load the server while Android reports `Server not reachable`.

The compatibility change must require no modification to the official Compose stack, reverse proxy, or WebUI deployment. Real deployment URLs, public backend values used for private testing, credentials, and server-side secrets must never enter Git, public CI logs, release assets, or release notes.

## Goals

- Preserve automatic discovery for servers that already implement the JSON protocol.
- Add a safe automatic fallback for official images that expose `/runtime-config.js`.
- Add a one-time manual compatibility form for official images that expose no discoverable public config.
- Reuse the deployment's existing Supabase account and data without importing or storing a WebUI password.
- Keep existing saved custom-server configurations working without migration prompts.
- Initially produce only a signed Android arm64 test APK. Build and publish the full affected matrix only after user validation.

## Non-goals

- Do not modify or replace the official Docker Compose deployment.
- Do not scrape the homepage or Next.js chunks for embedded values.
- Do not execute remote JavaScript.
- Do not import browser cookies, local storage, or WebUI sessions.
- Do not add username/password-based server discovery.
- Do not include iOS or KOReader in the initial or final affected-platform matrix.

## Architecture

### Transport

Custom-server discovery and validation use the Tauri HTTP plugin on Tauri platforms. This avoids Android WebView CORS differences and matches a native HTTP client. Test callers retain injectable fetch implementations. Non-Tauri web builds do not expose the custom-server workflow.

### Discovery order

The client tries these sources in order:

1. `/.well-known/readest-client-config.json`
2. `/api/public/runtime-config`
3. `/runtime-config.js`

The first two must return a JSON object. The runtime script is accepted only when its entire response matches the fixed `window.__READEST_RUNTIME_CONFIG=<JSON>;` envelope. The JSON is parsed without `eval` or dynamic code execution. Responses have a small size ceiling and explicit timeout.

All discovered data passes through the same URL, required-field, and dangerous-secret validation used by manual input.

### Manual compatibility mode

When all compatible discovery sources are absent, unreachable, or structurally invalid, the existing server panel expands an `Official Docker compatibility` section in place. The entered server URL is retained.

Fields:

- WebUI/server URL
- API base URL, optional and defaulting to the server URL
- Supabase public URL
- Supabase anon or publishable key

The section is also available through an explicit advanced-settings disclosure. Once a valid configuration is saved, it remains collapsed on later launches.

## Authentication and session behavior

Credentials are not part of discovery or connectivity testing. After public client configuration is saved, the existing login flow sends credentials directly to the configured Supabase Auth service. This preserves the official WebUI account and library because both clients use the same backend.

Changing any effective server, API, or Supabase identity clears the previous auth session. Re-saving an equivalent normalized configuration does not sign the user out. Restoring the default server removes the compatibility config and clears the custom-server session.

## Security

- Production public endpoints must use HTTPS under the existing URL policy.
- Credentialed URLs remain forbidden.
- JWT keys whose decoded role is `service_role` are rejected.
- JWT keys with role `anon` and `sb_publishable_...` keys are accepted.
- `sb_secret_...` keys are rejected.
- Existing dangerous field-name scanning remains mandatory for discovered objects.
- The anon/publishable key field is visually masked by default even though it is public client configuration.
- No connection attempt sends a username or password to a guessed endpoint.
- Remote runtime script text is never executed.

## Connectivity validation

Before saving manual configuration, the client independently checks the Readest API base and Supabase public service with bounded native HTTP requests.

- A Readest API response such as 401 or 403 proves reachability and must not be reported as a network failure.
- Supabase health/config probing includes the public API key where the standard gateway requires it.
- Network failure, timeout, TLS failure, invalid URL, incomplete config, rejected secret material, Readest API failure, and Supabase failure remain distinguishable error states.
- Failed validation preserves all form input.

## Storage compatibility

The existing custom-server config already stores the server URL, API URL, Supabase URL, public anon key, and fetch timestamp. Manual compatibility reuses this shape and storage key. No migration is needed for previously saved valid configs. New metadata may be optional and must not invalidate older stored values.

## UX

Normal flow:

1. Enter server URL and select Connect.
2. Run automatic discovery.
3. If discovery succeeds, save and proceed as today.
4. If no supported config exists, automatically expand the compatibility fields with the server and API URLs prefilled.
5. Validate and save the two Supabase public values once.
6. Continue to the existing sign-in UI.

Dangerous discovered configuration is a hard-stop warning rather than a silent fallback. Incomplete but otherwise safe discovered configuration may prefill safe values in manual mode.

## Testing

Automated tests cover:

- discovery priority and fallback across all three sources;
- Tauri-native transport selection;
- strict runtime-script parsing without execution;
- response size and timeout handling;
- manual-mode expansion, prefilling, validation, saving, resetting, and input preservation;
- accepted anon and publishable key shapes;
- rejected service-role, secret, dangerous-field, and malformed values;
- 401/403 reachability semantics;
- API and Supabase error separation;
- session clearing only when effective configuration changes;
- compatibility with existing stored configs;
- public-fork URL and secret safety contracts.

Real-server checks use environment-injected values only and are never committed or enabled in public CI logs.

## Version and staged delivery

The compatibility build version is `0.11.21-selfhost.1`. It sorts above the current `0.11.20` client and below a future upstream stable `0.11.21` release.

### Phase 1: user-validation artifact

- Build only the Android arm64 APK.
- Sign it with the existing Android release certificate.
- Verify package ID, version code/name, ABI, and certificate.
- Upload it as a private-to-repository GitHub Actions artifact, not as a public or partial Release.
- Do not mutate the immutable `selfhost-v0.11.20` Release.
- Stop for user installation and real-device validation.

### Phase 2: full release after validation

After explicit user confirmation, rebuild the affected matrix:

- Android universal, arm64, armv7, x64, and x86;
- Windows x64 and arm64 installer/portable packages;
- Linux x64 and arm64 AppImage, deb, and rpm packages;
- macOS Universal DMG and updater archive;
- updater signatures and `latest.json`.

Publish a new stable/latest GitHub Release tagged `selfhost-v0.11.21-selfhost.1`. Keep the accepted macOS non-notarization warning. Release notes describe official Docker WebUI compatibility and the manual public-config flow without mentioning a real deployment.

The Docker workflow may run automatically when the client commit reaches `main`, but no server-side change or deployment migration is required for this feature.

## Completion gates

Phase 1 completes only when tests pass and the signed arm64 artifact is available and independently audited. The overall compatibility release remains incomplete until the user validates the arm64 APK and Phase 2 publishes and audits the complete matrix.
