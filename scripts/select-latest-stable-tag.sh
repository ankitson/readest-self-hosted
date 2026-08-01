#!/usr/bin/env bash
set -euo pipefail

stable_tags=()
while IFS= read -r tag; do
  if [[ "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    stable_tags+=("$tag")
  fi
done

if [ "${#stable_tags[@]}" -eq 0 ]; then
  echo "No strict stable upstream tag was found." >&2
  exit 1
fi

printf '%s\n' "${stable_tags[@]}" | sort -V | tail -n 1
