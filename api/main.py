"""Read only API for the public site.

This service is reachable from the internet through the tunnel, so it:
  - never writes to the graph
  - uses parameters in every query, so input cannot change a query
  - rate limits by client address
  - sends strict response headers
  - returns plain error messages, never a stack trace
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j import GraphDatabase

import connections

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("khoj.api")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))
ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
# Only believe the Cloudflare client header when we are actually behind the
# tunnel. Otherwise anyone could send that header and get a fresh rate limit
# bucket on every request.
TRUST_PROXY = os.environ.get("TRUST_PROXY_HEADER", "false").lower() == "true"

app = FastAPI(title="KhojAI", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["content-type"],
)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
rds = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)

SAFE_TEXT = re.compile(r"^[\w\s.,'&()/-]{1,120}$", re.UNICODE)


@app.middleware("http")
async def hardening(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    if TRUST_PROXY:
        client = request.headers.get("cf-connecting-ip") or client
    bucket = f"khoj:rl:{client}:{int(time.time() // 60)}"
    try:
        used = rds.incr(bucket)
        if used == 1:
            rds.expire(bucket, 90)
        if used > RATE_LIMIT:
            return JSONResponse({"error": "too many requests"}, status_code=429)
    except Exception:
        pass

    try:
        response = await call_next(request)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("unhandled error on %s: %s", request.url.path, exc)
        return JSONResponse({"error": "internal error"}, status_code=500)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Cache-Control"] = "public, max-age=20"
    return response


async def cypher(query, **params):
    def run():
        with driver.session() as session:
            return [dict(r) for r in session.run(query, **params)]
    return await asyncio.to_thread(run)


def clean_text(value, field):
    value = (value or "").strip()
    if not value or not SAFE_TEXT.match(value):
        raise HTTPException(400, f"invalid {field}")
    return value


@app.get("/api/health")
async def api_health():
    return {"api": "up"}


@app.get("/api/status")
async def status():
    """What the status page shows."""
    snapshot, stale = None, True
    try:
        raw = rds.get("khoj:health")
        if raw:
            snapshot = json.loads(raw)
            stale = (time.time() - snapshot.get("epoch", 0)) > 180
    except Exception:
        pass

    services = dict(snapshot.get("services", {})) if snapshot else {}
    services["api"] = {"state": "up", "note": "read only"}
    services["agents"] = {"state": "down" if (not snapshot or stale) else "up",
                          "note": "no recent heartbeat" if (not snapshot or stale) else "running"}
    if stale and snapshot:
        # The snapshot is old, so nothing inside it can be trusted as current.
        for name, info in services.items():
            if name not in ("api",):
                info["state"] = "unknown"
                info["note"] = "no recent report from the agents container"
    down = [k for k, v in services.items() if v.get("state") != "up"]
    return {
        "checked": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "queue_depth": (snapshot or {}).get("queue_depth", 0),
        "processed_today": (snapshot or {}).get("processed_today", 0),
        "healthy": not down,
        "down": down,
    }


@app.get("/api/stats")
async def stats():
    day = datetime.now(timezone.utc).strftime("%Y%m%d")

    def counter(name):
        try:
            return int(rds.get(f"khoj:stat:{day}:{name}") or 0)
        except Exception:
            return 0

    totals = await cypher(
        "MATCH (e:Entity) WITH count(e) AS entities "
        "MATCH ()-[r:CLAIM]->() RETURN entities, count(r) AS claims")
    row = totals[0] if totals else {"entities": 0, "claims": 0}

    def lifetime(name):
        try:
            return int(rds.get(f"khoj:total:{name}") or 0)
        except Exception:
            return 0

    return {
        "today": {
            "seen": counter("seen"),
            "queued": counter("queued"),
            "processed": counter("processed"),
            "claims": counter("claims"),
            "duplicates": counter("duplicate"),
        },
        "total": {"entities": row["entities"], "claims": row["claims"]},
        # Counting started when running totals were added, not when the
        # project did, so the date is carried with the numbers.
        "ever": {
            "seen": lifetime("seen"),
            "processed": lifetime("processed"),
            "claims": lifetime("claims"),
            "duplicates": lifetime("duplicate"),
            "merged": lifetime("merged"),
            "since": (rds.get("khoj:total:since") or "") if rds else "",
        },
    }


@app.get("/api/activity")
async def activity(limit: int = Query(40, ge=1, le=100)):
    try:
        rows = rds.lrange("khoj:activity", 0, limit - 1)
        return {"activity": [json.loads(r) for r in rows]}
    except Exception:
        return {"activity": []}


@app.get("/api/markets")
async def markets():
    try:
        raw = rds.get("khoj:markets")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"quotes": [], "note": "market data not available"}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=2, max_length=120),
                 limit: int = Query(15, ge=1, le=40)):
    q = clean_text(q, "query")
    terms = " ".join(f"{w}~" for w in re.findall(r"\w+", q.lower()) if len(w) > 2)
    if terms:
        try:
            rows = await cypher(
                "CALL db.index.fulltext.queryNodes('entity_search', $terms) "
                "YIELD node, score "
                "RETURN node.uid AS uid, node.name AS name, node.type AS type, "
                "coalesce(node.mentions,0) AS mentions "
                "ORDER BY score DESC, mentions DESC LIMIT $limit",
                terms=terms, limit=limit)
            if rows:
                return {"results": rows}
        except Exception as exc:
            log.warning("fulltext unavailable: %s", str(exc)[:100])
    rows = await cypher(
        "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS $q "
        "RETURN e.uid AS uid, e.name AS name, e.type AS type, "
        "coalesce(e.mentions,0) AS mentions ORDER BY mentions DESC LIMIT $limit",
        q=q.lower(), limit=limit)
    return {"results": rows}


@app.get("/api/entity/{uid}")
async def entity(uid: str):
    if not re.fullmatch(r"[a-f0-9]{6,32}", uid or ""):
        raise HTTPException(400, "invalid id")
    base = await cypher(
        "MATCH (e:Entity {uid:$uid}) RETURN e.uid AS uid, e.name AS name, "
        "e.type AS type, coalesce(e.mentions,0) AS mentions, "
        "toString(e.first_seen) AS first_seen, toString(e.last_seen) AS last_seen",
        uid=uid)
    if not base:
        raise HTTPException(404, "not found")
    claims = await cypher(
        "MATCH (a:Entity {uid:$uid})-[r:CLAIM]->(b:Entity) "
        "RETURN a.name AS subject, r.relation AS relation, b.name AS object, "
        "b.uid AS object_uid, r.quote AS quote, r.source_url AS url, "
        "r.outlet AS outlet, toString(r.created) AS created "
        "UNION "
        "MATCH (a:Entity)-[r:CLAIM]->(b:Entity {uid:$uid}) "
        "RETURN a.name AS subject, r.relation AS relation, b.name AS object, "
        "a.uid AS object_uid, r.quote AS quote, r.source_url AS url, "
        "r.outlet AS outlet, toString(r.created) AS created",
        uid=uid)
    return {**base[0], "claims": claims[:80]}


@app.get("/api/graph")
async def graph(entity: str | None = None,
                limit: int = Query(120, ge=10, le=300),
                type: str | None = None):
    params = {"limit": limit}
    where = ["1=1"]
    if entity:
        params["name"] = clean_text(entity, "entity").lower()
        where.append("(toLower(a.name) CONTAINS $name OR toLower(b.name) CONTAINS $name)")
    if type:
        if type not in {"Person", "Party", "Company", "Government", "Court", "Place", "Topic", "Event"}:
            raise HTTPException(400, "invalid type")
        params["type"] = type
        where.append("(a.type = $type AND b.type = $type)")

    rows = await cypher(
        f"MATCH (a:Entity)-[r:CLAIM]->(b:Entity) WHERE {' AND '.join(where)} "
        "RETURN a.uid AS su, a.name AS sn, a.type AS st, "
        "b.uid AS ou, b.name AS on_, b.type AS ot, r.relation AS rel "
        "LIMIT $limit", **params)

    nodes, edges = {}, []
    for r in rows:
        nodes.setdefault(r["su"], {"id": r["su"], "label": r["sn"], "type": r["st"]})
        nodes.setdefault(r["ou"], {"id": r["ou"], "label": r["on_"], "type": r["ot"]})
        edges.append({"source": r["su"], "target": r["ou"], "relation": r["rel"]})
    return {"nodes": list(nodes.values()), "edges": edges}


SIMPLE_PATHS = """
MATCH path = (a:Entity)-[rels:CLAIM*2..3]-(b:Entity)
WHERE a.uid < b.uid
  AND ALL(r IN rels WHERE r.relation <> 'MENTIONED_WITH')
RETURN [n IN nodes(path) | n.name] AS names,
       [n IN nodes(path) | n.uid] AS uids,
       [n IN nodes(path) | n.type] AS types,
       [r IN rels | r.relation] AS relations,
       [r IN rels | r.quote] AS quotes,
       [r IN rels | r.source_url] AS urls,
       [r IN rels | r.outlet] AS outlets,
       [r IN rels | toString(r.created)] AS dates
LIMIT $limit
"""

ENTITY_PATHS = """
MATCH path = (a:Entity {uid:$uid})-[rels:CLAIM*1..3]-(b:Entity)
WHERE ALL(r IN rels WHERE r.relation <> 'MENTIONED_WITH')
RETURN [n IN nodes(path) | n.name] AS names,
       [n IN nodes(path) | n.uid] AS uids,
       [n IN nodes(path) | n.type] AS types,
       [r IN rels | r.relation] AS relations,
       [r IN rels | r.quote] AS quotes,
       [r IN rels | r.source_url] AS urls,
       [r IN rels | r.outlet] AS outlets,
       [r IN rels | toString(r.created)] AS dates
LIMIT $limit
"""

BACKING = """
UNWIND $pairs AS pair
MATCH (a:Entity {name: pair[0]})-[r:CLAIM {relation: pair[2]}]-(b:Entity {name: pair[1]})
RETURN pair[0] AS a, pair[1] AS b, pair[2] AS rel,
       count(DISTINCT r.outlet) AS outlets
"""


def _dedupe_paths(rows):
    """Drop paths that revisit a name, which read as nonsense."""
    clean = []
    for row in rows:
        names = row.get("names") or []
        if len(set(names)) == len(names):
            clean.append(row)
    return clean


async def _add_backing(rows):
    """Count how many independent outlets report each step of each path."""
    pairs, seen = [], set()
    for row in rows:
        names = row.get("names") or []
        relations = row.get("relations") or []
        for i, rel in enumerate(relations):
            if i + 1 < len(names):
                key = (names[i], names[i + 1], rel)
                if key not in seen:
                    seen.add(key)
                    pairs.append([names[i], names[i + 1], rel])
    if not pairs:
        return rows
    try:
        counts = await cypher(BACKING, pairs=pairs[:900])
    except Exception as exc:
        log.warning("backing lookup failed: %s", str(exc)[:100])
        return rows
    lookup = {(c["a"], c["b"], c["rel"]): c["outlets"] for c in counts}
    for row in rows:
        names = row.get("names") or []
        relations = row.get("relations") or []
        row["backing"] = [
            lookup.get((names[i], names[i + 1], rel))
            or lookup.get((names[i + 1], names[i], rel))
            or 1
            for i, rel in enumerate(relations) if i + 1 < len(names)
        ]
    return rows


@app.get("/api/connections")
async def all_connections(limit: int = Query(20, ge=1, le=60)):
    """Chains of separately recorded facts that meet at a shared name."""
    rows = await _add_backing(_dedupe_paths(
        await cypher(SIMPLE_PATHS, limit=min(limit * 25, 900))))
    chains = connections.build(rows)[:limit]
    shapes = {}
    for c in chains:
        shapes[c["label"]] = shapes.get(c["label"], 0) + 1
    if chains:
        top = max(shapes, key=shapes.get)
        summary = (
            f"{len(chains)} chains found by walking between names that were "
            f"reported separately. The most common shape is \"{top}\". "
            "A chain is a route through the records. It is not a claim that "
            "one step caused another."
        )
    else:
        summary = ("No chains yet. They appear once two recorded facts share a "
                   "name in the middle.")
    return {"summary": summary, "shapes": shapes, "connections": chains}


@app.get("/api/entity/{uid}/connections")
async def entity_connections(uid: str, limit: int = Query(12, ge=1, le=40)):
    """What the links around one name add up to."""
    if not re.fullmatch(r"[a-f0-9]{6,32}", uid or ""):
        raise HTTPException(400, "invalid id")
    rows = await _add_backing(_dedupe_paths(
        await cypher(ENTITY_PATHS, uid=uid, limit=min(limit * 25, 600))))
    chains = connections.build(rows)[:limit]
    return {"connections": chains}


@app.get("/api/cases")
async def cases(limit: int = Query(12, ge=1, le=40)):
    """Names that several outlets link to others, grouped as cases to read.

    A case is not a verdict. It is a name that has drawn enough independent
    coverage to be worth reading in one place.
    """
    rows = await cypher(
        "MATCH (e:Entity)-[r:CLAIM]-(other:Entity) "
        "WITH e, count(r) AS links, count(DISTINCT r.outlet) AS outlets, "
        "     collect(DISTINCT other.name)[..6] AS others, "
        "     max(r.created) AS latest "
        "WHERE links >= 2 AND outlets >= 1 "
        "RETURN e.uid AS uid, e.name AS name, e.type AS type, links, outlets, "
        "       others, toString(latest) AS latest "
        "ORDER BY outlets DESC, links DESC LIMIT $limit", limit=limit)
    for row in rows:
        strength = "several outlets" if row["outlets"] > 2 else (
            "two outlets" if row["outlets"] == 2 else "one outlet")
        row["headline"] = (
            f"{row['name']} appears in {row['links']} recorded links across {strength}.")
    return {"cases": rows}


@app.get("/api/case/{uid}")
async def case_detail(uid: str):
    """One case: every recorded link about a name, with its sources."""
    if not re.fullmatch(r"[a-f0-9]{6,32}", uid or ""):
        raise HTTPException(400, "invalid id")
    base = await cypher(
        "MATCH (e:Entity {uid:$uid}) RETURN e.uid AS uid, e.name AS name, "
        "e.type AS type, coalesce(e.mentions,0) AS mentions, "
        "toString(e.first_seen) AS first_seen, toString(e.last_seen) AS last_seen",
        uid=uid)
    if not base:
        raise HTTPException(404, "not found")
    claims = await cypher(
        "MATCH (a:Entity {uid:$uid})-[r:CLAIM]->(b:Entity) "
        "RETURN a.name AS subject, r.relation AS relation, b.name AS object, "
        "r.quote AS quote, r.source_url AS url, r.outlet AS outlet, "
        "toString(r.created) AS created "
        "UNION "
        "MATCH (a:Entity)-[r:CLAIM]->(b:Entity {uid:$uid}) "
        "RETURN a.name AS subject, r.relation AS relation, b.name AS object, "
        "r.quote AS quote, r.source_url AS url, r.outlet AS outlet, "
        "toString(r.created) AS created", uid=uid)
    claims.sort(key=lambda c: c.get("created") or "", reverse=True)
    outlets = sorted({c["outlet"] for c in claims if c.get("outlet")})
    relations = sorted({c["relation"] for c in claims})
    row = base[0]
    read = (
        f"{row['name']} shows up in {len(claims)} recorded links from "
        f"{len(outlets)} outlet{'s' if len(outlets) != 1 else ''}. "
        f"The links recorded are: {', '.join(r.lower().replace('_', ' ') for r in relations)}. "
        "Each one below carries the sentence it came from and a link to the article. "
        "Read the sources before drawing any conclusion."
    ) if claims else "Nothing has been recorded about this name yet."
    return {**row, "reading": read, "outlets": outlets,
            "relations": relations, "claims": claims[:100]}


@app.get("/api/insights")
async def insights():
    """Numbers behind the charts. Every figure comes from the graph."""
    by_type = await cypher(
        "MATCH (e:Entity) RETURN e.type AS name, count(*) AS value "
        "ORDER BY value DESC")
    by_relation = await cypher(
        "MATCH ()-[r:CLAIM]->() RETURN r.relation AS name, count(*) AS value "
        "ORDER BY value DESC LIMIT 12")
    by_outlet = await cypher(
        "MATCH ()-[r:CLAIM]->() WHERE r.outlet IS NOT NULL AND r.outlet <> '' "
        "RETURN r.outlet AS name, count(*) AS value ORDER BY value DESC LIMIT 10")
    busiest = await cypher(
        "MATCH (e:Entity)-[r:CLAIM]-() WITH e, count(r) AS links "
        "WHERE links > 1 RETURN e.uid AS uid, e.name AS name, e.type AS type, "
        "links AS value ORDER BY value DESC LIMIT 12")

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    daily = []
    for back in range(6, -1, -1):
        stamp = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - back * 86400,
            tz=timezone.utc).strftime("%Y%m%d")
        try:
            daily.append({
                "day": f"{stamp[4:6]}/{stamp[6:8]}",
                "processed": int(rds.get(f"khoj:stat:{stamp}:processed") or 0),
                "claims": int(rds.get(f"khoj:stat:{stamp}:claims") or 0),
            })
        except Exception:
            daily.append({"day": f"{stamp[4:6]}/{stamp[6:8]}", "processed": 0, "claims": 0})

    total_claims = sum(r["value"] for r in by_relation) or 0
    outlets = len(by_outlet)
    top_rel = by_relation[0]["name"].lower().replace("_", " ") if by_relation else "none"
    top_entity = busiest[0]["name"] if busiest else "none"
    summary = (
        f"The graph holds {sum(r['value'] for r in by_type)} names and "
        f"{total_claims} links drawn from {outlets} outlets. "
        f"The most common link is {top_rel}. "
        f"{top_entity} appears in more links than any other name."
    ) if total_claims else "Nothing has been stored yet, so there is nothing to chart."

    return {
        "summary": summary,
        "by_type": by_type,
        "by_relation": by_relation,
        "by_outlet": by_outlet,
        "busiest": busiest,
        "daily": daily,
    }


@app.get("/api/claims")
async def claims(limit: int = Query(40, ge=1, le=100)):
    rows = await cypher(
        "MATCH (a:Entity)-[r:CLAIM]->(b:Entity) "
        "RETURN a.name AS subject, a.uid AS subject_uid, r.relation AS relation, "
        "b.name AS object, b.uid AS object_uid, r.quote AS quote, "
        "r.source_url AS url, r.outlet AS outlet, toString(r.created) AS created "
        "ORDER BY r.created DESC LIMIT $limit", limit=limit)
    return {"claims": rows}


@app.get("/api/machine")
async def machine():
    """Load, disk and running totals, written by the agents container.

    The API does not measure anything itself. It reads the last reading the
    agents container took, and says how old it is, so a stale figure is
    obvious rather than being presented as current.
    """
    try:
        raw = rds.get("khoj:machine")
    except Exception:
        raw = None
    if not raw:
        return {"available": False,
                "note": "the agents container has not reported a reading yet"}
    snap = json.loads(raw)
    age = time.time() - (snap.get("at") or 0)
    snap["available"] = True
    snap["age_seconds"] = int(age)
    snap["fresh"] = age < 180
    if not snap["fresh"]:
        snap["note"] = (f"this reading is {int(age)} seconds old, "
                        "so the agents container may have stopped")
    return snap


@app.get("/api/watchlist")
async def watchlist(limit: int = Query(30, ge=1, le=100)):
    """Names being followed and the links that touched them."""
    names, hits = [], []
    try:
        raw = rds.hgetall("khoj:watch") or {}
        for value in raw.values():
            try:
                names.append(json.loads(value))
            except (ValueError, TypeError):
                continue
        names.sort(key=lambda w: -(int(w.get("hits") or 0)))
    except Exception:
        pass
    try:
        hits = [json.loads(r) for r in rds.lrange("khoj:watch:hits", 0, limit - 1)]
    except Exception:
        pass
    return {
        "watching": names,
        "hits": hits,
        "note": ("Names are followed from Telegram. This page shows what is "
                 "being followed and what has come in."),
    }


@app.get("/api/merges")
async def merge_log(limit: int = Query(40, ge=1, le=100)):
    """What was folded together, and what is still waiting for a decision.

    Merging is the one thing here that removes something, so it is written
    down. Every fold is listed with the rule that caused it.
    """
    folded, waiting = [], []
    try:
        folded = [json.loads(r) for r in rds.lrange("khoj:merges", 0, limit - 1)]
    except Exception:
        pass
    try:
        raw = rds.hgetall("khoj:merge:review") or {}
        for value in raw.values():
            try:
                waiting.append(json.loads(value))
            except (ValueError, TypeError):
                continue
        waiting.sort(key=lambda r: -(r.get("ts") or 0))
    except Exception:
        pass
    automatic = sum(1 for f in folded if f.get("automatic"))
    return {
        "merged": folded,
        "waiting": waiting[:60],
        "summary": (
            f"{len(folded)} recent merges, {automatic} of them made without "
            f"asking. {len(waiting)} pairs were too close to call and are "
            "waiting for a decision."
        ) if folded or waiting else
        "No duplicate names have been folded together yet.",
    }


@app.get("/api/sources")
async def source_list():
    """Which sources are producing and which are silent."""
    snap = {}
    try:
        raw = rds.get("khoj:machine")
        if raw:
            snap = json.loads(raw)
    except Exception:
        pass
    rows = snap.get("sources") or []
    dead = [r for r in rows if not r.get("items")]
    return {
        "sources": rows,
        "by_outlet": snap.get("by_outlet_seen") or [],
        "claims_by_outlet": snap.get("by_outlet_claims") or [],
        "summary": (
            f"{len(rows)} sources have been tried. {len(dead)} returned "
            "nothing the last time. A source that returns nothing is usually "
            "one that changed its address or now needs a browser."
        ) if rows else "No source has been tried yet.",
    }


PARTY_LINKS = """
MATCH (p:Entity {type:'Party'})-[r:CLAIM]-(other:Entity)
WHERE r.relation <> 'MENTIONED_WITH'
RETURN p.uid AS uid, p.name AS name, count(r) AS links,
       count(DISTINCT r.outlet) AS outlets,
       collect(DISTINCT other.name)[..8] AS around,
       collect(DISTINCT r.relation)[..8] AS relations
ORDER BY links DESC LIMIT $limit
"""

PARTY_MONEY = """
MATCH (a:Entity)-[r:CLAIM]->(b:Entity)
WHERE (a.type = 'Party' OR b.type = 'Party')
  AND r.relation IN ['DONATED_TO','AWARDED_CONTRACT','RECEIVED_CONTRACT',
                     'OWNS','APPOINTED','APPROVED','RULED_ON']
RETURN a.name AS subject, a.uid AS subject_uid, r.relation AS relation,
       b.name AS object, b.uid AS object_uid, r.quote AS quote,
       r.source_url AS url, r.outlet AS outlet, toString(r.created) AS created
ORDER BY r.created DESC LIMIT $limit
"""

PARTY_PATHS = """
MATCH path = (a:Entity {type:'Party'})-[rels:CLAIM*1..3]-(b:Entity)
WHERE ALL(r IN rels WHERE r.relation <> 'MENTIONED_WITH')
RETURN [n IN nodes(path) | n.name] AS names,
       [n IN nodes(path) | n.uid] AS uids,
       [n IN nodes(path) | n.type] AS types,
       [r IN rels | r.relation] AS relations,
       [r IN rels | r.quote] AS quotes,
       [r IN rels | r.source_url] AS urls,
       [r IN rels | r.outlet] AS outlets,
       [r IN rels | toString(r.created)] AS dates
LIMIT $limit
"""


@app.get("/api/parties")
async def parties(limit: int = Query(15, ge=1, le=40)):
    """Everything recorded that touches a political party.

    Parties get their own page because money and decisions around them are
    the links most worth reading, not because anything here is aimed at one
    of them. The same rules and the same sourcing apply as everywhere else.
    """
    rows = await cypher(PARTY_LINKS, limit=limit)
    money = await cypher(PARTY_MONEY, limit=40)
    chains = connections.build(await _add_backing(_dedupe_paths(
        await cypher(PARTY_PATHS, limit=400))))[:limit]

    total_links = sum(r["links"] for r in rows)
    if rows:
        summary = (
            f"{len(rows)} political parties appear in {total_links} recorded "
            f"links. {len(money)} of those involve money, a contract, an "
            "appointment or a decision. Everything here is a link an article "
            "stated, not a finding."
        )
    else:
        summary = ("No party has been recorded yet. A name becomes a party "
                   "when it matches a known party or carries a party word.")
    return {"summary": summary, "parties": rows, "money": money,
            "connections": chains}
