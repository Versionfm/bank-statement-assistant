#!/usr/bin/env bash
set -euo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly placeholder="bank-statement-assistant:RELEASE_IMAGE"

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 <application|migration> <immutable-release-image>" >&2
  exit 2
fi

readonly target="$1"
readonly image_ref="$2"

if [[ ! "$image_ref" =~ ^bank-statement-assistant:sha-[a-f0-9]{64}$ ]]; then
  echo "Expected an immutable release image reference, got: $image_ref" >&2
  exit 2
fi

cd "$project_root"

case "$target" in
  application)
    rendered="$(kubectl kustomize deploy/k8s/application)"
    expected_references=3
    ;;
  migration)
    rendered="$(kubectl create --dry-run=client --validate=false -f deploy/k8s/migration-job.yaml -o yaml)"
    expected_references=1
    ;;
  *)
    echo "Unknown release render target: $target" >&2
    exit 2
    ;;
esac

actual_references="$(grep -Fc "image: $placeholder" <<<"$rendered" || true)"
if [[ "$actual_references" -ne "$expected_references" ]]; then
  echo "Expected $expected_references release image placeholders in $target, found $actual_references." >&2
  exit 1
fi

sed "s|$placeholder|$image_ref|g" <<<"$rendered"
