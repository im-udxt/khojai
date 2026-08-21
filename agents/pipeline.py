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
    """Run documents through the cheap steps and queue the survivors."""
    counts = {"in": len(docs), "new": 0, "relevant": 0, "queued": 0}
    for doc in docs:
        db.stat("seen")
        if not doc.get("url") or seen_before(doc["url"]):
            continue
        counts["new"] += 1
        if not worth_reading(doc):
            mark_seen(doc["url"])
            continue
        counts["relevant"] += 1

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


def sweep():
    """One pass over every feed."""
    db.activity("crawler", "reading feeds")
    docs = sources.read_feeds()[:config.MAX_DOCS_PER_SWEEP]
    counts = collect(docs)
    db.activity("crawler",
                f"{counts['in']} items, {counts['new']} new, "
                f"{counts['queued']} sent to the model")
    return counts


def crawl_loop(stop):
    import health
    while not stop.is_set():
        try:
            health.beat(health.CRAWLER_BEAT, "sweeping")
            sweep()
            health.beat(health.CRAWLER_BEAT, "waiting")
        except Exception as exc:
            log.exception("sweep failed: %s", exc)
        stop.wait(config.CRAWL_INTERVAL)


def process_one(doc):
    """Extract claims from one queued document and save them."""
    source = {
        "url": doc.get("url"), "title": doc.get("title"),
        "outlet": doc.get("outlet"), "published": doc.get("published"),
    }
    claims = extract.claims_from(doc)
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
