# Architecture

Five containers, one host process, and a rule that the public site can only
read.

```
                    feeds, searches, listing pages
                                 |
   host: Ollama  <----  agents  ----> Redis  (queue, counters, watchlist)
   (model, not in         |             ^
    a container)          v             |
                        Neo4j  <------  api  <------  web  <-- Cloudflare tunnel
                       (graph)      (read only)      (Next.js)
```

## The five services

| Service | What it does | Ports |
| --- | --- | --- |
| `neo4j` | The graph | 7474, 7687 on loopback only |
| `redis` | Queue, counters, heartbeats, watchlist, robots cache | 6379 on loopback only |
| `agents` | Crawling, extraction, merging, health, metrics, Telegram | none |
| `api` | Read only HTTP for the site | 8080, loopback, 8090 on the server |
| `web` | Next.js site | 3000, loopback, 3100 on the server |

Both listen on loopback only. `API_BIND`, `WEB_BIND`, `API_PORT` and
`WEB_PORT` change that; the server uses 3100 and 8090 because 3000 and 8000
belong to something else on that machine.

Ollama runs on the host rather than in a container so it can use the machine's
GPU or unified memory. The agents container reaches it through
`host.docker.internal`.

## Why the API can only read

The site is on the public internet through a tunnel. The API has no endpoint
that writes, updates or deletes, every query uses parameters, and it holds no
credential that could change the graph.

That is also why the watchlist is managed from Telegram or the command line
rather than from a button on the site. A public page that could add a watch
would be a public page that can write.

## Threads inside the agents container

One process, six threads, so a failure in one does not stop the others.

| Thread | Interval | What it does |
| --- | --- | --- |
| `crawler` | 180s | One sweep of every source, measured start to start |
| `worker` | continuous | Takes documents off the queue, calls the model |
| `health` | 30s | Writes the health snapshot Redis serves to the status page |
| `metrics` | 45s | Writes machine load, disk and running totals |
| `merge` | 30m | Folds duplicate names, queues the rest for review |
| `markets` | 300s | Refreshes the small market strip |

The crawler's interval is a period, not a gap. It waits the remainder of the
interval after a sweep rather than the whole of it, so a slow sweep does not
stretch the cycle. If a sweep ends with documents still to fetch it goes
straight back round instead of idling.

Telegram runs on the main thread's event loop. This matters: a revoked token
once raised at startup and killed the process, taking the crawler and worker
with it. Telegram failures are now caught and the process idles instead, so
collection keeps running with the bot off.

## The pipeline

```
source  ->  seen before?  ->  worth reading?  ->  fetch body  ->  near duplicate?
                                                       |
                                                   archive
                                                       |
                                                    queue  ->  worker  ->  model
                                                                             |
                                                          quote and type checks
                                                                             |
                                                                          graph
```

Four cheap tests run before the model is asked for anything, because the model
is the slow part by a wide margin. A sweep looks at a couple of thousand items
and sends a hundred or so onward.

Two separate limits, because the costs are not alike. Looking at a document is
one Redis lookup, so `MAX_DOCS_PER_SWEEP` is wide enough to reach every source.
Fetching its body is a request to somebody else's server at one per second, so
`MAX_FETCH_PER_SWEEP` bounds that. Anything over the fetch budget is left
unmarked and picked up next sweep rather than lost.

Items are taken from every source in turn rather than off the top of a flat
list. Cutting a flat list reads the first few sources and never reaches the
rest.

The archive is written before anything is derived. It is the only copy of what
was actually seen, and the graph is derived data that could be rebuilt from it.

## The data model

Three node labels and three relationship types.

```
(:Entity {uid, key, name, type, aliases, mentions, first_seen, last_seen})
   -[:CLAIM {relation, quote, source_url, outlet, published, created}]->
(:Entity)

(:Entity)-[:CITED_IN]->(:Source {url, title, outlet, published, fetched})
```

`uid` is `sha1(key)` truncated to 16 characters, and **the type is not part of
it**. That was a real bug: when the type was included, improving the typing
rules split one name into two nodes and scattered its links between them.

`key` is the canonical form: lowercase, no honorifics, no legal suffixes, no
punctuation. It is what makes two spellings the same node.

`type` is one of Person, Company, Government, Court, Party, Place, Event,
Topic. `Topic` means nothing more specific could be worked out, and a later
more specific reading is allowed to replace it, so the graph corrects itself as
a name is seen again.

A `CLAIM` is unique on `(relation, source_url)` between two nodes, so the same
article reporting the same thing twice makes one edge, and two outlets
reporting it make two. That is what corroboration counts.

## Chains

A chain is a path of 2 or 3 `CLAIM` edges between two names, with
`MENTIONED_WITH` excluded and paths that revisit a name dropped. Each is
classified by the shape it makes: money then decision, party and money, a
decision and a case, and so on. Party shapes rank first.

Corroboration is counted per step, by asking how many distinct outlets carry
that exact relation between that exact pair. A chain's confidence is its
weakest step, because a chain cannot be stronger than that.

## Redis keys

| Key | Holds |
| --- | --- |
| `khoj:queue`, `khoj:queue:priority` | Documents waiting for the model |
| `khoj:seen` | Fingerprints of every URL seen, capped |
| `khoj:fingerprints` | simhash values for near duplicate detection |
| `khoj:stat:<day>:<name>` | Daily counters, expire after nine days |
| `khoj:total:<name>` | Running totals, never expire |
| `khoj:beat:worker`, `khoj:beat:crawler` | Heartbeats |
| `khoj:health`, `khoj:machine` | Snapshots the API serves |
| `khoj:watch`, `khoj:watch:hits`, `khoj:alerts:out` | Watchlist and alerts |
| `khoj:merges`, `khoj:merge:review`, `khoj:merge:rejected` | Merge log and queue |
| `khoj:source:health` | What each source last returned |
| `khoj:robots:<host>` | Cached robots files, one day |

## Near duplicate detection

simhash over word trigrams, compared against the last few thousand documents,
matching at a Hamming distance of 6 or less. This replaced sentence embeddings,
which meant carrying torch and a model file to answer a question that takes
microseconds without them.

## Fetching politely

Every outbound request goes through one function that:

- allows one request per second per host,
- reads feeds on different hosts at the same time, but never two on one host,
- sends an identifying user agent,
- refuses any address that resolves to a private, loopback, link local or
  reserved range, **including after each redirect hop**,
- asks each host for its robots file before walking its pages, and obeys it.

The address check matters because the crawler follows links that come from
feeds and search results, which are outside our control. Without it a crafted
link could make the crawler read the database admin page or a cloud metadata
address and store the response.

## The site

Next.js with no chart library, no graph library and no component library. The
map is a canvas with a spatial grid force simulation; the charts are SVG. This
keeps the page small and the build fast on a machine with 8 GB.
