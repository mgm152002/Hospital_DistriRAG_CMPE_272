# Deploying to GCP

`.github/workflows/deploy-gcp.yml` is continuous deployment: every push to `main`
(except docs-only and test-only changes), or a manual run from the Actions tab:

1. builds the `runtime` image (`EXTRAS=minilm,s3,azure`), checks that it imports,
   and pushes it to Artifact Registry as `…/distrirag/app:<commit-sha>`;
2. creates the VM on the first run (Ubuntu 24.04, `e2-medium`, static IP, Docker
   installed by `vm-startup.sh`);
3. SSHes in (OS Login), checks out that commit in `/opt/distrirag`, and runs
   `rollout.sh`, which pulls the image, restarts the lite stack, and waits for `/readyz`;
4. checks `/readyz` on the public URL and writes it to the run summary.

GitHub gets into GCP through Workload Identity Federation, limited to this
repository. No service-account key exists anywhere.

## One-time setup

You need `gcloud` logged in as a project owner and `gh` logged in to GitHub:

```sh
gcloud auth login
PROJECT=cmpe-272-515921 REPO=mgm152002/Cmpe273_DistriRag bash deploy/gcp/setup.sh
```

The script is safe to rerun. It enables the APIs and creates the Artifact
Registry repo, two service accounts (`distrirag-deploy` for GitHub,
`distrirag-vm` for the VM, which only reads images), the WIF pool and provider,
a static IP, and firewall rules for 22/80/443. It then sets the GitHub secrets
`GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA` and the variables `GCP_REGION`,
`GCP_AR_REPO` and `GCP_PROJECT`. Setting `GCP_PROJECT` is what switches the
workflow on.

## Optional settings

| Kind     | Name          | Effect                                                                 |
|----------|---------------|------------------------------------------------------------------------|
| Secret   | `APP_ENV`     | Full contents of the app's `.env` (provider keys and so on). Unset: `.env.example` is used. |
| Variable | `GCP_DOMAIN`  | A hostname pointing at the static IP. Set: Caddy serves HTTPS. Unset: plain HTTP on the IP. |
| Variable | `GCP_ZONE`, `GCP_VM`, `GCP_MACHINE` | Defaults: `us-central1-a`, `distrirag-vm`, `e2-medium`. |

The deploy job uses the `production` environment. Add required reviewers there
if you want a manual approval before each rollout.

## Rollback

Re-run the workflow for an earlier commit (Actions → deploy-gcp → pick the run → Re-run),
or on the VM:

```sh
cd /opt/distrirag && sudo IMAGE_TAG=us-central1-docker.pkg.dev/<project>/distrirag/app:<old-sha> bash deploy/gcp/rollout.sh < /dev/null
```
