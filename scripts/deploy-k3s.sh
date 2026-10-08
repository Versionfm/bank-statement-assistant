#!/usr/bin/env bash
set -euo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly namespace="bank-statement-assistant"
readonly source_image_ref="$($project_root/scripts/release-image-ref.sh)"
readonly extraction_module="src/bank_statement_assistant/statements/extraction.py"
readonly extraction_module_hash="$(sha256sum "$project_root/$extraction_module" | awk '{print $1}')"
release_dir="$(mktemp -d)"
image_ref=""
imported_image_id=""

cleanup() {
  rm -rf "$release_dir"
}
trap cleanup EXIT

extract_image_digest() {
  awk 'match($0, /sha256:[a-f0-9]{64}/) { print substr($0, RSTART, RLENGTH); exit }'
}

verify_workload_artifact() {
  local workload="$1"
  local command="$2"
  local desired_image
  local installed_hash
  local pod
  local running_image_id

  desired_image="$(kubectl get deployment "$workload" -n "$namespace" \
    -o jsonpath='{.spec.template.spec.containers[0].image}')"
  if [[ "$desired_image" != "$image_ref" ]]; then
    echo "$workload deployment does not reference $image_ref." >&2
    exit 1
  fi

  pod="$(kubectl get pod -n "$namespace" -l "app.kubernetes.io/name=$workload" \
    --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
  if [[ -z "$pod" ]]; then
    echo "No running $workload Pod is available for artifact verification." >&2
    exit 1
  fi
  running_image_id="$(kubectl get pod "$pod" -n "$namespace" \
    -o jsonpath='{.status.containerStatuses[0].imageID}' | extract_image_digest)"
  if [[ -z "$running_image_id" ]]; then
    echo "Could not determine the running image ID for $workload." >&2
    exit 1
  fi
  if [[ "$running_image_id" != "$imported_image_id" ]]; then
    echo "$workload reports a platform image digest ($running_image_id); imported index is $imported_image_id." >&2
  fi
  installed_hash="$(kubectl exec -n "$namespace" "$pod" -c "$workload" -- \
    sha256sum "/app/.venv/lib/python3.12/site-packages/bank_statement_assistant/statements/extraction.py" \
    | awk '{print $1}')"
  if [[ "$installed_hash" != "$extraction_module_hash" ]]; then
    echo "$workload is not running the image built from this checkout." >&2
    exit 1
  fi

  kubectl exec -n "$namespace" "$pod" -c "$workload" -- /bin/sh -ec "$command"
}

cd "$project_root"

# Keep the private parser fixture configuration in the ignored .env file when
# it is not already supplied by the caller. Only this deploy-specific key is
# read; the rest of the application environment is not imported into the
# shell running the release.
if [[ -z "${BSA_PRIVATE_BPI_FIXTURE:-}" && -r "$project_root/.env" ]]; then
  fixture_line="$(grep -E '^[[:space:]]*BSA_PRIVATE_BPI_FIXTURE[[:space:]]*=' "$project_root/.env" | tail -n 1 || true)"
  if [[ -n "$fixture_line" ]]; then
    fixture_value="${fixture_line#*=}"
    fixture_value="$(printf '%s' "$fixture_value" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
    fixture_value="${fixture_value#\"}"
    fixture_value="${fixture_value%\"}"
    fixture_value="${fixture_value#\'}"
    fixture_value="${fixture_value%\'}"
    if [[ "$fixture_value" != /* ]]; then
      fixture_value="$project_root/$fixture_value"
    fi
    BSA_PRIVATE_BPI_FIXTURE="$fixture_value"
  fi
fi

kubectl apply -f deploy/k8s/base/namespace.yaml

if ! kubectl get secret bank-statement-assistant-secrets -n "$namespace" >/dev/null 2>&1; then
  echo "Missing Secret bank-statement-assistant-secrets in Namespace $namespace." >&2
  echo "Create it from deploy/k8s/base/secret.example.yaml outside Git, then retry." >&2
  exit 1
fi

if [[ -z "${BSA_PRIVATE_BPI_FIXTURE:-}" || ! -r "$BSA_PRIVATE_BPI_FIXTURE" ]]; then
  echo "Set BSA_PRIVATE_BPI_FIXTURE to a readable private BPI fixture before deployment." >&2
  exit 1
fi
BSA_PRIVATE_BPI_FIXTURE="$BSA_PRIVATE_BPI_FIXTURE" \
  .venv/bin/python -m pytest -q tests/statements/test_bpi_parser.py

docker build -t "$source_image_ref" .
image_id="$(docker image inspect --format '{{.Id}}' "$source_image_ref")"
image_ref="bank-statement-assistant:sha-${image_id#sha256:}"
docker tag "$source_image_ref" "$image_ref"

"$project_root/scripts/render-k3s-release.sh" application "$image_ref" \
  >"$release_dir/application.yaml"
"$project_root/scripts/render-k3s-release.sh" migration "$image_ref" \
  >"$release_dir/migration.yaml"

kubectl apply --dry-run=server -k deploy/k8s/base >/dev/null
kubectl apply --dry-run=server -f "$release_dir/application.yaml" >/dev/null
kubectl apply --dry-run=server -k deploy/k8s/inference >/dev/null
kubectl create --dry-run=server -f "$release_dir/migration.yaml" >/dev/null

docker save "$image_ref" | sudo k3s ctr images import -
imported_image_id="$(sudo k3s ctr images inspect "docker.io/library/$image_ref" \
  | extract_image_digest)"
if [[ -z "$imported_image_id" ]]; then
  echo "Could not determine the imported image ID for $image_ref." >&2
  exit 1
fi
if ! sudo k3s ctr images list | awk '{print $1}' \
  | grep -Fxq "docker.io/library/$image_ref"; then
  echo "Imported image $image_ref was not found in the k3s containerd image store." >&2
  exit 1
fi

kubectl apply -k deploy/k8s/base
kubectl rollout status statefulset/postgres -n "$namespace" --timeout=130s
kubectl apply -k deploy/k8s/inference
kubectl rollout status deployment/vllm -n "$namespace" --timeout=900s

migration_job="$(kubectl create -f "$release_dir/migration.yaml" -o name)"
kubectl wait --for=condition=complete "$migration_job" -n "$namespace" --timeout=130s
kubectl apply -f "$release_dir/application.yaml"
kubectl rollout status deployment/web -n "$namespace" --timeout=130s
kubectl rollout status deployment/worker -n "$namespace" --timeout=130s

verify_workload_artifact web 'test -x /app/.venv/bin/bsa-api'
verify_workload_artifact worker "python -c '
import socket
socket.create_connection = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError(\"network\"))
import bank_statement_assistant.statements.extraction as module
from bank_statement_assistant.statements.configured_parser import build_statement_extractor
from bank_statement_assistant.statements.models import ExtractedPage
assert not hasattr(module, \"OpenAIStatementExtractor\")
pages = (ExtractedPage(number=1, text=\"EXTRACTO INTEGRADO\\nPeríodo De 01/09/2025 a 30/09/2025\\nCONTA AGE Nº: 123 EUR\\nDEPÓSITOS À ORDEM\\nSALDO ANTERIOR CONTABILISTICO 10,00\\n01/09 01/09 Mercado -2,00 8,00\\nSALDO ACTUAL CONTABILISTICO 8,00\"),)
assert build_statement_extractor().extract(pages).provenance.extraction_strategy == \"deterministic\"
from playwright.sync_api import sync_playwright
playwright = sync_playwright().start()
browser = playwright.chromium.launch(headless=True)
browser.close()
playwright.stop()
'"

echo "Deployment ready with $image_ref. Browser search is enabled without an API key."
echo "Open a loopback port-forward with:"
echo "kubectl port-forward --address 127.0.0.1 -n $namespace service/web 8000:8000"
