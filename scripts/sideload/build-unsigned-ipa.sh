#!/usr/bin/env bash
# Build an UNSIGNED, universal (iPhone + iPad) IPA for sideloading.
#
# Why unsigned: SideStore/AltStore re-sign on-device with the user's own free
# Apple ID, so the build needs no certificate, no provisioning profile, and no
# Apple account. That also means it runs anywhere -- including a GitHub-hosted
# macOS runner -- instead of only on a Mac whose login keychain is unlocked in a
# GUI session.
#
# The one wrinkle: the Xcode project's "Build Rust Code" phase shells out to
# `tauri ios xcode-script`, which connects back to the parent tauri CLI over a
# local JSON-RPC socket and therefore cannot run under a bare `xcodebuild`. So we
# compile the staticlib ourselves, drop it where the project expects it, and set
# READEST_PREBUILT_RUST=1 to skip the phase.
#
# Usage:  scripts/sideload/build-unsigned-ipa.sh [output.ipa]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$REPO/apps/readest-app"
OUT="${1:-$REPO/dist/readest-selfhost-unsigned.ipa}"
RUST_TARGET="${RUST_TARGET:-aarch64-apple-ios}"
DERIVED="${DERIVED_DATA:-$APP/src-tauri/gen/apple/build}"

# arm64 is the only shipping iOS arch; the project still carries an x86_64 slot
# for the simulator, which a sideload build never needs.
ARCH_DIR=arm64

cd "$APP"

echo "==> [1/7] vendored web assets (pdf.js, simplecc, jieba)"
pnpm --filter @readest/readest-app setup-vendors

echo "==> [2/7] fork self-host patch"
pnpm patch-tauri-selfhost

# Do this BEFORE the frontend build and before `tauri ios init`: the About
# dialog renders package.json's version through getAppVersion(), and
# tauri.conf.json sets "version": "../package.json", so overriding it here is
# what makes the in-app version, the generated Info.plist and the SideStore feed
# all agree. Stamping only the built Info.plist afterwards left About showing
# upstream's 0.11.21-selfhost.1 while SideStore showed 0.11.<run>.
if [ -n "${SIDELOAD_BUILD_NUMBER:-}" ]; then
  node - "$SIDELOAD_BUILD_NUMBER" <<'NODE'
const fs = require('node:fs');
const run = process.argv[2];
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
// Keep upstream's major.minor; the run number owns the patch. iOS allows at
// most three integers and no prerelease tag in CFBundleShortVersionString.
const [major, minor] = pkg.version.split('.');
pkg.version = `${major}.${minor}.${run}`;
fs.writeFileSync('package.json', `${JSON.stringify(pkg, null, 2)}\n`);
console.log(`    app version -> ${pkg.version}`);
NODE
fi

echo "==> [3/7] frontend production build"
pnpm build

echo "==> [4/7] scaffold generated iOS project files"
# src-tauri/gen is gitignored apart from a few force-added files, so a fresh
# checkout lacks Sources/, Assets.xcassets/, Externals/ etc. and xcodegen fails
# spec validation. `tauri ios init` fills them in -- but it skips Info.plist when
# gen/apple already exists, so scaffold a pristine tree aside and lift it over.
pnpm tauri ios init
plist=src-tauri/gen/apple/Readest_iOS/Info.plist
if [ ! -f "$plist" ]; then
  echo "    Info.plist absent after init; lifting from a pristine scaffold"
  mv src-tauri/gen/apple src-tauri/gen/apple.custom
  pnpm tauri ios init
  cp src-tauri/gen/apple/Readest_iOS/Info.plist src-tauri/gen/apple.custom/Readest_iOS/Info.plist
  rm -rf src-tauri/gen/apple
  mv src-tauri/gen/apple.custom src-tauri/gen/apple
fi
test -f "$plist"

# `tauri ios init` scaffolds Assets.xcassets from cargo-mobile2's template, whose
# AppIcon is the Tauri logo -- and gen/apple is gitignored, so the repo's real
# icons never reach the build. The 18 files in src-tauri/icons/ios are named
# exactly as the generated AppIcon.appiconset/Contents.json expects, so copying
# them over the placeholders is enough. (The Android job does the equivalent via
# `pnpm tauri icon`.)
iconset=src-tauri/gen/apple/Assets.xcassets/AppIcon.appiconset
if [ -d "$iconset" ] && [ -d src-tauri/icons/ios ]; then
  cp src-tauri/icons/ios/*.png "$iconset"/
  echo "    app icons: copied $(ls src-tauri/icons/ios/*.png | wc -l | tr -d ' ') files over the Tauri placeholders"
else
  echo "::warning::icon source or appiconset missing; shipping placeholder icons"
fi

echo "==> [5/7] strip un-provisionable capabilities, set sideload identity"
python3 "$REPO/scripts/sideload/prepare-project.py"
( cd src-tauri/gen/apple && xcodegen generate >/dev/null && echo "    Xcode project regenerated" )

echo "==> [6/7] compile Rust staticlib ($RUST_TARGET)"
# Several plugins (turso, native-tts, log) use swift-rs, which compiles Swift in
# a build script and picks its SDK from the environment. Under tauri the cargo
# build runs inside an xcodebuild script phase and inherits SDKROOT; standalone
# it does not, so swift-rs targets macOS and the link fails with
# "symbol(s) not found for architecture arm64". Supply the SDK explicitly.
export SDKROOT="${SDKROOT:-$(xcrun --sdk iphoneos --show-sdk-path)}"
export IPHONEOS_DEPLOYMENT_TARGET="${IPHONEOS_DEPLOYMENT_TARGET:-15.0}"
export PLATFORM_NAME="${PLATFORM_NAME:-iphoneos}"

# --features tauri/custom-protocol is NOT optional and NOT implied by --release.
# tauri's build.rs does `let dev = !custom_protocol`, so without this feature the
# binary is a DEV build: it ignores the embedded frontend and tries to load
# `devUrl` (http://localhost:3000), which on a device fails with
# "error sending request ... did you grant local network permissions?".
# `tauri build` passes it automatically; a bare `cargo build` must not forget it.
# The app crate declares no custom-protocol feature of its own, so enable it on
# the tauri dependency directly.
( cd src-tauri && cargo build --lib --release --target "$RUST_TARGET" \
    --features tauri/custom-protocol )

# This is a cargo workspace rooted at the repo, so the target dir is NOT
# src-tauri/target -- ask cargo rather than assuming.
TARGET_DIR="$(cd src-tauri && cargo metadata --format-version 1 --no-deps \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"

# The project links `libapp.a` from Externals/<arch>/<configuration>/.
mkdir -p "src-tauri/gen/apple/Externals/$ARCH_DIR/release"
cp "$TARGET_DIR/$RUST_TARGET/release/libreadestlib.a" \
   "src-tauri/gen/apple/Externals/$ARCH_DIR/release/libapp.a"

echo "==> [7/7] xcodebuild (unsigned) + package"
cd src-tauri/gen/apple
xcodebuild -project Readest.xcodeproj -scheme Readest_iOS \
  -configuration release -sdk iphoneos -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED" \
  READEST_PREBUILT_RUST=1 \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" CODE_SIGN_ENTITLEMENTS="" DEVELOPMENT_TEAM="" \
  build

app="$(ls -d "$DERIVED/Build/Products/release-iphoneos/"*.app | head -1)"

# Give every build a distinct CFBundleVersion. Both the marketing version and the
# build number are derived from package.json, so consecutive CI builds are
# byte-identical in version terms -- and AltStore/SideStore offer an update only
# when "version or buildVersion" differs from what is installed (dates are
# explicitly ignored). Without this, a new IPA is published and no client ever
# sees it. Safe to edit in place: the app is unsigned, so there is no signature
# to invalidate; the sideload signer signs afterwards.
if [ -n "${SIDELOAD_BUILD_NUMBER:-}" ]; then
  short="$(plutil -extract CFBundleShortVersionString raw -o - "$app/Info.plist")"
  major="${short%%.*}"; rest="${short#*.}"; minor="${rest%%.*}"
  stamped="$major.$minor.$SIDELOAD_BUILD_NUMBER"

  # BOTH fields get the run number, because SideStore decides whether an update
  # exists from CFBundleShortVersionString alone. Its InstalledApp.hasUpdate
  # parses each side as semver and compares major.minor.patch; buildVersion is
  # only ever displayed ("0.11.21 (0.11.10)") and used for identity, never for
  # the comparison. Leaving the short version pinned to upstream's meant every
  # build looked identical to the installed one and no update was ever offered.
  #
  # Apple allows at most three period-separated integers in either field, so the
  # run number takes the third component rather than being appended as a fourth.
  plutil -replace CFBundleShortVersionString -string "$stamped" "$app/Info.plist"
  plutil -replace CFBundleVersion -string "$stamped" "$app/Info.plist"
  echo "    version -> $stamped (short and build, from upstream $short)"
fi

work="$(mktemp -d)"
mkdir -p "$work/Payload"
cp -R "$app" "$work/Payload/"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
( cd "$work" && zip -qry "$OUT" Payload )
rm -rf "$work"

echo
echo "unsigned IPA: $OUT ($(du -h "$OUT" | cut -f1))"
echo "  app            $(basename "$app")"
echo "  bundle id      $(plutil -extract CFBundleIdentifier raw -o - "$app/Info.plist")"
echo "  version        $(plutil -extract CFBundleShortVersionString raw -o - "$app/Info.plist")"
echo "  device family  $(plutil -extract UIDeviceFamily json -o - "$app/Info.plist")  (1=iPhone, 2=iPad)"
