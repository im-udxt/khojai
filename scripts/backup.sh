#!/usr/bin/env bash
# Copy the graph and the archive out of the Docker volumes into a dated folder.
# Keeps the last 7 backups.
#
#   scripts/backup.sh                 # into ~/khojai-backups
#   scripts/backup.sh /some/other/dir
#
# Take one of these before anything that changes the graph in bulk. Folding
# duplicate names, re-typing entities and clearing data all rewrite records
# that cannot be worked out again from what is left.
set -euo pipefail

cd "$(dirname "$0")/.."

# On the Mac the docker command is not on PATH: this machine runs colima and
# only docker-compose was linked. The engine is the same either way, so the
# binary is looked for rather than assumed.
find_docker() {
  for candidate in \
    "${DOCKER_BIN:-}" \
    "$(command -v docker 2>/dev/null || true)" \
    /Applications/Docker.app/Contents/Resources/bin/docker \
    /opt/homebrew/bin/docker \
    /usr/local/bin/docker
  do
    [ -n "$candidate" ] && [ -x "$candidate" ] && echo "$candidate" && return 0
  done
  return 1
}

DOCKER=$(find_docker) || {
  echo "no docker command found. set DOCKER_BIN to its path and run again." >&2
  exit 1
}

DEST="${1:-$HOME/khojai-backups}"
STAMP=$(date +%Y%m%d-%H%M)
OUT="$DEST/$STAMP"
mkdir -p "$OUT"

echo "backing up to $OUT using $DOCKER"
"$DOCKER" run --rm -v khojai_neo4j-data:/from -v "$OUT":/to alpine \
  tar czf /to/neo4j.tar.gz -C /from .
"$DOCKER" run --rm -v khojai_archive-data:/from -v "$OUT":/to alpine \
  tar czf /to/archive.tar.gz -C /from .

ls -1dt "$DEST"/*/ 2>/dev/null | tail -n +8 | xargs -r rm -rf
echo "done. kept the newest 7 backups in $DEST"
du -sh "$OUT"
