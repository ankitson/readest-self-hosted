#!/usr/bin/env bash
set -euo pipefail

awk -F 'certificate SHA-256 digest: ' '
  NF == 2 && ($1 ~ /^Signer #[[:digit:]]+ $/ || $1 ~ /^V[[:digit:]]+([.][[:digit:]]+)? Signer: $/) {
    digest = $2
    gsub(/[[:space:]:]/, "", digest)
    if (length(digest) == 64 && digest !~ /[^[:xdigit:]]/) {
      print tolower(digest)
      exit
    }
  }
'
