"""Answering questions and running investigations."""
import logging
import re
import threading
import time

import db
import entities
import extract
import pipeline
import sources

log = logging.getLogger("khoj.research")

_busy = threading.Lock()
STOPWORDS_Q = {"what", "who", "where", "when", "why", "how", "is", "are", "was",
               "the", "and", "between", "connection", "relation", "relationship",
               "link", "links", "with", "about", "show", "find", "tell", "me",
               "of", "in", "on", "for", "to", "any", "all", "does", "did"}


def names_in(text):
    """Pick the entity names out of a free form question."""
    found, seen = [], set()
    for chunk in re.findall(r"[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*)*", text or ""):
        ent = entities.canonical(chunk)
        if ent and ent["key"] not in seen:
            seen.add(ent["key"])
            found.append(chunk.strip())
    if not found:
        words = [w for w in re.split(r"\W+", text or "")
                 if len(w) > 2 and w.lower() not in STOPWORDS_Q]
        if words:
            found = [" ".join(words[:4])]
    return found[:4]


def facts_for(names, limit=40):
    """Every sourced claim touching these names, plus paths between them."""
    uids = []
    for name in names:
        hits = db.search_entities(name, limit=2)
        uids.extend(h["uid"] for h in hits)
    uids = list(dict.fromkeys(uids))
    if not uids:
        return [], []

    direct = db.query(
        """
        MATCH (a:Entity)-[r:CLAIM]->(b:Entity)
        WHERE a.uid IN $uids OR b.uid IN $uids
        RETURN a.name AS subject, r.relation AS relation, b.name AS object,
               r.quote AS quote, r.source_url AS url, r.outlet AS outlet,
               toString(r.created) AS created
        ORDER BY r.created DESC LIMIT $limit
        """, uids=uids, limit=limit)

    paths = []
    if len(uids) >= 2:
        paths = db.query(
            """
            MATCH (a:Entity), (b:Entity)
            WHERE a.uid = $a AND b.uid = $b
            MATCH p = shortestPath((a)-[:CLAIM*1..4]-(b))
            RETURN [n IN nodes(p) | n.name] AS chain,
                   [r IN relationships(p) | r.relation] AS steps,
                   [r IN relationships(p) | r.source_url] AS urls
            LIMIT 5
            """, a=uids[0], b=uids[1])
    return direct, paths


def report(question):
    """Answer a question from the graph. Never invents anything."""
    names = names_in(question)
    direct, paths = facts_for(names)
    if not direct:
        return (f"Nothing documented yet for: {question}\n\n"
                "This means no crawled article has stated a relationship for "
                "these names. It does not mean none exists.")

    lines, cites = [], []
    for i, row in enumerate(direct[:20], 1):
        lines.append(f'[{i}] {row["subject"]} {row["relation"].lower().replace("_", " ")} '
                     f'{row["object"]}. Quote: "{row["quote"][:180]}" ({row["outlet"]})')
        cites.append(row)

    summary = extract.summarise(question, lines)
    out = [f"<b>{_esc(question)}</b>", "", _esc(summary), ""]

    if paths:
        out.append("<b>How they connect</b>")
        for p in paths[:3]:
            chain = p["chain"]
            steps = p["steps"]
            pretty = chain[0]
            for step, node in zip(steps, chain[1:]):
                pretty += f" → {step.lower().replace('_',' ')} → {node}"
            out.append(_esc(pretty))
        out.append("")

    out.append("<b>Sources</b>")
    for i, row in enumerate(cites[:8], 1):
        out.append(f'{i}. <a href="{_esc(row["url"])}">{_esc(row["outlet"] or "source")}</a> '
                   f'{_esc(row["subject"])} {_esc(row["relation"].lower().replace("_"," "))} '
                   f'{_esc(row["object"])}')
    outlets = {r["outlet"] for r in cites if r["outlet"]}
    out.append("")
    out.append(f"{len(cites)} claims from {len(outlets)} outlets.")
    if len(outlets) < 2:
        out.append("<i>Single outlet. Check it yourself before relying on it.</i>")
    return "\n".join(out)


def investigate(question, progress=None):
    """Go and fetch new material for a question, then answer it."""
    def say(msg):
        db.activity("research", msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    if not _busy.acquire(blocking=False):
        return "An investigation is already running. Try again in a few minutes."
    try:
        names = names_in(question) or [question]
        say(f"Looking into: {question}")
        say(f"Names found: {', '.join(names)}")

        docs = sources.search_news(question, limit=25)
        for name in names:
            docs.extend(sources.search_news(name, limit=15))
        unique = {}
        for d in docs:
            unique.setdefault(d["url"], d)
        say(f"Found {len(unique)} articles. Reading them now.")

        counts = pipeline.collect(list(unique.values()), priority=True)
        say(f"{counts['queued']} articles queued for reading.")

        target = max(counts["queued"], 1)
        for _ in range(40):
            time.sleep(6)
            pending = db.rds().llen("khoj:queue:priority")
            if pending == 0:
                break
            if pending < target:
                say(f"{target - pending} of {target} read.")
                target = pending

        say("Writing up what was found.")
        return report(question)
    finally:
        _busy.release()


def _esc(text):
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))
