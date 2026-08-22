"""The crawl and processing loop.

Four cheap steps run before the model is asked for anything, because the model
is the slow part. Near duplicate detection uses simhash rather than sentence
embeddings, which removes a large dependency and runs in microseconds.
"""
import gzip
import hashlib
import json
import logging
import os
import re
import time
from urllib.parse import urlparse, urlunparse

import config
import db
import extract
import sources

log = logging.getLogger("khoj.pipeline")

TRACKING = ("utm_", "fbclid", "gclid", "cmpid", "ref_", "at_medium")
WORD_RE = re.compile(r"[a-z0-9']+")

# A document is worth the model's time when it touches these areas.
SIGNAL_WORDS = {
    "court", "case", "petition", "verdict", "judgment", "bail", "fir", "probe",
    "investigation", "cbi", "enforcement", "raid", "summons", "chargesheet",
    "contract", "tender", "award", "procurement", "crore", "lakh", "auction",
    "minister", "ministry", "parliament", "sabha", "bill", "policy", "cabinet",
    "sebi", "rbi", "regulator", "penalty", "fine", "notice", "compliance",
    "acquisition", "merger", "stake", "shareholder", "board", "director",
    "resign", "appointed", "arrested", "accused", "fraud", "scam", "audit",
    "election", "candidate", "affidavit", "donation", "funding", "trust",
}

BORING_URL = re.compile(
    r"/(sport|sports|cricket|football|entertainment|bollywood|lifestyle|"
    r"fashion|food|recipe|travel|horoscope|astrology|gadget|gaming|movie|"
    r"celebrity|photo|video|gallery|live-blog)/", re.IGNORECASE)


def normalise_url(url):
    try:
        p = urlparse(url.strip())
        query = "&".join(part for part in p.query.split("&")
                         if part and not part.lower().startswith(TRACKING))
        return urlunparse((p.scheme.lower(), p.netloc.lower(),
                           p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url.strip()


def url_id(url):
    return hashlib.sha1(normalise_url(url).encode()).hexdigest()


def simhash(text):
    """64 bit fingerprint. Two near identical articles differ in few bits."""
    words = WORD_RE.findall((text or "").lower())
    if not words:
        return 0
    shingles = [" ".join(words[i:i + 3]) for i in range(max(len(words) - 2, 1))]
    vector = [0] * 64
    for shingle in shingles:
        h = int(hashlib.md5(shingle.encode()).hexdigest()[:16], 16)
        for bit in range(64):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit in range(64):
        if vector[bit] > 0:
            out |= 1 << bit
    return out


def hamming(a, b):
    return bin(a ^ b).count("1")


def seen_before(url):
    return db.rds().sismember("khoj:seen", url_id(url))


def mark_seen(url):
    r = db.rds()
    r.sadd("khoj:seen", url_id(url))
    if r.scard("khoj:seen") > 400000:
        r.spop("khoj:seen", 50000)


def is_near_duplicate(text):
    """Compare against fingerprints from the last few thousand documents."""
    fp = simhash(text)
    if not fp:
        return True
    r = db.rds()
    for other in r.lrange("khoj:fingerprints", 0, 2500):
        try:
            if hamming(fp, int(other)) <= 6:
                return True
        except ValueError:
            continue
    pipe = r.pipeline()
    pipe.lpush("khoj:fingerprints", fp)
    pipe.ltrim("khoj:fingerprints", 0, 4000)
    pipe.execute()
    return False


def worth_reading(doc):
    """Cheap relevance test. No model involved."""
    url = doc.get("url", "")
    blob = f"{doc.get('title','')} {doc.get('text','')}".lower()
    words = set(WORD_RE.findall(blob))
    hits = len(words & SIGNAL_WORDS)
    if BORING_URL.search(url) and hits < 2:
        return False
    return hits >= 1


def archive(doc):
    """Keep a compressed copy of what we saw, before anything is derived."""
    try:
        day = time.strftime("%Y/%m/%d")
        folder = os.path.join(config.ARCHIVE_DIR, day)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{url_id(doc['url'])}.json.gz")
        if not os.path.exists(path):
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
    except Exception as exc:
        log.debug("archive skipped: %s", str(exc)[:80])


def queue_for_model(doc):
    db.rds().lpush("khoj:queue", json.dumps(doc))
    db.stat("queued")


def collect(docs, priority=False):
    """Run documents through the cheap steps and queue the survivors.

    Looking at a document is cheap: one Redis lookup says whether it has been
    seen. Fetching its body is not, because it is a request to somebody else's
    server at one per second. So the number examined is left wide and the
    number fetched is what gets a budget. Anything past the budget is left
    unmarked so the next sweep picks it up rather than losing it.
    """
    counts = {"in": len(docs), "new": 0, "relevant": 0, "queued": 0,
              "held_over": 0}
    budget = config.MAX_FETCH_PER_SWEEP if not priority else len(docs)
    for doc in docs:
        db.stat("seen")
        db.count_outlet(doc.get("outlet"), "seen")
        if not doc.get("url") or seen_before(doc["url"]):
            continue
        counts["new"] += 1
        if not worth_reading(doc):
            mark_seen(doc["url"])
            continue
        counts["relevant"] += 1
        if budget <= 0:
            counts["held_over"] += 1
            continue
        budget -= 1

        body = sources.fetch_article(doc["url"])
        if len(body) > len(doc.get("text", "")):
            doc["text"] = body
        mark_seen(doc["url"])

        if is_near_duplicate(doc.get("text", "") or doc.get("title", "")):
            db.stat("duplicate")
            continue

        archive(doc)
        if priority:
            db.rds().rpush("khoj:queue:priority", json.dumps(doc))
        else:
            queue_for_model(doc)
        counts["queued"] += 1
    return counts


def interleave(docs, cap):
    """Take from every source in turn until the cap is reached.

    Cutting a flat list at the cap reads the first few sources and never
    reaches the rest. With 26 sources that was survivable. With 65 it meant
    5 sources were read and 47 were not, and the crawler spent every sweep
    re-reading the same articles it had already seen.
    """
    buckets, order = {}, []
    for doc in docs:
        key = doc.get("outlet_id") or "unknown"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(doc)

    out, depth = [], 0
    while len(out) < cap:
        took = False
        for key in order:
            group = buckets[key]
            if depth < len(group):
                out.append(group[depth])
                took = True
                if len(out) >= cap:
                    break
        if not took:
            break
        depth += 1
    return out


def sweep():
    """One pass over the feeds, the topic searches and a few listing pages."""
    db.activity("crawler", "reading feeds and searches")
    feed_docs = sources.read_feeds()

    walked = []
    try:
        walked = sources.read_sites()
        if walked:
            db.activity("crawler",
                        f"walked listing pages, {len(walked)} links to check")
    except Exception as exc:
        log.warning("site walk skipped: %s", str(exc)[:100])

    # Listing pages go first. They are the smallest group and the hardest to
    # get, so they must never be the ones the cap throws away.
    docs = walked + interleave(feed_docs, max(config.MAX_DOCS_PER_SWEEP - len(walked), 1))
    counts = collect(docs)
    counts["from_sites"] = len(walked)

    # A run of sweeps that finds nothing new anywhere is a fault, not a quiet
    # news day. Health cannot see it from the queue, because a starved intake
    # and a caught up one both leave the queue empty.
    try:
        if counts["new"]:
            db.rds().delete("khoj:crawler:barren")
        else:
            db.rds().incr("khoj:crawler:barren")
            db.rds().expire("khoj:crawler:barren", 86400)
    except Exception:
        pass

    held = f", {counts['held_over']} held over" if counts.get("held_over") else ""
    db.activity("crawler",
                f"{counts['in']} items, {counts['new']} new, "
                f"{counts['queued']} sent to the model{held}")
    return counts


def crawl_loop(stop):
    """Sweep on a period, not on a gap.

    This used to sweep and then wait the full interval, so the real cycle was
    the interval plus however long the sweep took. With a short source list
    that was a few seconds of drift. With sixty five sources a sweep runs for
    nearly three minutes, so a four minute interval became a seven minute
    one and the site looked stalled between updates.

    It also sat idle through that wait while documents it already knew were
    new went unfetched. When the fetch budget runs out there is work in hand,
    so it goes straight back round instead.
    """
    import health

    while not stop.is_set():
        started = time.monotonic()
        held_over = 0
        try:
            health.beat(health.CRAWLER_BEAT, "sweeping")
            counts = sweep() or {}
            held_over = counts.get("held_over", 0)
        except Exception as exc:
            log.exception("sweep failed: %s", exc)

        if held_over:
            wait = config.CRAWL_MIN_GAP
            health.beat(health.CRAWLER_BEAT,
                        f"{held_over} known documents still to fetch")
        else:
            elapsed = time.monotonic() - started
            wait = max(config.CRAWL_INTERVAL - elapsed, config.CRAWL_MIN_GAP)
            health.beat(health.CRAWLER_BEAT, "waiting")
        stop.wait(wait)


def process_one(doc):
    """Extract claims from one queued document and save them."""
    source = {
        "url": doc.get("url"), "title": doc.get("title"),
        "outlet": doc.get("outlet"), "published": doc.get("published"),
    }
    claims = extract.claims_from(doc)
    if config.VERIFY_CLAIMS:
        checked = []
        for claim in claims:
            kept = extract.verify(claim)
            if kept:
                checked.append(kept)
            else:
                db.stat("rejected_on_check")
        claims = checked
    saved = 0
    for claim in claims:
        if db.save_claim(claim["subject"], claim["relation"], claim["object"],
                         claim["quote"], source):
            saved += 1
    db.stat("processed")
    if saved:
        db.stat("claims", saved)
        db.activity("model", f"{saved} claims from {doc.get('title','')[:70]}")
    return saved


def worker_loop(stop):
    """Take documents off the queue one at a time."""
    import health
    while not stop.is_set():
        health.beat(health.WORKER_BEAT, "checking model")
        if not extract.model_ready():
            db.rds().set("khoj:model_down", "1", ex=120)
            health.beat(health.WORKER_BEAT, "waiting for the model")
            stop.wait(30)
            continue
        db.rds().delete("khoj:model_down")

        raw = db.rds().rpop("khoj:queue:priority") or db.rds().rpop("khoj:queue")
        if not raw:
            health.beat(health.WORKER_BEAT, "idle")
            stop.wait(5)
            continue
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        health.beat(health.WORKER_BEAT, f"reading {doc.get('title','')[:50]}")
        try:
            process_one(doc)
            db.rds().delete(health.WORKER_FAILS)
        except Exception as exc:
            # Count consecutive failures so health can tell a model that
            # answers but cannot produce anything from a healthy one.
            try:
                db.rds().incr(health.WORKER_FAILS)
                db.rds().expire(health.WORKER_FAILS, 1800)
            except Exception:
                pass
            log.warning("processing failed, document returned to queue: %s",
                        str(exc)[:120])
            db.rds().rpush("khoj:queue", raw)
            stop.wait(15)
