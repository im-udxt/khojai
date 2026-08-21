#!/usr/bin/env bash
# One command setup for macOS and Linux.
#
#   ./scripts/install.sh
#
# Checks what is missing, writes a starter .env if there is none, pulls the
# model, builds the containers and waits until the site answers. Safe to run
# again: nothing already set up is changed.
set -euo pipefail

ok()   { printf "\033[0;32m  ok\033[0m   %s\n" "$1"; }
warn() { printf "\033[0;33m warn\033[0m  %s\n" "$1"; }
die()  { printf "\033[0;31m fail\033[0m  %s\n" "$1"; exit 1; }
step() { printf "\n\033[1m%s\033[0m\n" "$1"; }

cd "$(dirname "$0")/.."
OS="$(uname -s)"

step "Checking what is installed"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  COMPOSE="docker compose"
  ok "docker is running"
elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
  COMPOSE="docker-compose"
  ok "docker-compose is available"
else
  echo
  echo "Docker is not running. Install one of these, then run this again:"
  case "$OS" in
    Darwin) echo "  brew install colima docker-compose && colima start"
            echo "  or install Docker Desktop for Mac" ;;
    Linux)  echo "  curl -fsSL https://get.docker.com | sh" ;;
    *)      echo "  install Docker for your system" ;;
  esac
  die "docker missing"
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo
  echo "Ollama is not installed. It runs the language model on this machine."
  case "$OS" in
    Darwin) echo "  brew install ollama && brew services start ollama" ;;
    Linux)  echo "  curl -fsSL https://ollama.com/install.sh | sh" ;;
  esac
  die "ollama missing"
fi
ok "ollama is installed"

if ! curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then
  warn "ollama is not answering, starting it"
  (ollama serve >/dev/null 2>&1 &)
  sleep 5
  curl -fsS http://localhost:11434/api/version >/dev/null 2>&1 || die "ollama did not start"
fi
ok "ollama is answering"

step "Configuration"
if [ ! -f .env ]; then
  cp .env.example .env
  PASS=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
  if [ "$OS" = "Darwin" ]; then
    sed -i "" "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=$PASS|" .env
  else
    sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=$PASS|" .env
  fi
  ok "wrote .env with a generated database password"
  warn "Telegram is off until you add TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID"
else
  ok ".env already exists, leaving it alone"
fi

set -a; . ./.env; set +a
[ -n "${NEO4J_PASSWORD:-}" ] || die "NEO4J_PASSWORD is empty in .env"

MODEL="${LLM_MODEL:-qwen2.5:3b-instruct}"
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
  ok "model $MODEL is present"
else
  step "Downloading the model, this takes a few minutes"
  ollama pull "$MODEL" || die "could not pull $MODEL"
fi

step "Building and starting"
$COMPOSE up -d --build

step "Waiting for the site"
PORT="${WEB_PORT:-3000}"
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT" >/dev/null 2>&1; then
    ok "site is answering"
    break
  fi
  sleep 5
  [ "$i" = "60" ] && die "site did not come up. check: $COMPOSE logs web"
done

echo
echo "Ready."
echo "  site    http://localhost:$PORT"
echo "  status  http://localhost:$PORT/status"
echo "  logs    $COMPOSE logs -f agents"
echo
echo "It starts collecting on its own. The first links appear within a few minutes."
