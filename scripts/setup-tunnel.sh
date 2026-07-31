#!/usr/bin/env bash
# Publish the site through a Cloudflare tunnel.
#
#   ./scripts/setup-tunnel.sh khojai.uditgarg.in
#
# Creates a tunnel dedicated to this project, points the hostname at it, and
# runs it as a user service that starts at login. Any other tunnel already on
# the machine is left alone.
#
# Run `cloudflared tunnel login` once first if ~/.cloudflared/cert.pem is
# missing. That step opens a browser and cannot be done over SSH.
set -euo pipefail

HOSTNAME="${1:-}"
NAME="${TUNNEL_NAME:-khojai}"
[ -n "$HOSTNAME" ] || { echo "usage: $0 <hostname>"; exit 1; }

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env file"; exit 1; }
set -a; . ./.env; set +a
PORT="${WEB_PORT:-3000}"
CFDIR="$HOME/.cloudflared"

command -v cloudflared >/dev/null || { echo "cloudflared is not installed. brew install cloudflared"; exit 1; }
[ -f "$CFDIR/cert.pem" ] || { echo "not logged in. run: cloudflared tunnel login"; exit 1; }

# Reuse the tunnel if it already exists.
ID=$(cloudflared tunnel list --output json 2>/dev/null \
     | python3 -c "import json,sys;print(next((t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'),''))" 2>/dev/null || true)
if [ -z "$ID" ]; then
  cloudflared tunnel create "$NAME" >/dev/null
  ID=$(cloudflared tunnel list --output json \
       | python3 -c "import json,sys;print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'))")
fi
echo "tunnel $NAME is $ID"

cat > "$CFDIR/$NAME.yml" <<EOF
tunnel: $ID
credentials-file: $CFDIR/$ID.json

# Only the website is published. The API is reached through the site, so its
# port stays closed. The databases and the model server stay on loopback.
ingress:
  - hostname: $HOSTNAME
    service: http://localhost:$PORT
    originRequest:
      connectTimeout: 30s
      noHappyEyeballs: true
  - service: http_status:404
EOF

# Pass the config and the tunnel id explicitly. Without them cloudflared picks
# up the default config.yml and writes the DNS record for the wrong tunnel.
cloudflared tunnel --config "$CFDIR/$NAME.yml" route dns --overwrite-dns "$ID" "$HOSTNAME"
cloudflared --config "$CFDIR/$NAME.yml" tunnel ingress validate

PLIST="$HOME/Library/LaunchAgents/com.$NAME.tunnel.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.$NAME.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v cloudflared)</string>
    <string>--config</string><string>$CFDIR/$NAME.yml</string>
    <string>--no-autoupdate</string>
    <string>tunnel</string><string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/$NAME-tunnel.log</string>
  <key>StandardErrorPath</key><string>/tmp/$NAME-tunnel.err</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "waiting for the tunnel to connect"
for i in $(seq 1 24); do
  sleep 5
  if cloudflared tunnel info "$ID" 2>/dev/null | grep -q CONNECTOR; then
    echo "connected"
    break
  fi
done

echo
echo "https://$HOSTNAME should now serve the site."
echo "logs: tail -f /tmp/$NAME-tunnel.err"
echo
echo "Set ALLOWED_ORIGINS=https://$HOSTNAME and TRUST_PROXY_HEADER=true in .env,"
echo "then restart the api container, or the browser will be refused by CORS."
