#!/usr/bin/env bash
set -euo pipefail

readonly namespace="bank-statement-assistant"
mode=""
confirmed=false

usage() {
  cat <<'EOF'
Usage:
  ./scripts/stop-k3s.sh --services --confirm  Stop application deployments.
  ./scripts/stop-k3s.sh --cluster --confirm   Stop the local k3s service.

Both modes preserve the namespace, PostgreSQL data, and PVCs.
EOF
}

while (($# > 0)); do
  case "$1" in
    --services|--cluster)
      if [[ -n "$mode" ]]; then
        echo "Choose only one of --services or --cluster." >&2
        usage >&2
        exit 2
      fi
      mode="${1#--}"
      ;;
    --confirm)
      confirmed=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "$mode" || "$confirmed" != true ]]; then
  echo "This command requires exactly one mode and --confirm." >&2
  usage >&2
  exit 2
fi

if [[ "$mode" == "services" ]]; then
  kubectl scale deployment/web deployment/worker deployment/vllm \
    --replicas=0 -n "$namespace"
  echo "Application deployments scaled to zero. PVCs and database data were preserved."
  exit 0
fi

echo "Stopping the k3s service. The cluster and kubectl API will be unavailable until k3s is started again."
sudo systemctl stop k3s
echo "k3s stopped. PVCs and database data were preserved."
