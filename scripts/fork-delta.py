#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Inventory this fork's divergence from upstream, so a merge is a checklist.

`docs/FORK.md` is the durable narrative; this is the mechanical view that keeps
it honest. Run it before and after an upstream merge: the delta should shrink or
stay flat, and any file that appears here and is NOT explained in FORK.md is
either something to document or something to drop.

Usage: fork-delta.py [--upstream readest/main] [--files] [--check]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Paths that are ours by construction — the fork's own surface, not divergence
# from upstream code. Listing them keeps the signal in the "shared code" bucket,
# which is the part that actually costs merge effort.
FORK_OWNED_PREFIXES = (
    "docs/",
    ".github/workflows/build-selfhost",
    ".github/workflows/build-ios-sideload",
    ".github/workflows/build-desktop",
    ".github/workflows/sync-upstream",
    ".github/workflows/vercel-merge",
    "apps/readest-app/scripts/calibre-library-migration/",
    "apps/readest-app/scripts/patch-tauri-selfhost",
    "apps/readest-app/src/services/customServerConfig",
    "apps/readest-app/src/components/settings/ServerSettingsPanel",
    "apps/readest-app/src/services/annotation/providers/appleBooks",
    "apps/readest-app/src/app/reader/hooks/useAppleBooksAnnotationImport",
    "apps/readest-app/src/hooks/useAutoUpdateCheck",
    "apps/readest-app/src/utils/build.ts",
    "apps/readest.koplugin/readest_selfupdate",
    "apps/readest.koplugin/spec/selfupdate_spec",
    "docker/volumes/db/migrations/9",
    "scripts/sideload/",
    "scripts/prepare-selfhost",
    "scripts/select-latest-stable-tag",
    "scripts/scan-public-fork-safety",
    "scripts/extract-android-certificate",
    "scripts/test-prepare-selfhost",
    "scripts/test-select-latest-stable-tag",
    "scripts/test-selfhost",
    "scripts/test-sync-upstream",
    "Justfile",
    "README.md",
    ".gitignore",
)


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default="readest/main")
    ap.add_argument("--files", action="store_true", help="list every diverging file")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if shared-code divergence grew past --max")
    ap.add_argument("--max", type=int, default=80,
                    help="shared-code file budget for --check (default 80; 72 at the 0.12.8 merge)")
    args = ap.parse_args()

    base = git("merge-base", "HEAD", args.upstream).strip()
    ahead = git("rev-list", "--count", f"{args.upstream}..HEAD").strip()
    behind = git("rev-list", "--count", f"HEAD..{args.upstream}").strip()

    changed = [f for f in git("diff", "--name-only", base, "HEAD").splitlines() if f]
    owned = [f for f in changed if f.startswith(FORK_OWNED_PREFIXES)]
    shared = [f for f in changed if not f.startswith(FORK_OWNED_PREFIXES)]

    print(f"merge base   {base[:9]}  ({git('log','-1','--format=%ci',base).strip()[:10]})")
    print(f"ours ahead   {ahead} commits")
    print(f"upstream ahead {behind} commits  <- unmerged upstream work")
    print()
    print(f"fork-owned files   {len(owned):>4}  (our own surface; cheap)")
    print(f"shared-code files  {len(shared):>4}  (divergence in upstream's files; this is the tax)")

    if args.files:
        print("\nshared-code divergence:")
        for f in sorted(shared):
            print(f"  {f}")

    if args.check and len(shared) > args.max:
        print(f"\nFAIL: shared-code divergence {len(shared)} exceeds budget {args.max}.")
        print("Drop what upstream now provides, or raise the budget deliberately.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
