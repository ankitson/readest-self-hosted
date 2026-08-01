# Restore Official Readest Icons

## Goal

Restore the self-hosted client to the official Readest application icon on every supported platform. Use the official `readest/readest` `v0.11.20` tag (`1df1505fc5033fc949463c9908f2d53bd0fbdfa6`) as the source of truth.

This change is intentionally limited to icon assets and icon metadata. A later rebrand may replace the icon set again, but that is outside this change.

## Preserve Self-Hosted Identity and Behavior

The following remain unchanged:

- product name `Readest Selfhost`;
- application identifier `com.readest.selfhost`;
- updater endpoint, updater public key, and release signing;
- custom server configuration and server switching;
- all non-icon product behavior.

## Official Icon Surface

Restore or verify the official icon assets used by:

- Web/PWA and Apple touch integration under `apps/readest-app/public/`;
- Next.js icon metadata in `apps/readest-app/src/app/layout.tsx`;
- Windows, macOS, Android, and iOS packaging under `apps/readest-app/src-tauri/icons/`;
- Android store metadata under `fastlane/metadata/android/en-US/images/icon.png`;
- the canonical icon-generation source at `data/icons/readest-book.png`.

Binary assets in those icon-specific paths must be byte-for-byte identical to `v0.11.20`. Icon declarations in the Web manifest and Next.js metadata must match the official tag while preserving unrelated local code.

Files introduced only for the self-hosted icon override must be removed when the official tag does not contain them. In particular, the extra size-specific PWA icon files and references must not survive if they are absent upstream.

Browser-extension icons, document-type icons, UI glyphs, and unrelated images are outside scope.

## Implementation Approach

1. Produce a pre-change comparison that fails because the current icon surface differs from `v0.11.20`.
2. Restore official binary assets directly from the upstream tag without regenerating or recompressing them.
3. Apply the smallest text edits needed to align Web icon declarations with the upstream tag.
4. Remove self-host-only icon assets that have no upstream counterpart.
5. Verify that no self-host identity, updater, or server files changed.

## Verification

- Compare the complete scoped icon path list against `v0.11.20`.
- Compare SHA-256 checksums for every scoped binary icon.
- Validate `manifest.json` and the Next.js icon metadata.
- Run formatting/lint checks and a Web production build.
- Run relevant existing tests. The pre-existing nested-CBZ metadata test failure is recorded as a baseline issue and is not part of this icon-only change.
- Inspect Git changes to ensure only the design document and icon-related files changed.

## Ephemeral Real-Site E2E

After local verification, use Playwright CLI against an operator-provided self-hosted library URL supplied only at runtime.

- Do not add the URL, credentials, storage state, screenshots, traces, or generated test files to the repository.
- Do not persist the URL in Git configuration or project environment files.
- Verify page load, icon/manifest delivery, visible branding, and the available library flow.
- If authentication is required, accept credentials only at runtime and do not save browser state.
- Store any temporary diagnostic artifact outside the repository and delete it after inspection.

## Failure Behavior

If an official asset cannot be matched, a declaration still references a removed icon, a scoped build fails, or the real-site smoke test shows a regression, stop without merging the implementation. Unrelated baseline failures are reported separately rather than fixed in this change.
