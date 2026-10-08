#!/usr/bin/env bash
set -euo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$project_root"

mapfile -d '' -t build_inputs < <(
  git ls-files -co --exclude-standard -z -- \
    .dockerignore Dockerfile README.md alembic.ini migrations frontend pyproject.toml src uv.lock \
    | LC_ALL=C sort -z -u
)

if [[ "${#build_inputs[@]}" -eq 0 ]]; then
  echo "No Docker build inputs were found." >&2
  exit 1
fi

content_hash="$(printf '%s\0' "${build_inputs[@]}" | xargs -0 sha256sum | sha256sum | cut -c1-12)"
printf 'bank-statement-assistant:bsa-%s\n' "$content_hash"
