#!/usr/bin/env bash
# Restart Ollama when the pipeline cannot use it.
#
# The first version of this asked Ollama to generate two tokens and restarted
# it after two failures in a row. It never once fired, for two reasons worth
# remembering:
#
#   1. The probe was easier than the work. A two token reply succeeds while a
#      real extraction with an eight thousand token context times out, so the
#      probe kept saying everything was fine.
#   2. The failure came and went. The log filled with "no answer, strike 1"
#      followed by "answering again" five minutes later, so it never reached
#      the second consecutive strike, while the pipeline failed 176 times in
#      a row.
#
# So it no longer guesses. The agents container already counts how many
# extractions failed one after another, which is the only measure that
# matters: whether the real work is getting done.
#
#   */5 * * * * /Users/udxt/bin/khojai-ollama-watchdog
set -uo pipefail

export PATH="$HOME/bin:/opt/homebrew/bin:$PATH"
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
export DOCKER_CONFIG="$HOME/.docker-clean"

LIMIT="${FAIL_LIMIT:-8}"
LOG="${HOME}/khojai-backups/ollama-watchdog.log"
mkdir -p "$(dirname "$LOG")"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

FAILS=$(docker exec khoj-redis redis-cli GET khoj:worker:fails 2>/dev/null | tr -d '\r')
[ -z "${FAILS:-}" ] && FAILS=0
case "$FAILS" in (*[!0-9]*) FAILS=0 ;; esac

if [ "$FAILS" -lt "$LIMIT" ]; then
  exit 0
fi

say "the pipeline has failed ${FAILS} extractions in a row, restarting ollama"
brew services restart ollama >> "$LOG" 2>&1
sleep 25

# Load the model before handing it back, so the first extraction after this
# is not the one that pays the reload and times out again.
MODEL=$(docker exec khoj-agents printenv LLM_MODEL 2>/dev/null | tr -d '\r')
[ -z "${MODEL:-}" ] && MODEL="qwen2.5:3b-instruct"
if curl -s --max-time 300 http://127.0.0.1:11434/api/generate \
     -d "{\"model\":\"${MODEL}\",\"prompt\":\"ok\",\"stream\":false,\"keep_alive\":\"30m\",\"options\":{\"num_predict\":1}}" \
     2>/dev/null | grep -q '"done"'; then
  say "model loaded and answering"
  docker exec khoj-redis redis-cli DEL khoj:worker:fails >/dev/null 2>&1
else
  say "still not answering after a restart, needs a person"
fi
