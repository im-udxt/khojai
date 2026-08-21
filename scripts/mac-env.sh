# Source this before running docker commands on the Mac mini.
#
#   source scripts/mac-env.sh
#   docker-compose ps
#
# Why this file exists:
# Docker Desktop's CLI asks the macOS keychain for registry credentials on
# every pull. Over SSH there is no unlocked keychain, so every command fails
# with "keychain cannot be accessed". A headless server should not depend on a
# desktop app anyway, so this machine runs colima with the standalone
# docker-compose binary and a config directory that holds no credentials.

export PATH="/opt/homebrew/bin:$PATH"
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
export DOCKER_CONFIG="$HOME/.docker-clean"

if [ ! -f "$DOCKER_CONFIG/config.json" ]; then
  mkdir -p "$DOCKER_CONFIG"
  printf '{\n  "auths": {}\n}\n' > "$DOCKER_CONFIG/config.json"
fi

if ! colima status >/dev/null 2>&1; then
  echo "colima is not running. starting it."
  colima start --cpu 3 --memory 4 --disk 40
fi

# Only docker-compose was linked into PATH on this machine, so a plain
# "docker" command fails even though the engine is running. Point at the
# binary that is actually installed, without going back to Docker Desktop's
# credential helper.
for candidate in /Applications/Docker.app/Contents/Resources/bin/docker                  /opt/homebrew/bin/docker /usr/local/bin/docker; do
  if [ -x "$candidate" ]; then
    export DOCKER_BIN="$candidate"
    alias docker="$candidate"
    break
  fi
done
