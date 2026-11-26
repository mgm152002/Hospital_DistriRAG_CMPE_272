#!/usr/bin/env bash
# One-time GCP + GitHub setup for .github/workflows/deploy-gcp.yml. Idempotent: rerunning is safe.
# Needs: gcloud (logged in as a project owner) and gh (logged in to GitHub).
#   PROJECT=my-project REPO=owner/name deploy/gcp/setup.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REPO:?set REPO (owner/name)}"
REGION=${REGION:-us-central1}
AR_REPO=${AR_REPO:-distrirag}

g() { gcloud --project="$PROJECT" "$@"; }
quiet() { "$@" >/dev/null 2>&1; }

echo "== APIs"
g services enable compute.googleapis.com artifactregistry.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com oslogin.googleapis.com

echo "== Artifact Registry"
quiet g artifacts repositories describe "$AR_REPO" --location="$REGION" ||
  g artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION"

echo "== Service accounts"
DEPLOY_SA=distrirag-deploy@$PROJECT.iam.gserviceaccount.com
VM_SA=distrirag-vm@$PROJECT.iam.gserviceaccount.com
quiet g iam service-accounts describe "$DEPLOY_SA" || g iam service-accounts create distrirag-deploy --display-name="DistriRAG deploy (GitHub Actions)"
quiet g iam service-accounts describe "$VM_SA" || g iam service-accounts create distrirag-vm --display-name="DistriRAG VM"
sleep 5   # new service accounts take a moment to become bindable

bind() { quiet g projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$1" --role="$2" --condition=None; }
for role in roles/artifactregistry.writer roles/compute.instanceAdmin.v1 roles/compute.osAdminLogin; do
  bind "$DEPLOY_SA" "$role"
done
bind "$VM_SA" roles/artifactregistry.reader
bind "$VM_SA" roles/logging.logWriter
# The deploy SA attaches the VM SA to the instance it creates.
quiet g iam service-accounts add-iam-policy-binding "$VM_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser

echo "== Workload Identity Federation (GitHub OIDC, $REPO only)"
quiet g iam workload-identity-pools describe github --location=global ||
  g iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
quiet g iam workload-identity-pools providers describe github --location=global --workload-identity-pool=github ||
  g iam workload-identity-pools providers create-oidc github --location=global \
    --workload-identity-pool=github --issuer-uri=https://token.actions.githubusercontent.com \
    --attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository \
    --attribute-condition="assertion.repository=='$REPO'"
# A just-created pool or provider can take a minute to become readable.
retry() { for _ in $(seq 1 12); do "$@" 2>/dev/null && return 0; sleep 10; done; "$@"; }
POOL=$(retry g iam workload-identity-pools describe github --location=global --format='value(name)')
PROVIDER=$(retry g iam workload-identity-pools providers describe github --location=global \
  --workload-identity-pool=github --format='value(name)')
quiet g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/$POOL/attribute.repository/$REPO"

echo "== Network"
quiet g compute addresses describe distrirag-ip --region="$REGION" ||
  g compute addresses create distrirag-ip --region="$REGION"
quiet g compute firewall-rules describe distrirag-web ||
  g compute firewall-rules create distrirag-web --allow=tcp:80,tcp:443 --target-tags=distrirag
quiet g compute firewall-rules describe distrirag-ssh ||
  g compute firewall-rules create distrirag-ssh --allow=tcp:22 --target-tags=distrirag

echo "== GitHub repository settings"
gh secret set GCP_WIF_PROVIDER -R "$REPO" --body "$PROVIDER"
gh secret set GCP_DEPLOY_SA -R "$REPO" --body "$DEPLOY_SA"
gh variable set GCP_REGION -R "$REPO" --body "$REGION"
gh variable set GCP_AR_REPO -R "$REPO" --body "$AR_REPO"
gh variable set GCP_PROJECT -R "$REPO" --body "$PROJECT"   # last: this switches the workflow on

IP=$(g compute addresses describe distrirag-ip --region="$REGION" --format='value(address)')
echo "Done. The next push to main deploys to http://$IP"
