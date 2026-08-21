# KhojAI

Reads Indian news, court and government sources all day. When an article states
that two names are connected, it stores that link along with the sentence that
said it and a link back to the article.

It does not draw conclusions. It records what published sources said, so you can
check each one yourself.

Live at [khojai.uditgarg.in](https://khojai.uditgarg.in).

## The idea

A single fact is not worth much. "This person works at that department" is a
line in one article. The value is in what two separately reported facts make
when they meet at a shared name: a company that received a contract from a
department that a minister leads.

Those chains are not stored anywhere. They are found by walking the graph, and
every step of every chain carries the sentence and the link it came from.

Nothing here asserts that one step caused another. A chain is a route through
the records.

## What it does

1. Reads 65 sources: 23 feeds, 15 outlets reached through search, 17 topic
   searches, and 10 listing pages walked like a browser.
2. Throws out anything already seen, anything off topic, and near duplicates.
3. Sends what is left to a language model running on your own machine.
4. The model lists relationships and must quote the sentence stating each one.
5. If the quote is not in the article word for word, the claim is thrown away.
6. What survives goes into a graph you can search, browse and walk.

## Screens

| Page | What is on it |
| --- | --- |
| Home | Counts for the day, the newest links found, a live activity list |
| Cases | Names that turned up in several recorded links, grouped for reading |
| Connections | Chains of separately recorded facts, with proof and confidence |
| Parties | Political parties, the money and decisions around them, party chains |
| Map | A canvas drawing of names and links, with filters |
| Insights | Charts of what is stored and a plain summary |
| Watchlist | Names being followed and what has come in about them |
| Status | Services, machine load, running totals, source health, merged names |

Every chain on Connections and Parties opens four tabs:

- **Reading** says what the chain is in a sentence, and what it is not.
- **Proof** shows every step's quote and source link.
- **Confidence** counts how many independent outlets back each step, and says
  plainly that a chain is only as strong as its weakest step.
- **Time** puts the steps in publication order, and warns that publication
  order is not the order events happened.

## Telegram

A private bot. Only the user id set in `.env` can use it.

| Command | What it does |
| --- | --- |
| `/investigate <question>` | Reads new articles about the question, answers with sources |
| `/ask <question>` | Answers from what is already stored |
| `/watch <name>` | Sends a message when a new link touches that name |
| `/unwatch <name>`, `/watching` | Stop following, and list what is followed |
| `/merges` | Duplicate names waiting for a decision, and how to decide them |
| `/stats` | Running totals and machine load |
| `/status` | Which services are working |

The bot is optional. Everything else runs without it, and the watchlist can be
managed from the command line instead:

```bash
docker-compose exec -T agents python watch_cli.py add "Adani Ports"
docker-compose exec -T agents python watch_cli.py list
```

## Requirements

- Docker, or colima on macOS
- [Ollama](https://ollama.com) on the host machine, not in a container
- About 6 GB of free disk and 4 GB of free memory

Runs on macOS, Linux and Windows. Nothing leaves the machine: the model runs
locally and the graph stays in local volumes.

## Setup

One command. It checks what is missing, generates a database password, pulls
the model and starts everything.

```bash
git clone https://github.com/im-udxt/khojai.git
cd khojai
./scripts/install.sh          # Windows: powershell -File scripts\install.ps1
```

Then open http://localhost:3000.

Telegram stays off until you add a bot token:

```bash
./scripts/set-telegram-token.sh <token from BotFather>
```

That checks the token with Telegram before writing it, so a typo fails there
rather than quietly disabling the bot.

## Configuration

Everything lives in `.env`.

| Name | What it does |
| --- | --- |
| `NEO4J_PASSWORD` | Database password. Required. |
| `LLM_MODEL` | Which Ollama model reads articles. Default `qwen2.5:3b-instruct`. See `docs/DECISIONS.md` before changing it. |
| `TELEGRAM_BOT_TOKEN` | From BotFather. Blank runs without Telegram. |
| `TELEGRAM_ALLOWED_USER_ID` | The only user allowed to use the bot. |
| `CRAWL_INTERVAL_SECONDS` | Gap between sweeps. Default 180. |
| `SITES_PER_SWEEP` | Listing pages walked per sweep. Default 5. |
| `API_BIND` / `WEB_BIND` | Which address to listen on. Loopback by default. |
| `ALLOWED_ORIGINS` | Set to your public hostname before going public. |
| `RATE_LIMIT_PER_MIN` | Requests per address per minute. Default 60. |

## Where the data lives

In Docker named volumes, not in this folder.

| Volume | Holds |
| --- | --- |
| `khojai_neo4j-data` | The graph |
| `khojai_archive-data` | A compressed copy of every article read |
| `khojai_redis-data` | The queue, counters and the watchlist |

This is deliberate. An earlier version kept data in a folder inside the repo and
lost all of it when that folder was cleared.

Back them up with `./scripts/backup.sh`, which keeps the last seven. **Run it
before any bulk change to the graph.** Merging duplicate names and re-typing
entities both rewrite records that cannot be worked out again from what is
left.

## How a claim is checked

1. The crawler reads sources and throws out anything seen before, off topic, or
   near identical to something already read.
2. The article body is fetched and archived before anything is derived from it.
3. The model is given the article and a schema it must fill. The schema forces
   a quote for every claim, so it cannot skip that field.
4. The quote must appear in the body word for word, must not be the headline,
   and must mention the subject or the object.
5. The relation must be one that can hold between those two kinds of name. A
   court does not work at a person. Implausible relations are downgraded to
   "mentioned with" rather than dropped, so the co-appearance survives.
6. A pair of names gets one relation per article. A model offering three or
   more for the same pair is guessing, so the pair drops to "mentioned with".
7. Names are canonicalised, and phrases that are descriptions rather than names
   are rejected.

This is why the counts are far lower than the number of articles read. Most
articles state nothing that survives step four.

## Documentation

| File | What is in it |
| --- | --- |
| `docs/ARCHITECTURE.md` | How the pieces fit, the data model, what runs where |
| `docs/OPERATIONS.md` | Deploying, backups, restores, and what to do when something breaks |
| `docs/SOURCES.md` | Every source, which work, which do not, and why |
| `docs/DECISIONS.md` | Things tried and rejected, with the measurements |
| `SECURITY.md` | What is exposed, how the API is protected, checklist before going public |

## Tests

No framework, no dependencies. Each file runs on its own and exits non zero on
failure.

```bash
python tests/test_merge_rules.py
python tests/test_entity_types.py
python tests/test_crawl.py
```

The cases in them are not invented. Every one is a decision the running system
actually made, including the wrong ones, kept so the rules that caused them
cannot come back.

## Layout

```
docker-compose.yml   the five services
agents/              crawling, entity handling, model calls, Telegram
  config.py          settings, the polite fetcher, address checks
  sources.py         feeds, topic searches, listing pages
  crawl.py           walking pages that have no feed, robots handling
  pipeline.py        crawl, filter, dedup, queue, worker
  entities.py        name canonicalisation and typing
  extract.py         the schema the model fills, and quote checking
  merge.py           folding duplicate names
  watch.py           the watchlist and alerts
  metrics.py         machine load and running totals
  health.py          heartbeats and health rules
  research.py        questions and investigations
api/                 read only API for the site
web/                 the site
scripts/             install, tunnel, backup, reset, token
tests/               rules that came out of real mistakes
docs/                architecture, operations, sources, decisions
```

## Health

The status page reports on progress, not reachability. The crawler and the
article reader each write a heartbeat. If the reader stops while the queue
grows, the page says so. An earlier version asked whether Ollama was listening
and called that healthy while nothing was being read at all.

## What it is not good at

Worth knowing before you trust anything on it.

- **The relation is the weakest part.** A small model picks which relationship
  holds between two names, and it gets that wrong often enough that the quote,
  not the label, is the thing to read. Type rules catch the nonsense. They do
  not catch a plausible relation pointing the wrong way.
- **Court judgments are mostly PDF** and are skipped, which is the largest gap
  in what it reads.
- **Several government sites cannot be read at all.** Some need a browser to
  render, some have broken certificates. `docs/SOURCES.md` lists which and why.
- **Corroboration is rare.** Most links have one outlet behind them, and the
  site says so on every chain.

## Licence

MIT. See `LICENSE`.
