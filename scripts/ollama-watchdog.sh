#!/usr/bin/env bash
# Restart Ollama if it has stopped answering.
#
# Ollama can wedge: the model stays loaded and the port stays open, but
# requests never return. Asking whether the port answers, or which models are
# loaded, both say everything is fine. Only asking it to generate something
# finds it. Once wedged it held 2.7 GB and the pipeline processed nothing for
# more than a day, because nothing was watching and nothing could restart it
# from inside a container.
#
# Run from cron every few minutes:
#   */5 * * * * /Users/udxt/bin/khojai-ollama-watchdog
set -uo pipefail

HOST="${OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL="${LLM_MODEL:-qwen2.5:3b-instruct}"
STATE="${HOME}/.khojai-ollama-watchdog"
LOG="${HOME}/khojai-backups/ollama-watchdog.log"
mkdir -p "$(dirname "$LOG")"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# A real generation, kept tiny. Sixty seconds is long enough that a busy
# machine is not mistaken for a broken one.
if curl -s --max-time 60 "${HOST}/api/generate" \
     -d "{\"model\":\"${MODEL}\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":2}}" \
     2>/dev/null | grep -q '"done"'; then
  if [ -f "$STATE" ]; then
    say "answering again"
    rm -f "$STATE"
  fi
  exit 0
fi

# One slow answer is not a fault. Two in a row is.
STRIKES=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$STRIKES" > "$STATE"
say "no answer, strike ${STRIKES}"

if [ "$STRIKES" -lt 2 ]; then
  exit 0
fi

say "restarting ollama"
if command -v brew >/dev/null 2>&1; then
  brew services restart ollama >> "$LOG" 2>&1
else
  say "brew not found, cannot restart"
  exit 1
fi
rm -f "$STATE"
sleep 20

if curl -s --max-time 60 "${HOST}/api/generate" \
     -d "{\"model\":\"${MODEL}\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":2}}" \
     2>/dev/null | grep -q '"done"'; then
  say "restart worked"
else
  say "still not answering after a restart, needs a person"
fi
