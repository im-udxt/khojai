"""Following a name.

The site is useful to read once. It is only useful to keep if it tells you
when something changes. A watched name is matched on the same canonical key
the graph uses, so "Shri Gautam Adani" and "Gautam Adani" are the same watch,
and adding one spelling does not miss the other.

Nothing here writes to the graph. A watch is a Redis entry and an alert is a
queued message, so a failure in this file cannot lose a claim.
"""
import json
import logging
import time

import db
import entities

log = logging.getLogger("khoj.watch")

WATCH_KEY = "khoj:watch"
HITS_KEY = "khoj:watch:hits"
QUEUE_KEY = "khoj:alerts:out"
SEEN_KEY = "khoj:alerts:seen"
MAX_WATCHES = 60


def _key(name):
    ent = entities.canonical(name)
    return ent["key"] if ent else (name or "").strip().lower()


def add(name, note=""):
    """Start following a name. Returns (ok, message)."""
    name = (name or "").strip()
    if len(name) < 3:
        return False, "Give me a name of at least three characters."
    key = _key(name)
    if not key:
        return False, f"{name} does not look like a name."
    r = db.rds()
    if r.hlen(WATCH_KEY) >= MAX_WATCHES and not r.hexists(WATCH_KEY, key):
        return False, f"Already following {MAX_WATCHES} names. Remove one first."
    if r.hexists(WATCH_KEY, key):
        return False, f"Already following {name}."
    r.hset(WATCH_KEY, key, json.dumps(
        {"name": name, "key": key, "note": note[:120],
         "added": time.time(), "hits": 0}))
    db.activity("watch", f"following {name}")
    return True, f"Following {name}. You get a message when a new link touches it."


def remove(name):
    key = _key(name)
    r = db.rds()
    if not r.hexists(WATCH_KEY, key):
        return False, f"Not following {name}."
    r.hdel(WATCH_KEY, key)
    db.activity("watch", f"stopped following {name}")
    return True, f"Stopped following {name}."


def listing():
    """Every watched name, most active first."""
    out = []
    try:
        raw = db.rds().hgetall(WATCH_KEY) or {}
    except Exception:
        return out
    for key, value in raw.items():
        try:
            item = json.loads(value)
        except (ValueError, TypeError):
            continue
        item.setdefault("key", key)
        item.setdefault("hits", 0)
        out.append(item)
    out.sort(key=lambda w: (-int(w.get("hits") or 0), w.get("name", "")))
    return out


def watched_keys():
    try:
        return set(db.rds().hkeys(WATCH_KEY) or [])
    except Exception:
        return set()


def hits(limit=40):
    """The most recent links that touched a watched name."""
    try:
        rows = db.rds().lrange(HITS_KEY, 0, limit - 1)
        return [json.loads(r) for r in rows]
    except Exception:
        return []


def on_claim(subject, relation, obj, quote, source):
    """Called for every claim written. Cheap when nothing is watched."""
    keys = watched_keys()
    if not keys:
        return
    touched = [e for e in (subject, obj) if e and e.get("key") in keys]
    if not touched:
        return

    url = (source or {}).get("url", "")
    for ent in touched:
        marker = f"{ent['key']}|{relation}|{subject['key']}|{obj['key']}|{url}"
        try:
            # An article can be re alerted only once, even if it is seen again.
            if not db.rds().sadd(SEEN_KEY, marker):
                continue
            db.rds().expire(SEEN_KEY, 86400 * 30)
        except Exception:
            pass

        item = {
            "ts": time.time(),
            "watched": ent["name"],
            "subject": subject["name"],
            "relation": relation,
            "object": obj["name"],
            "quote": (quote or "")[:400],
            "url": url,
            "outlet": (source or {}).get("outlet", ""),
        }
        try:
            r = db.rds()
            pipe = r.pipeline()
            pipe.lpush(HITS_KEY, json.dumps(item))
            pipe.ltrim(HITS_KEY, 0, 299)
            pipe.lpush(QUEUE_KEY, json.dumps(item))
            pipe.ltrim(QUEUE_KEY, 0, 199)
            pipe.execute()
            raw = r.hget(WATCH_KEY, ent["key"])
            if raw:
                record = json.loads(raw)
                record["hits"] = int(record.get("hits") or 0) + 1
                record["last"] = item["ts"]
                r.hset(WATCH_KEY, ent["key"], json.dumps(record))
        except Exception as exc:
            log.debug("alert not queued: %s", str(exc)[:80])
        db.stat("alerts")


def take_alerts(limit=8):
    """Pull queued alerts for sending. They are removed as they are taken."""
    out = []
    try:
        r = db.rds()
        for _ in range(limit):
            raw = r.rpop(QUEUE_KEY)
            if not raw:
                break
            out.append(json.loads(raw))
    except Exception:
        pass
    return out


def as_message(item):
    """One alert as a short block of text.

    The quote is copied from an article, so it can contain angle brackets.
    Everything is escaped before it goes anywhere near Telegram's markup.
    """
    from html import escape as esc

    words = (item.get("relation") or "").lower().replace("_", " ")
    lines = [
        f"<b>{esc(item.get('watched', ''))}</b>",
        f"{esc(item.get('subject', ''))} {esc(words)} {esc(item.get('object', ''))}",
    ]
    if item.get("quote"):
        lines.append(f"<i>{esc(item['quote'])}</i>")
    if item.get("url"):
        lines.append(f"{esc(item.get('outlet') or 'source')}: {esc(item['url'])}")
    return "\n".join(lines)
