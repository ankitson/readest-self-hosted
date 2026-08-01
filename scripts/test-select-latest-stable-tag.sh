#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SELECTOR="$ROOT_DIR/scripts/select-latest-stable-tag.sh"

actual="$(printf '%s\n' v0.11.9 v0.11.20 v0.12.0-rc.1 nightly v1.0.0 | "$SELECTOR")"
test "$actual" = "v1.0.0"

actual="$(printf '%s\n' v2.9.0 v2.10.0 v10.0.0 v01.2.3 v1.02.3 | "$SELECTOR")"
test "$actual" = "v10.0.0"

if printf '%s\n' v1.2.3-beta.1 latest selfhost-v1.2.3 | "$SELECTOR" >/dev/null 2>&1; then
  echo "selector accepted input without a strict stable tag" >&2
  exit 1
fi

echo "Stable tag selector tests passed."
