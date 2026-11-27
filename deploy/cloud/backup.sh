#!/bin/sh
# Nightly database backup to the blob store (cron: 0 2 * * * /opt/distrirag/deploy/cloud/backup.sh).
set -eu
cd "$(dirname "$0")/../.."
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f deploy/docker-compose.yml exec -T postgres pg_dump -U distrirag -Fc distrirag > "/tmp/distrirag-$STAMP.dump"
if [ -n "${S3_BUCKET:-}" ]; then
  docker run --rm -v /tmp:/tmp -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION amazon/aws-cli \
    s3 cp "/tmp/distrirag-$STAMP.dump" "s3://$S3_BUCKET/backups/distrirag-$STAMP.dump"
fi
find /tmp -name 'distrirag-*.dump' -mtime +7 -delete
