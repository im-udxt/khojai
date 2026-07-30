#!/usr/bin/env bash
# First run on the Mac home server.
#
#   git clone git@github.com:im-udxt/khojai.git
#   cd khojai
#   cp .env.example .env   and fill it in
#   ./scripts/setup-mac.sh
#
# Installs nothing without asking. Checks what is missing and tells you.
set -euo pipefail

green() { printf "\033[0;32m%s\033[0m\n" "$1"; }
red()   { printf "\033[0;31m%s\033[0m\n" "$1"; }
warn()  { printf "\033[0;33m%s\033[0m\n" "$1"; }

cd "$(dirname "$0")/.."

[ -f .env ] || { red "No .env file. Copy .env.example to .env and fill it in."; exit 1; }
set -a; . ./.env; set +a
[ -n "${NEO4J_PASSWORD:-}" ] || { red "NEO4J_PASSWORD is empty in .env"; exit 1; }
green "config loaded"

if ! command -v docker >/dev/null; then
  red "Docker is not installed."
  echo "Install Docker Desktop for Mac, or use colima:  brew install colima docker && colima start"
  exit 1
fi
docker info >/dev/null 2>&1 || { red "Docker is installed but not running. Start it and run this again."; exit 1; }
green "docker is running"

if ! command -v ollama >/dev/null; then
  red "Ollama is not installed. Install it with:  brew install ollama"
  exit 1
fi
if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "Ollama is not answering. Starting it in the background."
  (ollama serve >/dev/null 2>&1 &)
  sleep 4
fi
curl -fsS http://localhost:11434/api/tags >/dev/null || { red "Ollama did not start."; exit 1; }
green "ollama is running"

MODEL="${LLM_MODEL:-qwen2.5:3b-instruct}"
if ! ollama list | awk '{print $1}' | grep -q "^${MODEL}"; then
  echo "Pulling ${MODEL}. This downloads a few GB and takes a while."
  ollama pull "${MODEL}"
fi
green "model ready: ${MODEL}"

# Containers reach the host through host.docker.internal. Docker Desktop
# provides it. Colima needs the host gateway, which compose already sets.
echo "Building and starting."
docker compose up -d --build

printf "waiting for the database"
for i in $(seq 1 60); do
  state=$(docker inspect --format='{{.State.Health.Status}}' khoj-neo4j 2>/dev/null || echo starting)
  [ "$state" = "healthy" ] && { echo; green "database is healthy"; break; }
  printf "."; sleep 5
  [ "$i" = "60" ] && { echo; red "database did not come up. Check: docker logs khoj-neo4j"; exit 1; }
done

echo
green "KhojAI is running."
echo "  site       http://localhost:${WEB_PORT:-3000}"
echo "  api        http://localhost:${API_PORT:-8080}/api/status"
echo "  logs       docker compose logs -f agents"
echo
echo "To keep it running after a reboot, Docker restarts these containers"
echo "automatically as long as Docker itself starts at login."
