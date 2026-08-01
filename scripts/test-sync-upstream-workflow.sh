#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

sync=.github/workflows/sync-upstream.yml
build=.github/workflows/build-selfhost.yml
release=.github/workflows/release.yml
nightly=.github/workflows/nightly.yml
upload_r2=.github/workflows/upload-to-r2.yml

rg -q "refs/tags/upstream/v\*" "$sync"
rg -q "scripts/select-latest-stable-tag\.sh" "$sync"
rg -q "git merge-base --is-ancestor" "$sync"
rg -q "git rebase --onto" "$sync"
rg -q -- "--atomic" "$sync"
rg -q -- "--force-with-lease=refs/heads/main:" "$sync"
rg -q -- "--force-with-lease=refs/heads/selfhost-main:" "$sync"
rg -q 'HEAD:refs/tags/selfhost-\$latest_tag' "$sync"
rg -q "actions: write" "$sync"
rg -q "gh workflow run release-selfhost\.yml" "$sync"
rg -q 'git merge-base --is-ancestor "\$existing_tag_commit" HEAD' "$sync"
rg -q "pnpm lint" "$sync"
rg -q "pnpm --filter @readest/readest-app test --run" "$sync"
rg -q "luarocks --lua-version=5.1 install busted" "$sync"
rg -q "pnpm --filter @readest/readest-app test:lua" "$sync"
rg -q "pnpm --filter @readest/readest-app build-web" "$sync"
if rg -q "git rebase upstream/main" "$sync"; then
  echo "sync workflow still rebases directly onto upstream/main" >&2
  exit 1
fi
if sed -n '/^  push:/,/^permissions:/p' "$build" | rg -q .; then
  echo "build workflow still runs independently on tag pushes" >&2
  exit 1
fi
sed -n '/^  get-release:/,/^  update-release:/p' "$release" | \
  rg -q "if: github.repository == 'readest/readest'"
sed -n '/^  compute-version:/,/^  build:/p' "$nightly" | \
  rg -q "if: github.repository == 'readest/readest'"
sed -n '/^  build:/,/^  assemble-manifest:/p' "$nightly" | \
  rg -q "if: github.repository == 'readest/readest'"
sed -n '/^  assemble-manifest:/,$p' "$nightly" | \
  rg -q "github.repository == 'readest/readest'"
sed -n '/^  upload-to-r2:/,$p' "$upload_r2" | \
  rg -q "if: github.repository == 'readest/readest'"

echo "Stable sync workflow contract tests passed."
