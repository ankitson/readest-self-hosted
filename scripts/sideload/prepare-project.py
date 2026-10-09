#!/usr/bin/env python3
"""Prepare gen/apple for an UNSIGNED sideload build (SideStore / AltStore).

Sideload signers re-sign the app on-device with the user's own free Apple ID, so
the build itself needs no certificate, no team, and no provisioning profile. What
it does need is an app a free personal team is *able* to sign:

  - No restricted entitlements. Sign in with Apple, associated domains, App
    Groups and CarPlay cannot be provisioned by a personal team, and an
    entitlement no profile can back yields an app that installs but is killed at
    launch.
  - No app extensions. ShareExtension and ReadestWidget exist only to share an
    App Group with the host app, so they go with it.
  - A bundle id that will not collide with the App Store build of Readest, in
    case both end up on the same device.
  - The Info.plist keys `tauri ios build` would merge: src-tauri/Info.plist,
    src-tauri/Info.ios.plist, then tauri.conf.json bundle.iOS.infoPlist, in
    that order (tauri-cli src/mobile/ios/build.rs). This bare-xcodebuild
    pipeline has to do it itself. Most important is the scene manifest: tao
    0.37 attaches the main window to a UIWindowScene, and without one the
    WebView is laid out at 0x0 -- the app launches to a black screen.
    verify-ipa.py checks the built IPA against the same sources.

Everything here is a build-time transform of generated files; nothing is written
back to tracked sources except gen/apple/project.yml, which is itself generated
output that xcodegen consumes.

Env:
  SIDELOAD_BUNDLE_ID    default com.readest.selfhost.sideload
  SIDELOAD_PRODUCT_NAME default "Readest Selfhost"
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import re
import sys

BUNDLE = os.environ.get("SIDELOAD_BUNDLE_ID", "com.readest.selfhost.sideload")
PRODUCT = os.environ.get("SIDELOAD_PRODUCT_NAME", "Readest Selfhost")

ROOT = pathlib.Path(__file__).resolve().parents[2] / "apps/readest-app/src-tauri"
PROJ = ROOT / "gen/apple/project.yml"
ENTS = ROOT / "gen/apple/Readest_iOS/Readest_iOS.entitlements"
INFO = ROOT / "gen/apple/Readest_iOS/Info.plist"

# The phone scene, declared explicitly as upstream does from #6339 on (same tao
# 0.37), with single-scene mode so Files on iPad cannot open a second, blank
# scene. The CarPlay role is left out: its entitlement is stripped above.
SCENE_MANIFEST = {
    "UIApplicationSupportsMultipleScenes": False,
    "UISceneConfigurations": {
        "UIWindowSceneSessionRoleApplication": [
            {
                "UISceneClassName": "UIWindowScene",
                "UISceneConfigurationName": "Default",
                "UISceneDelegateClassName": "TaoSceneDelegate",
            }
        ]
    },
}

EMPTY_ENTITLEMENTS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    '<plist version="1.0">\n'
    "<!-- Emptied for unsigned sideload builds; see scripts/sideload/prepare-project.py -->\n"
    "<dict/>\n"
    "</plist>\n"
)


def info_sources() -> list[pathlib.Path]:
    """The plists `tauri ios build` merges into Info.plist, in its order."""
    sources = [ROOT / "Info.plist", ROOT / "Info.ios.plist"]
    config = json.loads((ROOT / "tauri.conf.json").read_text())
    overlay = (config.get("bundle", {}).get("iOS") or {}).get("infoPlist")
    if overlay:
        sources.append((ROOT / overlay).resolve())
    return sources


def main() -> None:
    if not PROJ.exists():
        sys.exit(f"missing {PROJ} - run `pnpm tauri ios init` first")

    text = PROJ.read_text()
    changes: list[str] = []

    # Drop the extension targets. Both sit at the end of the file, ShareExtension
    # first, so truncating there removes both.
    start = text.find("\n  ShareExtension:")
    if start != -1:
        text = text[:start] + "\n"
        changes.append("removed ShareExtension + ReadestWidget targets")

    # ...and the host app's dependency entries that referenced them.
    out, lines, i = [], text.splitlines(keepends=True), 0
    while i < len(lines):
        if re.match(r"\s*- target: (ShareExtension|ReadestWidget)\s*$", lines[i]):
            name = lines[i].split(":")[1].strip()
            i += 1
            while i < len(lines) and re.match(r"\s+(embed|codeSign):", lines[i]):
                i += 1
            changes.append(f"removed dependency on {name}")
            continue
        out.append(lines[i])
        i += 1
    text = "".join(out)

    # Identity. bundleIdPrefix and PRODUCT_BUNDLE_IDENTIFIER both carry upstream's id.
    n = text.count("com.bilingify.readest")
    if n:
        text = text.replace("com.bilingify.readest", BUNDLE)
        changes.append(f"bundle id -> {BUNDLE} ({n}x)")

    text, n = re.subn(r"^(\s*)PRODUCT_NAME: .*$", rf"\1PRODUCT_NAME: {PRODUCT}", text, flags=re.M)
    if n:
        changes.append(f"product name -> {PRODUCT}")

    # No signing identity is wanted at all; xcodebuild is invoked with
    # CODE_SIGNING_ALLOWED=NO, and a stale team here only invites a lookup.
    text, n = re.subn(r"^\s*DEVELOPMENT_TEAM: .*\n", "", text, flags=re.M)
    if n:
        changes.append(f"dropped DEVELOPMENT_TEAM ({n}x)")

    PROJ.write_text(text)

    if ENTS.exists() and ENTS.read_text() != EMPTY_ENTITLEMENTS:
        ENTS.write_text(EMPTY_ENTITLEMENTS)
        changes.append("entitlements emptied")

    if INFO.exists():
        with INFO.open("rb") as f:
            info = plistlib.load(f)
        merged = dict(info)
        for source in info_sources():
            if source.exists():
                with source.open("rb") as f:
                    merged.update(plistlib.load(f))
                changes.append(f"merged {source.name}")
        merged["UIApplicationSceneManifest"] = SCENE_MANIFEST
        if merged != info:
            with INFO.open("wb") as f:
                plistlib.dump(merged, f)

    print("\n".join(f"  - {c}" for c in changes) if changes else "  (already prepared)")


if __name__ == "__main__":
    main()
