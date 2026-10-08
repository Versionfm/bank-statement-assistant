#!/usr/bin/env bash
set -euo pipefail

readonly namespace="bank-statement-assistant"
readonly marker="/var/lib/bank-statement-assistant/statements/.smoke-${RANDOM}"
readonly smoke_id="smoke-${RANDOM}-$$"
web_port_forward_pid=""
vllm_port_forward_pid=""
current_web_pod=""

postgres_sql() {
  local statement="$1"
  kubectl exec -n "$namespace" statefulset/postgres -c postgres -- \
    /bin/sh -ec 'psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
    smoke "$statement"
}

assert_smoke_jobs() {
  local states
  states="$(postgres_sql "
    SELECT status || '|' || count(*)
    FROM processing_jobs
    WHERE payload->>'smoke_test' = '$smoke_id'
    GROUP BY status
    ORDER BY status;
  ")"
  grep -qx 'queued|1' <<<"$states"
  grep -qx 'running|1' <<<"$states"
}

cleanup() {
  if [[ -n "$web_port_forward_pid" ]]; then
    kill "$web_port_forward_pid" 2>/dev/null || true
  fi
  if [[ -n "$vllm_port_forward_pid" ]]; then
    kill "$vllm_port_forward_pid" 2>/dev/null || true
  fi
  if [[ -n "$current_web_pod" ]]; then
    kubectl exec -n "$namespace" "$current_web_pod" -c web -- rm -f "$marker" >/dev/null 2>&1 || true
  fi
  postgres_sql "DELETE FROM statements WHERE content_hash LIKE '$smoke_id-%';" \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl get namespace "$namespace" >/dev/null
kubectl exec -n "$namespace" deployment/web -c web -- alembic current | grep -q '(head)'

current_web_pod="$(
  kubectl get pod -n "$namespace" -l app.kubernetes.io/name=web \
    -o jsonpath='{.items[0].metadata.name}'
)"
kubectl exec -n "$namespace" "$current_web_pod" -c web -- \
  /bin/sh -ec "printf smoke > '$marker'"

postgres_sql "
  WITH queued_statement AS (
    INSERT INTO statements (
      id, account_reference, original_filename, content_hash, source_path,
      page_count, status, current_stage
    ) VALUES (
      gen_random_uuid(), 'Smoke', 'queued.pdf', '$smoke_id-queued',
      '$marker-queued', 1, 'processing', 'extract_text'
    ) RETURNING id
  )
  INSERT INTO processing_jobs (statement_id, stage, payload, available_at)
  SELECT
    id,
    'extract_text',
    jsonb_build_object('smoke_test', '$smoke_id'),
    now() + interval '1 hour'
  FROM queued_statement;
  WITH running_statement AS (
    INSERT INTO statements (
      id, account_reference, original_filename, content_hash, source_path,
      page_count, status, current_stage
    ) VALUES (
      gen_random_uuid(), 'Smoke', 'running.pdf', '$smoke_id-running',
      '$marker-running', 1, 'processing', 'extract_text'
    ) RETURNING id
  )
  INSERT INTO processing_jobs (
    statement_id, stage, payload, status, attempts,
    claimed_at, claimed_by, lease_expires_at
  )
  SELECT
    id,
    'extract_text',
    jsonb_build_object('smoke_test', '$smoke_id'),
    'running',
    1,
    now(),
    'smoke-test-worker',
    now() + interval '1 hour'
  FROM running_statement;
" >/dev/null
assert_smoke_jobs

kubectl rollout restart deployment/web deployment/worker -n "$namespace"
kubectl rollout status deployment/web -n "$namespace" --timeout=130s
kubectl rollout status deployment/worker -n "$namespace" --timeout=130s
assert_smoke_jobs

kubectl rollout restart statefulset/postgres -n "$namespace"
kubectl rollout status statefulset/postgres -n "$namespace" --timeout=130s
assert_smoke_jobs

current_web_pod="$(
  kubectl get pod -n "$namespace" -l app.kubernetes.io/name=web \
    -o jsonpath='{.items[0].metadata.name}'
)"
kubectl exec -n "$namespace" "$current_web_pod" -c web -- test -f "$marker"

kubectl port-forward --address 127.0.0.1 -n "$namespace" service/web 18000:8000 \
  >/tmp/bsa-smoke-port-forward.log 2>&1 &
web_port_forward_pid="$!"
sleep 2
curl --fail --silent --show-error http://127.0.0.1:18000/api/health/live >/dev/null
curl --fail --silent --show-error http://127.0.0.1:18000/api/health/ready >/dev/null

kubectl port-forward --address 127.0.0.1 -n "$namespace" service/vllm 18001:8000 \
  >/tmp/bsa-smoke-vllm-port-forward.log 2>&1 &
vllm_port_forward_pid="$!"
sleep 2
curl --fail --silent --show-error http://127.0.0.1:18001/v1/models \
  | grep -q 'bank-statement-qwen'
inference_response="$(
  curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    --data '{"model":"bank-statement-qwen","messages":[{"role":"user","content":"Return status ok."}],"temperature":0,"max_tokens":32,"chat_template_kwargs":{"enable_thinking":false},"response_format":{"type":"json_schema","json_schema":{"name":"smoke_status","strict":true,"schema":{"type":"object","additionalProperties":false,"properties":{"status":{"type":"string","enum":["ok"]}},"required":["status"]}}}}' \
    http://127.0.0.1:18001/v1/chat/completions
)"
python3 -c \
  'import json, sys; response=json.load(sys.stdin); assert json.loads(response["choices"][0]["message"]["content"]) == {"status": "ok"}' \
  <<<"$inference_response"

worker_classification_response="$(
  postgres_sql "
    WITH smoke_statement AS (
      INSERT INTO statements (
        id, account_reference, original_filename, content_hash, source_path,
        page_count, status, current_stage
      ) VALUES (
        gen_random_uuid(), 'Smoke', 'classification.pdf', '$smoke_id-classification',
        '$marker-classification', 1, 'processing', 'classify'
      ) RETURNING id
    ), smoke_transaction AS (
      INSERT INTO transactions (
        id, statement_id, source_ordinal, booking_date, description,
        signed_amount, currency, confidence, source_identity
      )
      SELECT
        gen_random_uuid(), id, 1, DATE '2025-09-01', 'ATM CASH WITHDRAWAL',
        -20.00, 'EUR', 1.0, '$smoke_id-classification-transaction'
      FROM smoke_statement
      RETURNING statement_id
    )
    INSERT INTO processing_jobs (statement_id, stage, payload)
    SELECT statement_id, 'classify', jsonb_build_object('smoke_test', '$smoke_id-classification')
    FROM smoke_transaction;
  " >/dev/null
  for _ in $(seq 1 120); do
    result="$(postgres_sql "
      SELECT
        (SELECT status FROM processing_jobs
         WHERE payload->>'smoke_test' = '$smoke_id-classification'
         ORDER BY created_at DESC LIMIT 1)
        || '|' ||
        (SELECT count(*) FROM transaction_classifications AS tc
         JOIN transactions AS t ON t.id = tc.transaction_id
         WHERE t.source_identity = '$smoke_id-classification-transaction');
    ")"
    if [[ "$result" == "succeeded|1" ]]; then
      printf '%s' "$result"
      break
    fi
    sleep 1
  done
)"
[[ "$worker_classification_response" == "succeeded|1" ]]

echo "k3s smoke test passed: migration, probes, workload recovery, three PVCs, and GPU inference"
