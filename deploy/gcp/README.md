# Deploying to GCP

`.github/workflows/deploy-gcp.yml` builds the `runtime` image, pushes it to
Artifact Registry tagged with the commit SHA, and rolls it out to one GCE VM
running the lite stack behind Caddy (`deploy/cloud/`). It runs automatically
after `ci` passes on a push to `main`, or manually from the Actions tab.
Every job is skipped until the `GCP_PROJECT` repository variable exists, so
the workflow stays green before setup.

## One-time GCP setup

```sh
PROJECT=<project-id> REGION=us-central1 ZONE=us-central1-a VM=distrirag-vm
REPO=mgm152002/Cmpe273_DistriRag

gcloud config set project $PROJECT
gcloud services enable artifactregistry.googleapis.com compute.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com
gcloud artifacts repositories create distrirag --repository-format=docker --location=$REGION

# Deploy service account used by GitHub Actions
gcloud iam service-accounts create distrirag-deploy
SA=distrirag-deploy@$PROJECT.iam.gserviceaccount.com
for role in roles/artifactregistry.writer roles/compute.instanceAdmin.v1 \
            roles/compute.osAdminLogin roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$role
done

# Workload Identity Federation: GitHub OIDC, restricted to this repository
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github --location=global \
  --workload-identity-pool=github --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository \
  --attribute-condition="assertion.repository=='$REPO'"
POOL=$(gcloud iam workload-identity-pools describe github --location=global --format='value(name)')
gcloud iam service-accounts add-iam-policy-binding $SA --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/$POOL/attribute.repository/$REPO"
gcloud iam workload-identity-pools providers describe github --location=global \
  --workload-identity-pool=github --format='value(name)'   # -> GCP_WIF_PROVIDER
```

## The VM

e2-standard-2 (2 vCPU / 4 GB), Ubuntu 24.04, ports 80/443 open, Docker with
the compose plugin installed. Its own service account needs
**Artifact Registry Reader** so it can pull images. Then follow
`deploy/cloud/README.md`: clone this repo to `/opt/distrirag` and create
`deploy/.env.cloud` (domain, provider key). That env file stays on the VM
and is never committed.

## GitHub settings (Settings → Secrets and variables → Actions)

| Kind     | Name               | Value                                        |
|----------|--------------------|----------------------------------------------|
| Secret   | `GCP_WIF_PROVIDER` | provider name printed above                  |
| Secret   | `GCP_DEPLOY_SA`    | `distrirag-deploy@<project>.iam.gserviceaccount.com` |
| Variable | `GCP_PROJECT`      | project id                                   |
| Variable | `GCP_REGION`       | e.g. `us-central1`                           |
| Variable | `GCP_ZONE`         | e.g. `us-central1-a`                         |
| Variable | `GCP_VM`           | VM name                                      |
| Variable | `GCP_DOMAIN`       | public hostname Caddy serves                 |
| Variable | `GCP_AR_REPO`      | optional; defaults to `distrirag`            |

The deploy job uses the `production` environment, so you can add required
reviewers there to gate each rollout.

## What a rollout does

1. Build the `runtime` image (`EXTRAS=minilm,s3,azure`), smoke-import it, push `…/app:<sha>`.
2. SSH to the VM, check out that exact commit in `/opt/distrirag`, pull the image,
   and restart `app` (and `caddy` if its config changed) with `IMAGE_TAG` set.
3. Wait for `/readyz` inside the container, then on `https://<domain>/readyz`.

`deploy/docker-compose.yml` uses `image: ${IMAGE_TAG:-distrirag:latest}`, so
local `make up` still builds as before.

**Rollback:** run the workflow manually from the previous commit, or on the VM:
`IMAGE_TAG=<region>-docker.pkg.dev/<project>/distrirag/app:<old-sha> docker compose -f deploy/docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml --profile lite up -d app`.
