#!/usr/bin/env bash
# Copy the graph and the archive out of the Docker volumes into a dated folder.
# Run it from cron or launchd. Keeps the last 7 backups.
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="${1:-$HOME/khojai-backups}"
STAMP=$(date +%Y%m%d-%H%M)
OUT="$DEST/$STAMP"
mkdir -p "$OUT"

echo "backing up to $OUT"
docker run --rm -v khojai_neo4j-data:/from -v "$OUT":/to alpine \
  tar czf /to/neo4j.tar.gz -C /from .
docker run --rm -v khojai_archive-data:/from -v "$OUT":/to alpine \
  tar czf /to/archive.tar.gz -C /from .

ls -1dt "$DEST"/*/ 2>/dev/null | tail -n +8 | xargs -r rm -rf
echo "done. kept the newest 7 backups in $DEST"
