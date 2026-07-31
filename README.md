# KhojAI

Reads Indian news and official feeds all day. When an article states that two
names are connected, it stores that link along with the sentence that said it
and a link back to the article.

It does not draw conclusions. It records what published sources said, so you can
check each one yourself.

## What it does

1. Reads about 25 news and government feeds every few minutes.
2. Throws out anything already seen, anything off topic, and near duplicates.
3. Sends what is left to a local language model running on your own machine.
4. The model lists relationships and must quote the sentence that states each one.
5. If the quote is not in the article word for word, the claim is thrown away.
6. What survives goes into a graph you can search and browse.

## Screens

- Home: counts for the day, the newest links found, and a live activity list.
- Map: a picture of names and the links between them, filterable by type.
- Status: which services are up or down and how many articles are waiting.
- Name pages: everything stored about one name, each with its source.

## Telegram

A private bot answers questions. Only the user id set in `.env` can use it.

- `/investigate <question>` goes and reads new articles about the question, then
  answers with sources.
- `/ask <question>` answers from what is already stored.
- `/status` reports which services are running.

## Requirements

- Docker
- [Ollama](https://ollama.com) on the host machine, not in a container
- About 6 GB of free disk

## Setup

```bash
git clone git@github.com:im-udxt/khojai.git
cd khojai
cp .env.example .env      # fill in NEO4J_PASSWORD and the Telegram values
./scripts/setup-mac.sh    # or: docker compose up -d --build
```

Then open http://localhost:3000

## Configuration

Everything lives in `.env`. The values worth knowing:

| Name | What it does |
| --- | --- |
| `NEO4J_PASSWORD` | Database password. Required. |
| `LLM_MODEL` | Which Ollama model reads articles. Default `qwen2.5:3b-instruct`. `qwen2.5:7b-instruct` picks relations more accurately and is worth using if the machine has about 6 GB free. |
| `TELEGRAM_BOT_TOKEN` | From BotFather. Leave blank to run without Telegram. |
| `TELEGRAM_ALLOWED_USER_ID` | The only user allowed to use the bot. |
| `CRAWL_INTERVAL_SECONDS` | Gap between feed sweeps. Default 180. |
| `API_BIND` / `WEB_BIND` | Which address to listen on. Default is loopback only. |
| `ALLOWED_ORIGINS` | Set this to your public hostname before going public. |
| `RATE_LIMIT_PER_MIN` | Requests allowed per address per minute. Default 60. |

## Where the data lives

In Docker named volumes, not in this folder:

| Volume | Holds |
| --- | --- |
| `khojai_neo4j-data` | The graph |
| `khojai_archive-data` | A compressed copy of every article read |
| `khojai_redis-data` | The queue and counters |

This is deliberate. An earlier version kept data in a folder inside the repo and
lost all of it when that folder was cleared. Named volumes survive reboots,
rebuilds and moving the project folder.

Back them up with `./scripts/backup.sh`. Start over with `./scripts/reset-data.sh`.

## Putting it on the internet

The site sits behind a Cloudflare tunnel. The containers only listen on
loopback, so nothing is exposed on your network and no ports are forwarded on
the router.

```bash
cloudflared tunnel login          # once, opens a browser
./scripts/setup-tunnel.sh khojai.uditgarg.in
```

The script creates a tunnel for this project, points the hostname at it, and
runs it as a login service. Other tunnels on the machine are left alone. Only
the website is published; the API is reached through the site, so its port is
never exposed.

Then set these in `.env` and restart the api container:

```
ALLOWED_ORIGINS=https://khojai.uditgarg.in
TRUST_PROXY_HEADER=true
```

Read `SECURITY.md` before going public.

## Layout

```
docker-compose.yml   the six services
agents/              crawling, entity handling, model calls, Telegram
api/                 read only API for the site
web/                 the site
scripts/             setup, backup, reset
```

## Licence

MIT. See `LICENSE`.
