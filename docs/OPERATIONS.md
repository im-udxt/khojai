# Operations

The production host is a Mac mini with 8 GB of memory, reachable as `khojmac`.
Everything below assumes you are on it.

## Getting a shell that can run docker

Docker Desktop's CLI asks the macOS keychain for registry credentials on every
command, and there is no unlocked keychain over SSH. This machine runs colima
instead, with a config directory holding no credentials.

```bash
ssh khojmac
cd ~/khojai
source scripts/mac-env.sh
```

That sets `PATH`, `DOCKER_HOST` to the colima socket, `DOCKER_CONFIG` to a
clean directory, and `DOCKER_BIN` to a working `docker` binary. Use
`docker-compose`, not `docker compose`.

There is no `docker` on the PATH by default. Docker Desktop's binary works fine
against the colima socket, so `mac-env.sh` points at it:

```
/Applications/Docker.app/Contents/Resources/bin/docker
```

## Deploying a change

```bash
cd ~/khojai
git pull --ff-only origin main
docker-compose build agents api web
docker-compose up -d agents api web
docker-compose ps
```

Only rebuild what changed. The web build is the slow one.

## Backups

Nightly at 03:17 from cron, into `~/khojai-backups`, keeping the last seven at
about 18 MB each. The job is `~/bin/khojai-backup`.

```bash
./scripts/backup.sh              # by hand, right now
tail ~/khojai-backups/backup.log
```

**Take one before any bulk change to the graph.** Folding duplicate names,
re-typing entities and clearing data all rewrite records that cannot be worked
out again from what is left. This is not theoretical: a bulk merge ran once
with no backup in existence and its mistakes could not be undone.

## Restoring

```bash
docker-compose down
docker run --rm -v khojai_neo4j-data:/to -v ~/khojai-backups/<stamp>:/from \
  alpine sh -c "rm -rf /to/* && tar xzf /from/neo4j.tar.gz -C /to"
docker-compose up -d
```

The archive volume restores the same way with `archive-data` and
`archive.tar.gz`.

## Bulk graph jobs

All of these are run by hand, none are on a timer.

```bash
docker-compose exec -T agents python cleanup.py           # report only
docker-compose exec -T agents python cleanup.py --apply   # remove junk names
docker-compose exec -T agents python retype.py            # re-derive entity types
docker-compose exec -T agents python watch_cli.py list
```

`cleanup.py` reports before it changes anything, and that is not a formality.
The first version of the rules behind it would have deleted 126 names including
`Meta Platforms, Inc` and `Indian Institute of Management, Indore`. The dry run
is what caught it.

## When something breaks

### The status page says a service is down

It reports on progress, not reachability, so believe it. Check which:

```bash
curl -s localhost:8090/api/status | python3 -m json.tool
docker-compose logs --tail=50 agents
```

### Nothing is being read and the queue is growing

Usually Ollama. Check the host, not the container:

```bash
curl -s localhost:11434/api/tags | python3 -m json.tool
brew services list | grep ollama
```

### The whole pipeline is dead

Check whether the process is up at all. A revoked Telegram token used to kill
it at startup; that is handled now, but any exception on the main thread would
do the same. `docker-compose logs agents | head -40` shows the startup path.

### A source stopped producing

The Sources tab on the status page lists what each source last returned.
Nothing to do for most of them: government sites move paths and let
certificates expire. See `docs/SOURCES.md`.

### The Mac cannot be reached

It does not answer ping. macOS blocks ICMP by default, so a failed ping means
nothing. Test with `ssh khojmac`.

`khojmac` resolves over Bonjour, which follows the machine when DHCP changes
its address. Bonjour sometimes fails to resolve for a few seconds; retry, or
use `khojmac-ip`, which is the fixed address.

## The tunnel

The site is published by a dedicated tunnel, `khojai`, running as a user
LaunchAgent. Only the website is published. The API is reached through the
site, so its port is never exposed.

```bash
launchctl list | grep khojai
cloudflared tunnel --config ~/.cloudflared/khojai.yml info khojai
```

There is a separate `n8n-tunnel` on this machine that must be left alone. When
routing DNS, always pass `--config` and the tunnel **id**, not just the name.
Without that, `cloudflared` reads the default config and writes the record for
the wrong tunnel.

## Other things on this machine

Do not disturb them.

| Port | What |
| --- | --- |
| 3000, 8000 | `adbot`, a separate project with its own LaunchAgents |
| 8888 | Jupyter |
| 3100, 8090 | KhojAI web and API |

The crontab has an `adbot-watchdog` line running every minute. Preserve it when
editing the crontab.

## Memory

The machine has 8 GB. colima takes 4, leaving the rest for macOS and Ollama.
Neo4j runs with a 512 MB heap and a 256 MB page cache, and Redis is capped at
256 MB. There is not room for a 7B model alongside colima; see
`docs/DECISIONS.md` for what was measured.
