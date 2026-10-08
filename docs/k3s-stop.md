# Stop and restart local k3s

Run these commands from the repository root:

```bash
cd ~/bank-statement-assistant
```

## Stop application services

```bash
./scripts/stop-k3s.sh --services --confirm
```

This scales the `web`, `worker`, and `vllm` deployments to zero. The k3s
cluster stays available, and PostgreSQL, the namespace, PVCs, and application
data are preserved.

## Stop the k3s cluster

```bash
./scripts/stop-k3s.sh --cluster --confirm
```

This stops the local `k3s` system service. The Kubernetes API and workloads are
unavailable until k3s is started again. No namespace, PVC, or application data
is deleted.

## Start k3s again

```bash
sudo systemctl start k3s
kubectl get nodes
```

Both stop modes require `--confirm` intentionally, to prevent accidental
shutdowns.
