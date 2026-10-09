#!/usr/bin/env python3
"""Check a sideload IPA against what `tauri ios build` would have produced.

build-unsigned-ipa.sh drives cargo and xcodebuild directly instead of going
through the Tauri CLI, so every step the CLI performs has to be reproduced by
hand -- and twice now a missing one shipped silently (the dev-mode binary, then
the Info.plist merge that left tao 0.37 a 0x0 WebView: a black screen). This
check derives its expectations from the same sources the CLI reads, so whatever
upstream adds there later is covered without editing this file:

  - Info.plist: every key from src-tauri/Info.plist, src-tauri/Info.ios.plist
    and tauri.conf.json bundle.iOS.infoPlist, merged in the CLI's order
    (tauri-cli src/mobile/ios/build.rs), must be present with the same value.
  - bundle.fileAssociations: every extension must be openable from Files.
  - bundle.iOS.minimumSystemVersion must be the deployment target.
  - The frontend must be embedded (a release, custom-protocol build), not
    loaded from devUrl.
  - Sideload transforms must hold: no app extensions, the sideload bundle id.

Each deliberate deviation is listed in ALLOWED with its reason. Exits non-zero
and prints every failure, so CI fails before a release is published.

Usage:  scripts/sideload/verify-ipa.py path/to.ipa [--version X.Y.Z]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import plistlib
import re
import sys
import tempfile
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[2]
TAURI = REPO / "apps/readest-app/src-tauri"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

prepare = import_module("prepare-project")

# Info.plist keys whose built value legitimately differs from the merged
# sources. Anything not listed here must match exactly.
ALLOWED = {
    # prepare-project.py declares the phone scene explicitly and drops the
    # CarPlay role, whose entitlement a free personal team cannot sign.
    "UIApplicationSceneManifest": prepare.SCENE_MANIFEST,
}

# Extensions the official build would register through generated
# CFBundleDocumentTypes (tauri_utils file_associations_plist) but this
# pipeline does not generate. Remove an entry once the gap is closed.
UNREGISTERED_EXTENSIONS = {
    "md": "declared only in tauri.conf.json fileAssociations, not in Info.plist",
}


def load_plist(path: pathlib.Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


def expected_info() -> dict:
    """The CLI's merge: Info.plist, then Info.ios.plist, then bundle.iOS.infoPlist."""
    merged: dict = {}
    for source in prepare.info_sources():
        if source.exists():
            merged.update(load_plist(source))
    return merged


def openable_extensions(info: dict) -> set[str]:
    """Extensions Files can hand to the app, directly or via a declared UTI."""
    types = info.get("CFBundleDocumentTypes", [])
    extensions = {e.lower() for t in types for e in t.get("CFBundleTypeExtensions", [])}
    content_types = {u for t in types for u in t.get("LSItemContentTypes", [])}
    for key in ("UTImportedTypeDeclarations", "UTExportedTypeDeclarations"):
        for declaration in info.get(key, []):
            if declaration.get("UTTypeIdentifier") in content_types:
                spec = declaration.get("UTTypeTagSpecification", {})
                extensions |= {e.lower() for e in spec.get("public.filename-extension", [])}
    # System-declared types an app can list without declaring them itself.
    system = {"com.adobe.pdf": "pdf", "public.plain-text": "txt", "org.idpf.epub-container": "epub"}
    extensions |= {ext for uti, ext in system.items() if uti in content_types}
    return extensions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ipa", type=pathlib.Path)
    parser.add_argument("--version", help="expected CFBundleShortVersionString")
    args = parser.parse_args()

    config = json.loads((TAURI / "tauri.conf.json").read_text())
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(args.ipa) as ipa:
        ipa.extractall(tmp)
        apps = list(pathlib.Path(tmp, "Payload").glob("*.app"))
        if len(apps) != 1:
            print(f"FAIL: expected one .app in Payload/, found {len(apps)}")
            return 1
        app = apps[0]
        info = load_plist(app / "Info.plist")
        binary = (app / info["CFBundleExecutable"]).read_bytes()
        has_extensions = (app / "PlugIns").exists() and any((app / "PlugIns").iterdir())

    for key, value in expected_info().items():
        want = ALLOWED.get(key, value)
        if key not in info:
            failures.append(f"Info.plist is missing {key}")
        elif info[key] != want:
            failures.append(f"Info.plist {key} differs from its source")

    openable = openable_extensions(info)
    for association in config.get("bundle", {}).get("fileAssociations") or []:
        for ext in association.get("ext", []):
            if ext.lower() not in openable and ext not in UNREGISTERED_EXTENSIONS:
                failures.append(f"file association .{ext} is not registered in CFBundleDocumentTypes")

    minimum = (config.get("bundle", {}).get("iOS") or {}).get("minimumSystemVersion")
    if minimum and info.get("MinimumOSVersion") != minimum:
        failures.append(f"MinimumOSVersion is {info.get('MinimumOSVersion')}, config says {minimum}")

    if args.version and info.get("CFBundleShortVersionString") != args.version:
        failures.append(f"CFBundleShortVersionString is {info.get('CFBundleShortVersionString')}, expected {args.version}")

    if info.get("CFBundleIdentifier") != prepare.BUNDLE:
        failures.append(f"CFBundleIdentifier is {info.get('CFBundleIdentifier')}, expected {prepare.BUNDLE}")
    if has_extensions:
        failures.append("app extensions are embedded; a free personal team cannot sign them")

    # A custom-protocol build embeds the frontend keyed by path; a dev build
    # has no such table and loads devUrl instead.
    chunk_paths = len(re.findall(rb"/_next/static/chunks/", binary))
    if b"/index.html" not in binary or chunk_paths < 50:
        failures.append(f"frontend is not embedded (/index.html missing or only {chunk_paths} chunk paths)")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        print(f"{len(failures)} problem(s) in {args.ipa.name}")
        return 1
    print(f"OK: {args.ipa.name} matches what tauri ios build would produce (allowing {sorted(ALLOWED)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
