#!/usr/bin/env bash
# Wipe everything the system has collected and start from empty.
# The code is untouched. Only the volumes are removed.
set -euo pipefail

cd "$(dirname "$0")/.."
read -r -p "This deletes the graph, the queue and the archive. Type yes to confirm: " reply
[ "$reply" = "yes" ] || { echo "cancelled"; exit 1; }

docker compose down -v
docker compose up -d --build
echo "reset done. the system is collecting from scratch."
