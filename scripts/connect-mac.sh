#!/usr/bin/env bash
# Find the home server whatever address it has today and open a shell.
#
#   ./scripts/connect-mac.sh              open a shell
#   ./scripts/connect-mac.sh "uptime"     run one command
#
# DHCP moves the machine, so a fixed address goes stale. This tries the
# Bonjour name first, then the last address that worked, then looks for the
# known hardware address on the local network.
set -uo pipefail

USER_NAME="${MAC_USER:-udxt}"
BONJOUR="${MAC_HOST:-Udits-Mac-mini.local}"
CACHE="$HOME/.khojai-mac-address"
MAC_ADDR="${MAC_HW:-2e-80-61-1e-f5-21}"

try() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      "$USER_NAME@$1" "${2:-true}" 2>/dev/null
}

for target in "$BONJOUR" "$(cat "$CACHE" 2>/dev/null)"; do
  [ -n "$target" ] || continue
  if try "$target" "true"; then
    echo "$target" > "$CACHE"
    exec ssh -o StrictHostKeyChecking=accept-new "$USER_NAME@$target" ${1:+"$1"}
  fi
done

echo "Bonjour and the cached address both failed. Looking for the machine." >&2
base=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
[ -n "$base" ] || base=$(ipconfig 2>/dev/null | tr -d '\r' | awk '/IPv4/{print $NF; exit}')
prefix=$(echo "$base" | cut -d. -f1-3)
[ -n "$prefix" ] || { echo "could not work out the local network" >&2; exit 1; }

for i in $(seq 2 254); do (ping -c 1 -W 1 "$prefix.$i" >/dev/null 2>&1 || \
                            ping -n 1 -w 200 "$prefix.$i" >/dev/null 2>&1 &) ; done
sleep 6
found=$(arp -a 2>/dev/null | tr -d '\r' | grep -i "$MAC_ADDR" | grep -oE "$prefix\.[0-9]+" | head -1)
[ -n "$found" ] || { echo "not found on $prefix.0/24" >&2; exit 1; }
echo "found at $found" >&2
echo "$found" > "$CACHE"
exec ssh -o StrictHostKeyChecking=accept-new "$USER_NAME@$found" ${1:+"$1"}
