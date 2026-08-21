#!/usr/bin/env bash
# Put a new Telegram bot token in place and restart the agents container.
#
#   scripts/set-telegram-token.sh 1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#
# Get the token from @BotFather in Telegram: send /newbot for a new one, or
# /token to reissue for a bot that already exists. It has to come from your
# own Telegram account, which is why this cannot be automated.
#
# The token is checked against Telegram before it is written, so a typo fails
# here rather than silently turning the bot off.
set -euo pipefail

cd "$(dirname "$0")/.."
TOKEN="${1:-}"

if [ -z "$TOKEN" ]; then
  echo "usage: scripts/set-telegram-token.sh <token>" >&2
  exit 1
fi

echo "checking the token with Telegram"
REPLY=$(curl -s --max-time 20 "https://api.telegram.org/bot${TOKEN}/getMe" || true)
if ! printf '%s' "$REPLY" | grep -q '"ok":true'; then
  echo "Telegram refused that token:" >&2
  printf '%s\n' "$REPLY" | head -c 300 >&2
  echo >&2
  exit 1
fi
NAME=$(printf '%s' "$REPLY" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
echo "token is good, the bot is @${NAME}"

if [ ! -f .env ]; then
  echo "no .env here" >&2
  exit 1
fi

cp .env ".env.backup-$(date +%Y%m%d-%H%M)"
if grep -q '^TELEGRAM_BOT_TOKEN=' .env; then
  # A token can contain characters that mean something to sed, so the file is
  # rewritten line by line instead of being patched in place.
  awk -v tok="$TOKEN" \
    '/^TELEGRAM_BOT_TOKEN=/ { print "TELEGRAM_BOT_TOKEN=" tok; next } { print }' \
    .env > .env.new && mv .env.new .env
else
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TOKEN" >> .env
fi
echo "written to .env, the old one is kept as .env.backup-*"

if grep -q '^TELEGRAM_ALLOWED_USER_ID=.\+' .env; then
  echo "the allowed user id is already set"
else
  echo "warning: TELEGRAM_ALLOWED_USER_ID is empty, so the bot will refuse everyone" >&2
fi

echo "restarting the agents container"
docker-compose up -d --force-recreate agents >/dev/null 2>&1
sleep 12
docker-compose logs --tail=40 agents 2>&1 | grep -i telegram | tail -3 || true
echo "done. send /start to @${NAME} to check."
