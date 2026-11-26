# GCP deployment CI — setup (draft)

Route chosen for the draft: **build in CI → Artifact Registry → roll out to
the existing GCE VM** (`deploy/cloud/` compose + Caddy). It reuses the VM
guide already in the repo, stays under the $25/mo target, and needs no app
code changes beyond one compose line. A Cloud Run alternative is at the end.

## One-time GCP setup (you, in the GCP console / gcloud)

1. Project + APIs: `gcloud services enable artifactregistry.googleapis.com compute.googleapis.com iamcredentials.googleapis.com`
2. Artifact Registry repo: `gcloud artifacts repositories create distrirag --repository-format=docker --location=<REGION>`
3. VM (if not already up): e2-standard-2 (2 vCPU / 4 GB), Ubuntu 24.04, ports
   22/80/443, Docker installed, code at `/opt/distrirag` on `main`, env at
   `deploy/.env.cloud` per `deploy/cloud/README.md`.
4. Service account `distrirag-deploy@<PROJECT>.iam.gserviceaccount.com` with:
   Artifact Registry Reader + Writer, Compute OS Login / Instance Admin.
5. Workload Identity Federation: create a WIF pool + GitHub provider
   (attribute `repository == mgm152002/Cmpe273_DistriRag`), grant the SA
   `roles/iam.workloadIdentityUser`. No long-lived JSON keys anywhere.
6. GitHub repo secrets: `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_DOMAIN`.
   Repo variables (or edit the workflow env): project, region, zone, VM name.

## What the workflow does

`deploy-gcp.yml` runs on pushes to `main` touching app/deploy/workflow paths,
or manually. It builds the `runtime` image (same Dockerfile target CI uses,
`EXTRAS=minilm,s3,azure`), pushes it tagged with the commit SHA, smoke-imports
it, then SSHes to the VM, fast-forward pulls `main`, pulls the image and
restarts only the `app` service. It then polls `/readyz` on localhost and on
`https://<DOMAIN>/readyz`. Rollback is re-running the workflow on the previous
commit, or on the VM: `IMAGE_TAG=<previous-sha-tag> docker compose ... up -d`.

## The one repo change the GCP PR makes

- Add `.github/workflows/deploy-gcp.yml` (this draft, values filled in).
- One line in `deploy/docker-compose.yml`, app service:
  `image: ${IMAGE_TAG:-distrirag:latest}` — so compose pulls the CI image
  instead of building locally. Local `make up` behaviour is unchanged
  (no `IMAGE_TAG` set → builds as today).
- This README (shortened) under `deploy/gcp/README.md`.

## Cloud Run alternative (if you pick it instead)

Same build/push job, then `gcloud run deploy distrirag --image=<tag>
--region=<REGION> --allow-unauthenticated` with `--set-env-vars` for
`DATABASE_URL` (Cloud SQL with pgvector, private IP + VPC connector) and
`REDIS_URL` (Memorystore). Needs: a VPC connector, Cloud SQL instance, and
the app's `DATABASE_URL`/`REDIS_URL` handling verified against managed
services. Cost is higher (Memorystore basic ~$35/mo alone) and it is a bigger
change than the VM route, which is why the VM route is the draft default.
