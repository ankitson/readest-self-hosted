#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

build=.github/workflows/build-selfhost.yml
release=.github/workflows/release-selfhost.yml
safety=.github/workflows/selfhost-safety.yml

require_marker() {
  local file="$1"
  local marker="$2"
  if ! rg -Fq -- "$marker" "$file"; then
    echo "Missing release workflow marker in ${file}: ${marker}" >&2
    exit 1
  fi
}

# These markers intentionally contain literal shell variable references.
# shellcheck disable=SC2016
for marker in \
  'fail-fast: false' \
  'windows-latest' \
  'x86_64-pc-windows-msvc' \
  'aarch64-pc-windows-msvc' \
  'ubuntu-22.04' \
  'ubuntu-22.04-arm' \
  'x86_64-unknown-linux-gnu' \
  'aarch64-unknown-linux-gnu' \
  'macos-latest' \
  'universal-apple-darwin' \
  "APPLE_SIGNING_IDENTITY: '-'" \
  'cargo install tauri-cli --git https://github.com/tauri-apps/tauri --rev 503bdbc1eade37d50a64ea7f81dbe853338b7fda --locked --force' \
  'pnpm tauri android build --apk' \
  'pnpm tauri android build --split-per-abi --apk' \
  'Duplicate Android APKs for ABI' \
  'apksigner sign' \
  '--ks "$ANDROID_KEYSTORE_PATH"' \
  '--ks-key-alias "$ANDROID_KEY_ALIAS"' \
  '--ks-pass env:ANDROID_KEYSTORE_PASSWORD' \
  '--key-pass env:ANDROID_KEY_PASSWORD' \
  'apksigner verify --verbose --print-certs' \
  'keytool -exportcert' \
  'aapt dump badging' \
  'SELFHOST_ANDROID_CERT_SHA256: 903bf29bdf76ec24766e48eb8eafc0f0d228572be347008956b3f6aa63d753be' \
  'Android keystore certificate does not match the pinned selfhost certificate' \
  'Unexpected Android universal ABI set' \
  'Unexpected Android package identifier' \
  'Unexpected Android version' \
  "Readest-Selfhost_\${version}_universal.apk" \
  "Readest-Selfhost_\${version}_x64-portable.exe" \
  "Readest-Selfhost_\${version}_arm64-portable.exe" \
  "Readest-Selfhost_\${version}_universal.dmg" \
  "Readest-Selfhost_\${version}_amd64.AppImage" \
  "Readest-Selfhost_\${version}_aarch64.AppImage"
do
  require_marker "$build" "$marker"
done

python3 - <<'PY'
from pathlib import Path

text = Path('.github/workflows/build-selfhost.yml').read_text()
jobs = ('build-windows', 'build-linux', 'build-macos', 'build-android')
for index, job in enumerate(jobs):
    start = text.index(f'  {job}:')
    following = [text.find(f'  {candidate}:', start + 1) for candidate in jobs[index + 1 :]]
    following = [position for position in following if position != -1]
    end = min(following) if following else len(text)
    block = text[start:end]
    before_steps = block.split('    steps:', 1)[0]
    if '${{ secrets.' in before_steps:
        raise SystemExit(f'{job} exposes GitHub secrets at job scope')
PY

python3 - <<'PY'
from pathlib import Path

text = Path('.github/workflows/build-selfhost.yml').read_text()
start = text.index('      - name: Initialize signed Android project')
end = text.index('      - name:', start + 8)
block = text[start:end]
if 'ANDROID_KEYSTORE_BASE64' in block:
    raise SystemExit('Android project initialization still has access to the private keystore')
if 'TAURI_UPDATER_PUBKEY' not in block:
    raise SystemExit('Android project initialization is missing the public updater key')
if '      - name: Decode Android keystore' not in text:
    raise SystemExit('Android keystore does not have a dedicated decode step')
PY

python3 - <<'PY'
from pathlib import Path

text = Path('.github/workflows/build-selfhost.yml').read_text()
start = text.index('      - name: Build Android universal and split APKs')
end = text.index('      - name: Upload Android artifacts', start)
block = text[start:end]

android_sign = block.index('apksigner sign')
android_verify = block.index('apksigner verify --verbose --print-certs')
updater_sign = block.index('pnpm tauri signer sign "$apk"')
if not android_sign < android_verify < updater_sign:
    raise SystemExit('Final APKs must be Android-signed and verified before updater signatures are generated')
if 'pnpm tauri signer sign "$universal_asset"' in block or 'pnpm tauri signer sign "$asset"' in block:
    raise SystemExit('Updater signatures are generated before the final Android APK bytes are available')
PY

for forbidden_apple_secret in \
  APPLE_CERTIFICATE \
  APPLE_CERTIFICATE_PASSWORD \
  APPLE_ID \
  APPLE_PASSWORD \
  APPLE_TEAM_ID
do
  if rg -Fq -- "$forbidden_apple_secret" "$build"; then
    echo "Selfhost build workflow must not depend on ${forbidden_apple_secret}" >&2
    exit 1
  fi
done

if sed -n '/^  build-macos:/,/^  build-android:/p' "$build" | rg -q '\bmapfile\b'; then
  echo "macOS selfhost job uses mapfile, which is unavailable in system Bash 3.2" >&2
  exit 1
fi
if sed -n '/^  build-macos:/,/^  build-android:/p' "$build" | rg -Fq -- '--bundles dmg'; then
  echo "macOS selfhost job excludes the app updater target with a DMG-only build" >&2
  exit 1
fi

for marker in \
  "group: release-selfhost-\${{ github.repository }}-\${{ github.ref_type == 'tag' && github.ref_name || inputs.tag }}" \
  'cancel-in-progress: false' \
  'needs:' \
  '- build' \
  'scripts/prepare-selfhost-release.mjs' \
  "SELFHOST_RELEASE_PUB_DATE=\$(git show -s --format=%cI \"\$GITHUB_SHA\")" \
  'Existing public releases are immutable' \
  'isPrerelease' \
  '--draft' \
  '--draft=false' \
  '--prerelease=false' \
  '--latest' \
  'diff -u expected-assets.tsv remote-assets.tsv' \
  "gh release upload \"\$release_tag\" release-assets/* --clobber"
do
  require_marker "$release" "$marker"
done

if rg -Fq -- 'release_was_public' "$release"; then
  echo "Release workflow still permits in-place mutation of a public release" >&2
  exit 1
fi

if rg -Fq -- 'const androidPlatforms' "$release"; then
  echo "Release workflow still contains the embedded partial manifest generator" >&2
  exit 1
fi

require_marker "$safety" 'bash scripts/test-prepare-selfhost-release.sh'
require_marker "$safety" 'bash scripts/test-selfhost-release-workflow.sh'

echo "Selfhost release workflow contract tests passed."
