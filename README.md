# Bank Statement Assistant

Private, single-user bank statement analysis running locally in k3s. The repository is
delivered in the verified increments defined in [`docs/product-design.md`](docs/product-design.md).

The repository now provides the runnable modular-monolith foundation, a verified Statements
vertical slice, and the first reviewable Transactions slice:

- FastAPI application with liveness/schema-head readiness endpoints and a built-in React shell
- PostgreSQL/Alembic persistence with atomic claims, expiring leases, and exponential backoff
- Worker process with bounded stage execution and privacy-safe structured logs
- Generated OpenAPI TypeScript contracts with backend/frontend drift checks in CI
- One non-root application image used by the web, worker, and migration processes
- k3s Namespace, PostgreSQL StatefulSet, PVCs, migration Job, probes, and internal Service
- Private GPU-backed vLLM deployment pinned to Qwen3-8B-AWQ, an exact image digest, and model revision
- Safe single-PDF upload, transparent empty-password PDF handling, content-hash duplicate detection,
  generated PVC paths, durable status, and source reprocessing for failed extraction
- Deterministic PDF text extraction and registered bank-layout parsing, exact reconciliation,
  local-LLM transaction Classification, review publication, bounded retries, visible failure,
  and retry through REST and React
- Provisional extracted Transactions persisted with immutable page/line evidence, linked Review
  Findings, persisted classification provenance, REST filtering/sorting/pagination, and an
  evidence-preserving React ledger view
- Python and TypeScript linting, type checks, tests, frontend build, and manifest rendering in CI

The remainder of Increment 2 remains intentionally open: Bank Account fingerprint resolution,
Processing Attempt history/progress streaming, multi-file drag-and-drop, scanned-PDF detection,
archive, and confirmed permanent deletion are not implemented by this slice. Transaction
corrections, revision history/revert, and user acceptance of low-confidence classifications
are implemented. Reports, rules, and the Financial Assistant remain later increments.

## Development

Prerequisites: Python 3.12, `uv`, Node.js 24, npm, Docker, and kubectl/Kustomize.

```bash
uv sync
cd frontend && npm ci
```

Copy `.env.example` to `.env`, replace the database password, create the database, then run:

```bash
uv run alembic upgrade head
uv run bsa-api
```

In another terminal, run the durable worker:

```bash
uv run bsa-worker
```

Classification research is optional. To use the bounded Chromium search provider locally, install
the Playwright browser once and set these values in `.env`:

```bash
uv run playwright install chromium
BSA_CLASSIFICATION_RESEARCH_ENABLED=true
BSA_SEARCH_PROVIDER=browser
```

The worker searches the first result page and deterministically fetches one additional page only
when the first page lacks enough matching evidence. It never gives the model arbitrary browser
navigation. Leave `BSA_SEARCH_PROVIDER=brave` and provide `BSA_SEARCH_API_KEY` to use the managed
HTTP provider instead. The application image installs Chromium when it is built.

For frontend development, run `npm run dev` from `frontend/`; requests under `/api` are proxied
to `127.0.0.1:8000`. `make verify` runs the complete local verification suite when PostgreSQL is
available through `TEST_DATABASE_URL`.

## Container image

Build the single application image from the repository root:

The release script builds from a source fingerprint, then deploys an immutable image-ID tag. It
imports that exact image into k3s/containerd and verifies the deployed web and worker modules before
reporting success. Do not build or import a mutable `:local` tag.

The final image contains the compiled frontend and runs as UID/GID `10001`. Its default command
starts the API; k3s overrides that command for migrations and the worker.

Both web and worker readiness require the exact Alembic head expected by the application image.
The worker also refuses to claim durable work until that head is present, protecting unexpected
Pod restarts while a release migration is still running.

Transaction extraction keeps each model request bounded and splits text-heavy pages only at line
boundaries, with small overlaps that retain the original page number and evidence. PDFs requiring a
real password remain unsupported; the original uploaded bytes are never replaced by a decrypted
copy.

## k3s deployment

The manifests intentionally expose no Ingress, NodePort, or LoadBalancer. Access the web Service
only through a loopback port-forward.

1. Create the Namespace separately:

   ```bash
   kubectl apply -f deploy/k8s/base/namespace.yaml
   ```

2. Copy `deploy/k8s/base/secret.example.yaml` outside the repository, replace both occurrences of
   the example password with one long random value, and apply that local file. Never commit it.
3. Deploy through the release script. It builds and imports a unique image derived from this
   checkout, server-validates the rendered manifests, creates a uniquely named migration Job, and
   verifies that both live application workloads contain the deterministic parser source. The release
   also starts the pinned private vLLM deployment; its first model-cache fill can take several minutes:

   ```bash
   ./scripts/deploy-k3s.sh
   ```

   Add `BSA_PRIVATE_BPI_FIXTURE=./BPI_2025-09.pdf` to your ignored `.env` file. The release
   script reads this path automatically and fails closed unless the fixture passes deterministic
   parsing and reconciliation.

   The k3s ConfigMap enables the keyless Playwright browser search provider. Chromium is installed
   into the application image during `docker build`; no `BSA_SEARCH_API_KEY` is required. The
   worker rollout also launches Chromium as a deployment verification step.

4. Open a loopback-only port-forward:

   ```bash
   kubectl port-forward --address 127.0.0.1 -n bank-statement-assistant service/web 8000:8000
   ```

If a previously imported PDF failed during Classification, uploading the same bytes returns the
existing Statement by content hash and does not create another job. Use that Statement's **Retry**
action to rerun its failed stage with the current worker and model configuration.

Routine validation must preserve the PostgreSQL, Statement source, and vLLM model-cache PVCs.

To stop only the application deployments while keeping the k3s cluster available, run:

```bash
./scripts/stop-k3s.sh --services --confirm
```

To stop the local k3s service itself, preserving its data and PVCs:

```bash
./scripts/stop-k3s.sh --cluster --confirm
```

Start the cluster again with `sudo systemctl start k3s` before using `kubectl`.

Generate a synthetic text-based statement for local smoke testing with:

```bash
uv run python scripts/generate-synthetic-statement.py /tmp/bsa-synthetic-statement.pdf
```

## Verification

Focused and full commands are deliberately separate:

```bash
uv run pytest tests/http/test_health.py
uv run pytest tests/jobs/test_worker.py
uv run pytest tests/jobs/test_postgres_job_queue.py  # requires migrated TEST_DATABASE_URL
npm --prefix frontend test
make verify
kubectl kustomize deploy/k8s/base >/dev/null
kubectl kustomize deploy/k8s/application >/dev/null
bash scripts/release-image-ref.sh
bash scripts/render-k3s-release.sh application "$(bash scripts/release-image-ref.sh)" >/dev/null
```

After deployment on the dedicated local instance, `./scripts/smoke-k3s.sh` verifies the migration
head, both probes, queued/running work across a worker restart, PostgreSQL data across a StatefulSet
restart, Statement PVC persistence, and a real worker-to-vLLM Classification request. Temporary
database rows and the Statement marker are removed on exit.

Real Statements and private evaluation data must never be added to this repository.
