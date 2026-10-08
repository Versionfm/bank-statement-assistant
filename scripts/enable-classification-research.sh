#!/usr/bin/env bash
set -euo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly namespace="bank-statement-assistant"
readonly secret_name="bank-statement-assistant-secrets"
readonly configmap_name="bank-statement-assistant-config"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"; unset search_api_key' EXIT

cd "$project_root"

echo "This will add the search key, enable research, and redeploy the current worker."
read -r -p "Continue? [y/N] " confirmation
[[ "$confirmation" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

kubectl get secret "$secret_name" -n "$namespace" >/dev/null
kubectl get configmap "$configmap_name" -n "$namespace" >/dev/null

read -r -s -p "Brave Search API key (hidden): " search_api_key
printf '\n'
if [[ -z "$search_api_key" ]]; then
  echo "The search API key must not be empty." >&2
  exit 1
fi

if [[ -z "${BSA_PRIVATE_BPI_FIXTURE:-}" && -f "$project_root/.env" ]]; then
  fixture_line="$(grep -E '^[[:space:]]*BSA_PRIVATE_BPI_FIXTURE[[:space:]]*=' "$project_root/.env" | tail -n 1 || true)"
  if [[ -n "$fixture_line" ]]; then
    BSA_PRIVATE_BPI_FIXTURE="${fixture_line#*=}"
    BSA_PRIVATE_BPI_FIXTURE="${BSA_PRIVATE_BPI_FIXTURE#\"}"
    BSA_PRIVATE_BPI_FIXTURE="${BSA_PRIVATE_BPI_FIXTURE%\"}"
    export BSA_PRIVATE_BPI_FIXTURE
  fi
fi

if [[ -z "${BSA_PRIVATE_BPI_FIXTURE:-}" || ! -r "$BSA_PRIVATE_BPI_FIXTURE" ]]; then
  echo "Set BSA_PRIVATE_BPI_FIXTURE to a readable private PDF, then rerun this script." >&2
  exit 1
fi

patch_file="$tmp_dir/secret-patch.json"
{
  printf '{"data":{"BSA_SEARCH_API_KEY":"'
  printf '%s' "$search_api_key" | base64 -w0
  printf '"}}\n'
} >"$patch_file"
chmod 600 "$patch_file"
kubectl patch secret "$secret_name" -n "$namespace" --type=merge --patch-file="$patch_file" >/dev/null

kubectl patch configmap "$configmap_name" -n "$namespace" --type=merge \
  -p '{"data":{"BSA_CLASSIFICATION_RESEARCH_ENABLED":"true","BSA_SEARCH_CACHE_TTL_SECONDS":"604800"}}' \
  >/dev/null

echo "Search key stored and research enabled. Deploying the current image..."
"$project_root/scripts/deploy-k3s.sh"
