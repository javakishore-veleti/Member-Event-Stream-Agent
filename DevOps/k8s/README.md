# Kubernetes manifests

Production-shaped manifests for deploying `member-event-stream-agent` to
any Kubernetes cluster (GKE, EKS, AKS, on-prem). The Cloud Run pipeline
under `.github/workflows/GCP_*.yml` is the lighter alternative; this
folder is for deployments that need pod-level controls (HPA, PDB,
network policies, sidecars, ingress).

## Files

| File | Purpose |
|---|---|
| `namespace.yaml` | Dedicated `mesa` namespace |
| `configmap.yaml` | Non-secret env vars (KAFKA_BROKERS, MONGO_URI, LLM_PROVIDER, ...) |
| `secret.example.yaml` | **Template only** — replace with a real secret out-of-band |
| `deployment.yaml` | API Deployment, 2 replicas, non-root, read-only rootfs, probes, resource limits |
| `service.yaml` | ClusterIP service in front of the pods |
| `hpa.yaml` | HorizontalPodAutoscaler 2 → 10 replicas on CPU/memory |
| `pdb.yaml` | PodDisruptionBudget keeping at least 1 pod available |
| `ingress.yaml` | Optional nginx-ingress example |
| `kustomization.yaml` | Bundles everything; pin image tag here |

## Apply

Edit `kustomization.yaml` to point at your real image registry and tag,
then:

```bash
kubectl apply -k DevOps/k8s
```

The `secret.example.yaml` line in `kustomization.yaml` is commented out
on purpose. Generate the real secret out-of-band — Sealed Secrets,
External Secrets Operator, or GCP Secret Manager + workload identity —
and apply it to the `mesa` namespace before the Deployment becomes
healthy. The Deployment uses `envFrom: secretRef: mesa-secrets`, so the
expected secret name is `mesa-secrets`.

## Switching to real backends

The defaults in `configmap.yaml` (`KAFKA_BROKERS=memory://`,
`MONGO_URI=memory://`, `LLM_PROVIDER=stub`) make the deployment self-
contained for a smoke test. To wire real infra:

1. Provision Kafka and MongoDB (Confluent Cloud / MSK / Strimzi for
   Kafka; MongoDB Atlas / self-hosted ReplicaSet for Mongo).
2. Update `configmap.yaml` with the broker list and connection URI.
3. If using `LLM_PROVIDER=google_adk`, ensure `LLM_API_KEY` is set in
   the secret and the image is built with the `[adk]` extra installed.
4. Re-apply: `kubectl apply -k DevOps/k8s`.

## Health and rollout

`/healthz` and `/version` are wired as probes. The rolling update sets
`maxSurge=1, maxUnavailable=0`, so a deploy never drops below the
configured replica count. The HPA will scale the deployment back down
after traffic settles.
