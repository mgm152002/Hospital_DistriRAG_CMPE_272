# Deploying DistriRAG on one small cloud VM

Target: one VM with 2 vCPU and 4 GB of RAM running the `lite` compose stack with the **hybrid** profile (MiniLM
embeddings on the VM, answers from an external model behind the egress policy), Caddy for HTTPS, and files in S3 or
Azure Blob. Measured memory use is far below 4 GB; the headroom is for MiniLM (about 235 MB) and the OS.

| Option | Size | Approximate monthly cost |
| --- | --- | --- |
| AWS Lightsail | 2 vCPU / 4 GB | about $24 |
| Azure B2s | 2 vCPU / 4 GB | about $30 (often covered by student credit) |
| Hetzner CX22 | 2 vCPU / 4 GB | about €5 |
| Object storage (S3 or Azure Blob) | a few hundred MB | under $1 |
| OpenRouter free model | rate-limited | $0 (add $10 credit for higher limits on demo day) |

Prices change; check the provider before buying. Free OpenRouter models may keep prompts, so the app allows them only
while `SYNTHETIC_DATA_ONLY=true`.

## Steps

1. **Create the VM** (Ubuntu 24.04), open ports 22, 80 and 443 only, and point a DNS name at its IP.
2. **Install Docker:** `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER` (log out and in).
3. **Get the code:** `git clone <repo> /opt/distrirag && cd /opt/distrirag && git checkout distrirag`.
4. **Configure:** `cp deploy/cloud/env.cloud.example deploy/.env.cloud`, then fill in `DOMAIN`, the provider key and
   the bucket credentials. Create the bucket first.
5. **Start:**
   ```bash
   EXTRAS=minilm,s3,azure DOMAIN=your.domain \
     docker compose -f deploy/docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml --profile lite up -d --build
   ```
   Caddy obtains a certificate automatically. Check `https://your.domain/readyz`.
6. **Seed the synthetic corpus:** `make seed API_URL=https://your.domain`.
7. **Backups:** add `0 2 * * * /opt/distrirag/deploy/cloud/backup.sh` to the crontab of the deploy user.
8. **Before inviting anyone:** set `AUTH_MODE=oidc` with your identity provider. Header sign-in is for demos only.

## Managed alternative (optional)

Use a managed Postgres with pgvector (Neon, Azure Database for PostgreSQL Flexible Server) and managed Redis (Upstash,
Azure Cache for Redis): set `DATABASE_URL` (with `sslmode=require`) and `REDIS_URL`, set `DEPLOYMENT_PROFILE=cloud`,
and run only the `app` service. Use a Redis plan with persistence; DistriRAG re-drives work from Postgres if Redis
loses data, but persistence avoids the 10-minute wait.
