# LocaNoto enterprise on Kubernetes

Several stateless pods on one Postgres. The files are applied in order;
names, sizes and hosts are placeholders.

| file | what |
|---|---|
| `10-postgres.yaml` | Postgres 16 with pgvector (simple StatefulSet; use an operator such as CloudNativePG for failover and point-in-time recovery) |
| `20-config.yaml` | ConfigMap; the commands to create the Secrets |
| `30-server.yaml` | API and web interface, 2–10 pods (HPA), shared documents volume (ReadWriteMany) |
| `31-worker.yaml` | background jobs from the Postgres queue |
| `32-pages.yaml` | optional: the Streamlit pages during the change-over (sticky sessions) |
| `40-gateway.yaml` | LiteLLM proxy in front of the model servers/keys, message logging off |
| `50-network.yaml` | Ingress, NetworkPolicies for Postgres and the gateway |
| `60-migrate.yaml` | one-time move of an existing installation |

## Image

Built by GitHub Actions (`.github/workflows/abbild.yml`) on every push to
the `enterprise` branch, as `ghcr.io/mw-research/locanoto:enterprise-schlank`
(CPU, no reranker model in the image) and, started by hand,
`enterprise-voll`, each for **linux/amd64 and linux/arm64** (Apple
Silicon Macs, NVIDIA DGX Spark); a machine pulls its own architecture.
Each build also carries a fixed tag `enterprise-schlank-<commit>`; pin
that one in production. Both architectures are built on native runners
and checked there (text recognition, server start) before the shared
tag moves. `enterprise-voll` for arm64 only on request (CUDA wheels for
aarch64). Installations that pull `schlank` are not affected.

On a Mac or a DGX Spark without Kubernetes:

```bash
docker run -p 8700:8700 -e LOCANOTO_SCHLUESSEL=... -e DATABASE_URL=... \
  ghcr.io/mw-research/locanoto:enterprise-schlank \
  uvicorn server:app --host 0.0.0.0 --port 8700
```

## New installation

```bash
kubectl create secret generic locanoto-postgres --from-literal=password="$(openssl rand -base64 32)"
kubectl create secret generic locanoto \
  --from-literal=LOCANOTO_SCHLUESSEL="$(python -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" \
  --from-literal=DATABASE_URL="postgresql://locanoto:<password>@locanoto-postgres:5432/locanoto" \
  --from-literal=OPENAI_API_KEY="<virtual key of the gateway>"
kubectl create secret generic locanoto-gateway --from-literal=LITELLM_MASTER_KEY="sk-$(openssl rand -hex 24)"
kubectl apply -f 10-postgres.yaml -f 20-config.yaml -f 40-gateway.yaml
kubectl apply -f 30-server.yaml -f 31-worker.yaml -f 50-network.yaml
kubectl exec deploy/locanoto-server -- python database.py --check
kubectl exec deploy/locanoto-server -- python create_user.py   # first admin
```

Keep a copy of `LOCANOTO_SCHLUESSEL` outside the cluster. Without it the
encrypted chats, passages and file names cannot be read, also not from a
backup.

## Moving an existing installation

1. Measure the search before deciding the vector size: on the old
   installation `python compare_search.py run questions.txt --user <name> --out old.json`.
2. Stop the old pages (`kubectl scale deploy/locanoto --replicas=0`).
3. `kubectl apply -f 60-migrate.yaml` and follow `kubectl logs -f job/locanoto-migrate`
   (check, run, verify; the old volumes are mounted read-only).
4. Start server and workers; run the same questions against the new one
   (`--out new.json`) and `python compare_search.py diff old.json new.json`.

The way back: scale the old deployment up again -- its data was only read.

## Sign-in through the company directory

Register a confidential OIDC client with the redirect URI
`https://<host>/api/v1/auth/oidc/callback`, put `OIDC_ISSUER`,
`OIDC_CLIENT_ID`, `OIDC_REDIRECT_URI` and the group names into the
ConfigMap and `OIDC_CLIENT_SECRET` into the Secret `locanoto`. Roles and
workspace membership follow the directory groups at every sign-in.
