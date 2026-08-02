#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

version=0.11.20
release_tag="selfhost-v${version}"
assets_dir="$tmp_dir/release-assets"
notes_path="$tmp_dir/release-notes.md"
mkdir -p "$assets_dir"

assets=(
  "Readest-Selfhost_${version}_x64-setup.exe"
  "Readest-Selfhost_${version}_x64-setup.exe.sig"
  "Readest-Selfhost_${version}_x64-portable.exe"
  "Readest-Selfhost_${version}_x64-portable.exe.sig"
  "Readest-Selfhost_${version}_arm64-setup.exe"
  "Readest-Selfhost_${version}_arm64-setup.exe.sig"
  "Readest-Selfhost_${version}_arm64-portable.exe"
  "Readest-Selfhost_${version}_arm64-portable.exe.sig"
  "Readest-Selfhost_${version}_amd64.AppImage"
  "Readest-Selfhost_${version}_amd64.AppImage.sig"
  "Readest-Selfhost_${version}_amd64.deb"
  "Readest-Selfhost_${version}_amd64.deb.sig"
  "Readest-Selfhost-${version}-1.x86_64.rpm"
  "Readest-Selfhost-${version}-1.x86_64.rpm.sig"
  "Readest-Selfhost_${version}_aarch64.AppImage"
  "Readest-Selfhost_${version}_aarch64.AppImage.sig"
  "Readest-Selfhost_${version}_arm64.deb"
  "Readest-Selfhost_${version}_arm64.deb.sig"
  "Readest-Selfhost-${version}-1.aarch64.rpm"
  "Readest-Selfhost-${version}-1.aarch64.rpm.sig"
  "Readest-Selfhost_${version}_universal.dmg"
  "Readest-Selfhost_${version}_universal.app.tar.gz"
  "Readest-Selfhost_${version}_universal.app.tar.gz.sig"
  "Readest-Selfhost_${version}_universal.apk"
  "Readest-Selfhost_${version}_universal.apk.sig"
  "Readest-Selfhost_${version}_arm64.apk"
  "Readest-Selfhost_${version}_arm64.apk.sig"
  "Readest-Selfhost_${version}_armv7.apk"
  "Readest-Selfhost_${version}_armv7.apk.sig"
  "Readest-Selfhost_${version}_x64.apk"
  "Readest-Selfhost_${version}_x64.apk.sig"
  "Readest-Selfhost_${version}_x86.apk"
  "Readest-Selfhost_${version}_x86.apk.sig"
)

for asset in "${assets[@]}"; do
  if [[ "$asset" == *.sig ]]; then
    printf 'test-signature-for-%s\n' "${asset%.sig}" > "$assets_dir/$asset"
  else
    printf 'test-artifact-%s\n' "$asset" > "$assets_dir/$asset"
  fi
done

run_preparer() {
  RELEASE_TAG="$release_tag" \
    GITHUB_REPOSITORY=luoji12103/readest-self-hosted \
    SELFHOST_RESOLVED_RELEASE_VERSION="$version" \
    SELFHOST_RELEASE_ASSETS_DIR="$assets_dir" \
    SELFHOST_RELEASE_NOTES_PATH="$notes_path" \
    node scripts/prepare-selfhost-release.mjs
}

run_preparer

jq -e --arg version "$version" '.version == $version' "$assets_dir/latest.json" >/dev/null

expected_platforms=(
  android-arm64
  android-armv7
  android-i686
  android-universal
  android-x86_64
  darwin-aarch64
  darwin-aarch64-app
  darwin-universal
  darwin-universal-app
  darwin-x86_64
  darwin-x86_64-app
  linux-aarch64
  linux-aarch64-appimage
  linux-aarch64-deb
  linux-aarch64-rpm
  linux-x86_64
  linux-x86_64-appimage
  linux-x86_64-deb
  linux-x86_64-rpm
  windows-aarch64
  windows-aarch64-nsis
  windows-aarch64-portable
  windows-x86_64
  windows-x86_64-nsis
  windows-x86_64-portable
)

printf '%s\n' "${expected_platforms[@]}" | sort > "$tmp_dir/expected-platforms"
jq -r '.platforms | keys[]' "$assets_dir/latest.json" | sort > "$tmp_dir/actual-platforms"
diff -u "$tmp_dir/expected-platforms" "$tmp_dir/actual-platforms"

expected_base="https://github.com/luoji12103/readest-self-hosted/releases/download/${release_tag}/"
if jq -e --arg base "$expected_base" \
  '[.platforms[].url | startswith($base)] | all' \
  "$assets_dir/latest.json" >/dev/null; then
  :
else
  echo "Updater manifest contains a URL outside the selfhost release" >&2
  exit 1
fi

rg -q \
  'The macOS build is ad-hoc signed but is not Apple Developer ID signed or notarized; macOS Gatekeeper may display a warning\.' \
  "$notes_path"

missing_signature="Readest-Selfhost_${version}_arm64-portable.exe.sig"
rm "$assets_dir/$missing_signature"
rm "$assets_dir/latest.json" "$notes_path"

if run_preparer >"$tmp_dir/missing.stdout" 2>"$tmp_dir/missing.stderr"; then
  echo "Release preparation unexpectedly accepted a missing signature" >&2
  exit 1
fi
rg -q "Missing release assets: ${missing_signature}" "$tmp_dir/missing.stderr"

echo "Selfhost release asset preparation tests passed."
