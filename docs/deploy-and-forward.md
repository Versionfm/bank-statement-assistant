# Deploy and forward the bank statement assistant

This is the local k3s workflow for building the application image, importing it into k3s, running the database migration, rolling out the web (including its loopback-only MCP sidecar) and worker workloads, and opening the web UI through a loopback-only port-forward.

The workflow keeps PostgreSQL, statement files, and the vLLM model cache in their existing PVCs. It does not expose the application to the LAN.

## Prerequisites

Run commands from the repository root:

```bash
cd ~/bank-statement-assistant
```

Confirm that Docker is reachable without changing the socket permissions:

```bash
stat -c '%A %U %G %n' /var/run/docker.sock
id
docker ps
```

The account must be in the `docker` group. If it was added recently, start a new login session or run `newgrp docker`. Do not use `chmod 666 /var/run/docker.sock`.

Confirm that kubectl is connected to the local k3s server:

```bash
kubectl cluster-info
kubectl get nodes
```

If the API server is unavailable on `127.0.0.1:6443`, fix k3s/context access before deploying. The release script performs server-side manifest validation and requires this connection.

## First deployment: create the Secret

Only do this once per cluster. Create a local copy outside Git, replace the example password with one long random value in both places, and apply it:

```bash
kubectl apply -f deploy/k8s/base/namespace.yaml
cp deploy/k8s/base/secret.example.yaml /tmp/bsa-secret.yaml
$EDITOR /tmp/bsa-secret.yaml
kubectl apply -f /tmp/bsa-secret.yaml
```

Verify only that the Secret exists; do not print its values:

```bash
kubectl get secret bank-statement-assistant-secrets -n bank-statement-assistant
```

## Build, import, migrate, and deploy

Set the path to a private BPI PDF. The PDF is used only as a deterministic parser fixture and must remain outside Git:

```bash
export BSA_PRIVATE_BPI_FIXTURE="$PWD/BPI_2025-09.pdf"
test -r "$BSA_PRIVATE_BPI_FIXTURE"
```

Run the release script:

```bash
./scripts/deploy-k3s.sh
```

The script performs these operations:

1. Runs the BPI parser tests.
2. Builds an image from the current checkout.
3. Tags it with an immutable SHA-based release reference.
4. Imports that exact image into the k3s containerd store.
5. Server-validates manifests.
6. Applies the base resources and pinned vLLM deployment.
7. Runs a uniquely named Alembic migration Job.
8. Rolls out the web and worker Deployments.
9. Verifies the installed application artifact and deterministic parser in both workloads.

The first vLLM rollout can take several minutes while the model cache is populated.

## Verify the rollout

```bash
kubectl get pods -n bank-statement-assistant -o wide
kubectl rollout status deployment/web -n bank-statement-assistant --timeout=130s
kubectl rollout status deployment/worker -n bank-statement-assistant --timeout=130s
kubectl rollout status deployment/vllm -n bank-statement-assistant --timeout=900s
```

Check application health from inside the cluster before forwarding:

```bash
kubectl exec -n bank-statement-assistant deployment/web -c web -- \
  curl --fail --silent http://127.0.0.1:8000/api/health/live
kubectl exec -n bank-statement-assistant deployment/web -c web -- \
  curl --fail --silent http://127.0.0.1:8000/api/health/ready

# The MCP sidecar is intentionally not a Service or Ingress; verify its local socket only.
kubectl get pod -n bank-statement-assistant -l app.kubernetes.io/name=web \
  -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="mcp")].ready}'
```

If a rollout fails, inspect logs without printing statement contents:

```bash
kubectl logs -n bank-statement-assistant deployment/web -c web --tail=100
kubectl logs -n bank-statement-assistant deployment/web -c mcp --tail=100
kubectl logs -n bank-statement-assistant deployment/worker -c worker --tail=100
kubectl logs -n bank-statement-assistant deployment/vllm -c vllm --tail=100
```

## Forward the web application

Keep this command running in a terminal:

```bash
kubectl port-forward --address 127.0.0.1 \
  -n bank-statement-assistant service/web 8000:8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in the browser. The `127.0.0.1` binding intentionally prevents LAN exposure. Stop the forward with `Ctrl-C`.

For API-only checks, use a second terminal:

```bash
curl --fail --silent http://127.0.0.1:8000/api/health/live
curl --fail --silent http://127.0.0.1:8000/api/health/ready
```

If inference needs to be inspected separately, use a different local port and stop it when finished:

```bash
kubectl port-forward --address 127.0.0.1 \
  -n bank-statement-assistant service/vllm 18001:8000
curl --fail --silent http://127.0.0.1:18001/v1/models
```

## Import or retry a statement

Import the PDF through the forwarded web UI. If the same PDF was already imported, its content hash makes the upload idempotent; uploading it again does not create a new processing Job.

For a failed existing Statement, use its **Retry** action. This reruns the failed stage with the newly deployed worker. Do not delete PVCs or re-upload the same PDF to create another attempt.

After retrying, watch the worker and statement status:

```bash
kubectl logs -f -n bank-statement-assistant deployment/worker -c worker
kubectl get pods -n bank-statement-assistant
```

## Optional smoke test

Run the repository smoke test after a deployment:

```bash
./scripts/smoke-k3s.sh
```

It creates and removes only its own marked smoke data, verifies migration and health probes, checks GPU inference, and exercises worker classification. It does not remove application PVCs.

## Shutdown and cleanup

Stop any foreground port-forward with `Ctrl-C`. The Kubernetes workloads may remain running for the next local session. Do not remove the namespace, PVCs, or Secret as routine cleanup; those contain application state and credentials.
