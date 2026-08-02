# Readest Selfhost Multi-platform Release Design

## Goal

Build, sign where credentials permit, and publish a complete Readest Selfhost
`0.11.20` GitHub Release from the current selfhost commit. The release tag is
`selfhost-v0.11.20`, and all automatic updater URLs remain scoped to
`luoji12103/readest-self-hosted`.

## Chosen Approach

Extend the dedicated `build-selfhost.yml` and `release-selfhost.yml` workflows
instead of reusing the official Readest release workflow. The dedicated flow
keeps the fork identity, updater key, Android signing key, artifact names, and
release URLs isolated from `readest/readest`. GitHub-hosted native runners build
each operating system; local cross-compilation is not used for the release.

The official workflow remains guarded in the fork. No official Readest signing
credential, download endpoint, R2 destination, or release is used.

## Release Matrix and Assets

The release must contain these deterministic selfhost assets and their Tauri
updater signatures where listed:

| Platform | Architectures | Release assets |
| --- | --- | --- |
| Windows | x86_64, aarch64 | NSIS setup EXE and portable EXE for each architecture, plus `.sig` for every EXE |
| Linux | x86_64, aarch64 | AppImage, DEB, and RPM for each architecture, plus `.sig` for every package |
| macOS | Universal binary containing x86_64 and aarch64 | DMG, updater `.app.tar.gz`, and updater archive `.sig` |
| Android | Universal, arm64, armv7, x86_64, x86 | Android-signed APK and Tauri updater `.sig` for each variant |

Asset names start with `Readest-Selfhost_0.11.20` and use stable architecture
suffixes. This prevents generated Tauri product-name differences from leaking
into the public release contract.

iOS IPA distribution is excluded. The repository has neither an Apple mobile
distribution profile nor the App Store credentials needed to publish a usable
IPA, and upstream GitHub Releases do not publish an iOS IPA.

## Native Build Jobs

The reusable build workflow has independent jobs so one runner cannot silently
substitute for another:

- Windows uses `windows-latest` and builds x86_64 and aarch64 MSVC targets.
  Each leg preserves the NSIS installer before performing the portable build.
- Linux uses the same x86_64 and native aarch64 Ubuntu runners as upstream
  `v0.11.20`. Each leg builds AppImage, DEB, and RPM bundles. The pinned
  truly-portable AppImage tooling from the upstream stable workflow is reused.
- macOS uses `macos-latest`, installs both Apple Rust targets, and builds
  `universal-apple-darwin`.
- Android uses Ubuntu, Java 17, Android NDK `28.2.13676358`, and the existing
  selfhost keystore. It builds one universal APK and four split ABI APKs.

Every job applies the requested release version in its checkout, runs
`patch-tauri-selfhost`, and validates required secrets before the expensive
build. Build outputs are uploaded as GitHub Actions artifacts; build jobs never
create a Release directly.

## Signing and macOS Limitation

The existing independent Tauri updater key signs all updater-delivered files.
The existing Android keystore signs every APK at the Android package layer.
Neither key material nor the private test-library URL is written to tracked
files, logs, release notes, or artifacts.

The repository has no Apple Developer ID certificate, Apple ID credential, or
notarization credential. The macOS app is therefore ad-hoc signed where needed
to assemble a universal bundle, but it is not Developer ID signed or notarized.
The DMG remains downloadable and testable, and the Release notes explicitly
state that macOS Gatekeeper may warn. The workflow must not borrow official
Readest Apple credentials or pretend that notarization succeeded.

## Manifest and Publishing

`release-selfhost.yml` downloads artifacts only after every build job succeeds.
It rejects missing or duplicate expected assets, verifies that every required
updater asset has a non-empty `.sig`, and produces one race-free `latest.json`.

The manifest contains the official Tauri platform aliases plus the selfhost
Android variants:

- `windows-x86_64`, `windows-x86_64-nsis`,
  `windows-x86_64-portable`, `windows-aarch64`,
  `windows-aarch64-nsis`, and `windows-aarch64-portable`;
- `linux-x86_64`, `linux-x86_64-appimage`, `linux-x86_64-deb`,
  `linux-x86_64-rpm`, and the matching `linux-aarch64` keys;
- `darwin-x86_64`, `darwin-aarch64`, `darwin-universal`, and their
  `-app` aliases, all pointing to the universal updater archive;
- `android-universal`, `android-arm64`, `android-armv7`,
  `android-x86_64`, and `android-i686`.

The workflow creates or updates the non-draft, non-prerelease GitHub Release
only after manifest validation passes, uploads the complete asset set with
`--clobber`, and marks `selfhost-v0.11.20` as the latest release. Publishing the
Release may trigger the repository's existing amd64/arm64 Docker image workflow;
that behavior remains enabled.

## Branch and Tag Flow

Before dispatching the release, the verified current selfhost commit is pushed
atomically to both `main` and `selfhost-main` with explicit
`--force-with-lease` protections against concurrent remote changes. The
release tag is `selfhost-v0.11.20`. No pull request is created.

Only the stable upstream version controls release cadence. The daily scheduler
may check for upstream tags, but it publishes only when a new strict
`vX.Y.Z` stable tag exists.

## Failure Handling

- Matrix jobs use `fail-fast: false` so all platform failures remain visible,
  but the publish job requires every job to succeed.
- Missing secrets, packages, signatures, platform keys, or malformed JSON fail
  the workflow before Release creation or update.
- A failed build leaves only temporary Actions artifacts and does not create an
  incomplete public Release.
- A remote branch change causes the atomic push to fail rather than overwrite
  work outside the verified commit.
- A failed Release run is diagnosed and rerun on the same tag only after its
  cause is corrected; versioned assets are replaced deterministically.

## Verification

Before pushing, repository contract tests must prove the full selfhost matrix,
required asset names, signing gates, manifest platform keys, and official-host
exclusions. Workflow syntax, formatting, selfhost safety scans, and the existing
project test/build gates must remain green.

After the remote run completes, verification uses authoritative GitHub state:

1. Every build job is successful at the tagged commit.
2. The Release is public, non-draft, non-prerelease, and points at
   `selfhost-v0.11.20`.
3. Every required asset exists once, has non-zero size, and is downloadable.
4. Every required `.sig` is non-empty.
5. `latest.json` parses, reports version `0.11.20`, contains every required
   platform key, references only this repository and tag, and resolves to the
   published assets.
6. The macOS limitation appears in Release notes.
7. The repository contains no private test URL or signing material.
