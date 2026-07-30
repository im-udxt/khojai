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
    down = [k for k, v in services.items() if v.get("state") != "up"]
    return {
        "checked": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "queue_depth": (snapshot or {}).get("queue_depth", 0),
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
    return {
        "today": {
            "seen": counter("seen"),
            "queued": counter("queued"),
            "processed": counter("processed"),
            "claims": counter("claims"),
            "duplicates": counter("duplicate"),
        },
        "total": {"entities": row["entities"], "claims": row["claims"]},
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
        if type not in {"Person", "Company", "Government", "Court", "Place", "Topic", "Event"}:
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


@app.get("/api/claims")
async def claims(limit: int = Query(40, ge=1, le=100)):
    rows = await cypher(
        "MATCH (a:Entity)-[r:CLAIM]->(b:Entity) "
        "RETURN a.name AS subject, a.uid AS subject_uid, r.relation AS relation, "
        "b.name AS object, b.uid AS object_uid, r.quote AS quote, "
        "r.source_url AS url, r.outlet AS outlet, toString(r.created) AS created "
        "ORDER BY r.created DESC LIMIT $limit", limit=limit)
    return {"claims": rows}
