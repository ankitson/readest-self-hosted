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
  'pnpm tauri android build --apk' \
  'pnpm tauri android build --split-per-abi --apk' \
  "Readest-Selfhost_\${version}_universal.apk" \
  "Readest-Selfhost_\${version}_x64-portable.exe" \
  "Readest-Selfhost_\${version}_arm64-portable.exe" \
  "Readest-Selfhost_\${version}_universal.dmg" \
  "Readest-Selfhost_\${version}_amd64.AppImage" \
  "Readest-Selfhost_\${version}_aarch64.AppImage"
do
  require_marker "$build" "$marker"
done

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

for marker in \
  'needs:' \
  '- build' \
  'scripts/prepare-selfhost-release.mjs' \
  '--draft' \
  '--draft=false' \
  '--latest' \
  "gh release upload \"\$release_tag\" release-assets/* --clobber"
do
  require_marker "$release" "$marker"
done

if rg -Fq -- 'const androidPlatforms' "$release"; then
  echo "Release workflow still contains the embedded partial manifest generator" >&2
  exit 1
fi

require_marker "$safety" 'bash scripts/test-prepare-selfhost-release.sh'
require_marker "$safety" 'bash scripts/test-selfhost-release-workflow.sh'

echo "Selfhost release workflow contract tests passed."
