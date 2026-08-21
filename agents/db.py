"""Graph and cache access.

Every write goes through save_claim, which refuses anything without a source.
All Cypher uses parameters, never string building, so user input cannot alter
a query.
"""
import json
import logging
import threading
from datetime import datetime, timezone

import redis as redis_lib
from neo4j import GraphDatabase

import config
import entities

log = logging.getLogger("khoj.db")

_driver = None
_redis = None
_lock = threading.Lock()

RELATIONS = {
    "WORKS_AT", "LEADS", "OWNS", "MEMBER_OF", "AWARDED_CONTRACT",
    "RECEIVED_CONTRACT", "INVESTIGATED_BY", "CHARGED_BY", "ACCUSED_OF",
    "FILED_CASE", "NAMED_IN", "RULED_ON", "APPROVED", "BLOCKED",
    "MET_WITH", "DONATED_TO", "APPOINTED", "RESIGNED_FROM", "MENTIONED_WITH",
}


def now():
    return datetime.now(timezone.utc)


def driver():
    global _driver
    with _lock:
        if _driver is None:
            _driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
                max_connection_lifetime=300,
            )
    return _driver


def rds():
    global _redis
    with _lock:
        if _redis is None:
            _redis = redis_lib.Redis.from_url(config.REDIS_URL, decode_responses=True)
    return _redis


def query(cypher, **params):
    with driver().session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def ensure_schema():
    stmts = [
        "CREATE CONSTRAINT entity_uid IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.uid IS UNIQUE",
        "CREATE INDEX entity_key IF NOT EXISTS FOR (e:Entity) ON (e.key)",
        "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
        "CREATE INDEX entity_seen IF NOT EXISTS FOR (e:Entity) ON (e.last_seen)",
        "CREATE CONSTRAINT source_url IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.url IS UNIQUE",
        "CREATE CONSTRAINT case_id IF NOT EXISTS "
        "FOR (c:Case) REQUIRE c.id IS UNIQUE",
        # Full text index is what makes entity search fast and forgiving.
        "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS "
        "FOR (e:Entity) ON EACH [e.name, e.aliases]",
    ]
    with driver().session() as s:
        for stmt in stmts:
            try:
                s.run(stmt)
            except Exception as exc:
                log.warning("schema step skipped: %s", str(exc)[:120])
    log.info("graph schema ready")


def upsert_entity(ent):
    """Create or update one canonical entity. Returns its uid."""
    query(
        """
        MERGE (e:Entity {uid: $uid})
        ON CREATE SET e.name = $name, e.key = $key, e.type = $type,
                      e.first_seen = datetime($ts), e.mentions = 0,
                      e.aliases = [$name]
        SET e.last_seen = datetime($ts),
            e.mentions = coalesce(e.mentions, 0) + 1,
            // Let a later, more specific reading replace a vague one, so the
            // graph corrects itself as a name is seen again.
            e.type = CASE WHEN coalesce(e.type,'Topic') = 'Topic' AND $type <> 'Topic'
                     THEN $type ELSE e.type END,
            e.aliases = CASE WHEN $name IN coalesce(e.aliases, [])
                        THEN e.aliases ELSE coalesce(e.aliases, []) + $name END,
            // Prefer the fuller spelling, but only up to a point. Taking the
            // longest name outright meant one sentence fragment could become
            // the label for a name that was otherwise recorded correctly.
            e.name = CASE WHEN size($name) > size(coalesce(e.name, ''))
                           AND size($name) <= 60
                      THEN $name ELSE e.name END
        """,
        uid=ent["uid"], name=ent["name"], key=ent["key"], type=ent["type"],
        ts=now().isoformat(),
    )
    return ent["uid"]


def save_claim(subject, relation, obj, quote, source):
    """Write one sourced relationship.

    Refuses the write unless there is a subject, an object, a quote taken from
    the article, and a source url. A claim without those is not a claim.
    """
    relation = (relation or "MENTIONED_WITH").upper().replace(" ", "_")
    if relation not in RELATIONS:
        relation = "MENTIONED_WITH"
    quote = (quote or "").strip()
    url = (source or {}).get("url", "").strip()
    if not (subject and obj and quote and url):
        return False
    if subject["uid"] == obj["uid"]:
        return False

    upsert_entity(subject)
    upsert_entity(obj)
    query(
        """
        MERGE (s:Source {url: $url})
        ON CREATE SET s.title = $title, s.outlet = $outlet,
                      s.published = $published, s.fetched = datetime($ts)
        WITH s
        MATCH (a:Entity {uid: $a}), (b:Entity {uid: $b})
        MERGE (a)-[r:CLAIM {relation: $rel, source_url: $url}]->(b)
        ON CREATE SET r.quote = $quote, r.created = datetime($ts),
                      r.outlet = $outlet, r.published = $published
        SET r.last_seen = datetime($ts)
        MERGE (a)-[:CITED_IN]->(s)
        MERGE (b)-[:CITED_IN]->(s)
        """,
        url=url, title=(source.get("title") or "")[:300],
        outlet=(source.get("outlet") or "")[:120],
        published=(source.get("published") or ""),
        a=subject["uid"], b=obj["uid"], rel=relation,
        quote=quote[:600], ts=now().isoformat(),
    )
    count_outlet(source.get("outlet") or "unknown", "claims")
    try:
        import watch
        watch.on_claim(subject, relation, obj, quote, source)
    except Exception as exc:
        # A watchlist problem must never stop a claim being written.
        log.debug("watch notify skipped: %s", str(exc)[:80])
    return True


def outlet_count(a_uid, b_uid, relation):
    """How many independent outlets carry this relationship."""
    rows = query(
        """
        MATCH (a:Entity {uid: $a})-[r:CLAIM {relation: $rel}]->(b:Entity {uid: $b})
        RETURN count(DISTINCT r.outlet) AS n
        """, a=a_uid, b=b_uid, rel=relation)
    return rows[0]["n"] if rows else 0


def search_entities(text, limit=15):
    """Forgiving entity search backed by the full text index."""
    text = (text or "").strip()
    if len(text) < 2:
        return []
    ent = entities.canonical(text)
    key = ent["key"] if ent else text.lower()
    terms = " ".join(f"{w}~" for w in key.split() if len(w) > 2) or f"{key}~"
    try:
        rows = query(
            """
            CALL db.index.fulltext.queryNodes('entity_search', $terms)
            YIELD node, score
            RETURN node.uid AS uid, node.name AS name, node.type AS type,
                   coalesce(node.mentions, 0) AS mentions, score
            ORDER BY score DESC, mentions DESC LIMIT $limit
            """, terms=terms, limit=limit)
        if rows:
            return rows
    except Exception as exc:
        log.warning("fulltext search failed, using prefix match: %s", str(exc)[:100])
    return query(
        """
        MATCH (e:Entity) WHERE e.key STARTS WITH $key OR e.key CONTAINS $key
        RETURN e.uid AS uid, e.name AS name, e.type AS type,
               coalesce(e.mentions, 0) AS mentions, 1.0 AS score
        ORDER BY mentions DESC LIMIT $limit
        """, key=key, limit=limit)


def stat(name, amount=1):
    """Count one thing, for today and for all time.

    The daily counter expires after nine days so the charts stay small. The
    running total never expires, because "how much has this read since it was
    switched on" is a different question from "what did it do today", and the
    first one had no answer before.
    """
    try:
        pipe = rds().pipeline()
        pipe.incrby(f"khoj:stat:{now():%Y%m%d}:{name}", amount)
        pipe.expire(f"khoj:stat:{now():%Y%m%d}:{name}", 86400 * 9)
        pipe.incrby(f"khoj:total:{name}", amount)
        pipe.setnx("khoj:total:since", now().isoformat())
        pipe.execute()
    except Exception:
        pass


def totals():
    """Every running total, with the date counting started.

    Counting started when this was added, not when the project did, so the
    date is returned alongside the numbers rather than left to be assumed.
    """
    names = ["seen", "queued", "processed", "claims", "duplicate",
             "fetched", "merged", "alerts"]
    out = {}
    try:
        r = rds()
        values = r.mget([f"khoj:total:{n}" for n in names])
        out = {n: int(v or 0) for n, v in zip(names, values)}
        out["since"] = r.get("khoj:total:since") or ""
    except Exception:
        out = {n: 0 for n in names}
        out["since"] = ""
    return out


def count_outlet(outlet, field="seen", amount=1):
    """Per outlet running totals, so a source that produces nothing is visible."""
    if not outlet:
        return
    try:
        rds().hincrby(f"khoj:outlet:{field}", outlet, amount)
    except Exception:
        pass


def outlet_totals(field="seen"):
    try:
        raw = rds().hgetall(f"khoj:outlet:{field}") or {}
        return sorted(({"outlet": k, "value": int(v)} for k, v in raw.items()),
                      key=lambda r: -r["value"])
    except Exception:
        return []


def activity(actor, message):
    try:
        r = rds()
        r.lpush("khoj:activity", json.dumps(
            {"ts": now().isoformat(), "actor": actor, "message": message}))
        r.ltrim("khoj:activity", 0, 199)
    except Exception:
        pass
    logging.getLogger(f"khoj.{actor}").info(message)
