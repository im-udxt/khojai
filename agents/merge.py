"""Folding duplicate names into one node.

The same organisation arrives as "Adani Ports", "Adani Ports and Special
Economic Zone" and "Adani Ports Ltd". Canonicalisation catches the spelling
differences it can see in one string. It cannot catch the ones that only
show up when two stored names are put side by side.

Merging is destructive, so the rules are split in two. A small set of shapes
is safe enough to merge without asking, and everything else is written to a
review list instead of being guessed at. Every automatic merge is recorded
with the reason, so a wrong one can be found later.
"""
import json
import logging
import re
import time

import db
import entities

log = logging.getLogger("khoj.merge")

MERGE_LOG = "khoj:merges"
REVIEW_KEY = "khoj:merge:review"
REJECT_KEY = "khoj:merge:rejected"

# Words that change what a thing is, not how it is spelled. If one name has
# them and the other does not, the two are not the same thing: "Adani" and
# "Adani Group" are a person and a company, and merging them would be wrong.
# The same trap catches "Supreme Court" against "Supreme Court Bar
# Association", which is a court and a body of lawyers.
BODY_WORDS = {
    "association", "federation", "trust", "foundation", "society",
    "institute", "academy", "university", "college", "school", "hospital",
    "wing", "cell", "chapter", "branch", "division", "subsidiary", "unit",
    "working", "youth", "mahila", "seva",
}
ROLE_WORDS = {
    "commissioner", "secretary", "director", "chairman", "chairperson",
    "governor", "judge", "justice", "officer", "spokesperson", "candidate",
    "mla", "mp", "ceo", "md", "founder", "owner", "leader",
}
KIND_WORDS = (entities.COMPANY_SUFFIXES | entities.GOVERNMENT_WORDS
              | entities.COURT_WORDS | entities.PARTY_WORDS
              | BODY_WORDS | ROLE_WORDS)

# What one name may have that the other does not, and still be folded without
# being asked about.
#
# This list used to work the other way round: fold unless the extra words are
# in a list of words known to change the meaning. That is the wrong direction
# and it did real damage. It folded "Nationalist Congress Party" into
# "Congress Party" and "Tamil Nadu Social Welfare" into "Tamil Nadu Finance",
# because no denylist can hold every word that matters. Naming the small set
# of words that genuinely do not matter is the only safe direction: anything
# outside it now goes to review instead.
#
# It is deliberately shorter than it could be. "Cabinet" and "chief" were on
# it once, which made "Karnataka cabinet" and "Karnataka" look like the same
# name. Merging cannot be undone, so a word only belongs here when it can
# never change which thing is being named.
FILLER = {"the", "of", "and", "for", "in", "on", "at",
          "shri", "smt", "sri", "sh", "mr", "mrs", "ms", "dr", "prof"}

# The same set is used to decide which words to ignore when comparing two
# names, so the two can never drift apart.
NOISE = FILLER


def is_filler(word):
    """A word that can differ between two spellings of the same name."""
    return word in FILLER or len(word) == 1


TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(key):
    return [t for t in TOKEN_RE.findall((key or "").lower()) if t]


def meaningful(key):
    return [t for t in tokens(key) if t not in NOISE]


def stem(word):
    """Crude singular form. Enough to see that industries and industry match."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def acronym_of(short, long_key):
    """True when the short key is the initials of the long one."""
    letters = "".join(tokens(short))
    initials = "".join(t[0] for t in meaningful(long_key))
    return len(letters) >= 3 and letters == initials


def compatible(type_a, type_b):
    """Two nodes can only merge if they are the same kind of thing.

    Topic is the label used when nothing more specific could be worked out,
    so it is allowed to merge into anything.
    """
    if type_a == type_b:
        return True
    return "Topic" in (type_a, type_b)


def judge(a, b):
    """Decide what to do with one candidate pair.

    Returns (action, reason) where action is auto, review or skip.
    """
    ka, kb = a["key"], b["key"]
    if ka == kb:
        return "skip", "same key"
    if not compatible(a.get("type"), b.get("type")):
        return "skip", "different kinds of name"

    ta, tb = set(meaningful(ka)), set(meaningful(kb))
    if not ta or not tb:
        return "skip", "nothing to compare"

    # Spacing only. "adani ports" against "adaniports".
    if ka.replace(" ", "") == kb.replace(" ", ""):
        return "auto", "same letters, different spacing"

    # The same words once titles and filler are removed, in any order.
    if ta == tb:
        return "auto", "the same words with different titles or order"

    # Singular against plural, on any number of words.
    if {stem(t) for t in ta} == {stem(t) for t in tb}:
        return "auto", "singular and plural of the same name"

    if acronym_of(ka, kb) or acronym_of(kb, ka):
        return "auto", "one is the initials of the other"

    # One name contains the other. Safe only when the extra words are filler.
    # If the extra words say what kind of thing it is, the two are different
    # things wearing similar names.
    small, large = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    if small < large:
        extra = large - small
        if len(small) == 1:
            # A single word inside a longer name is usually a family name or
            # a place, and is the shape that produces the worst mistakes.
            return "review", "one name is a single word inside the other"
        if all(is_filler(word) for word in extra):
            return "auto", "one name is the other with an initial or a title"
        return "review", "one name contains the other, with words that may matter"

    shared = len(ta & tb)
    union = len(ta | tb)
    if union and shared / union >= 0.6 and shared >= 2:
        return "review", "most words are shared"
    return "skip", "not close enough"


def candidates(rows, cap=4000):
    """Pairs worth judging, found through a shared uncommon word.

    Comparing every name against every other is quadratic and gets slow as
    the graph grows. Two names that are the same thing almost always share
    at least one distinctive word, so only those pairs are considered.
    """
    buckets = {}
    for row in rows:
        for token in set(meaningful(row["key"])):
            if len(token) < 3:
                continue
            buckets.setdefault(token, []).append(row)

    pairs, seen = [], set()
    for token, group in buckets.items():
        # A word shared by dozens of names is a common word, not a signature.
        if len(group) < 2 or len(group) > 25:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pair = tuple(sorted((a["uid"], b["uid"])))
                if pair in seen:
                    continue
                seen.add(pair)
                pairs.append((a, b))
                if len(pairs) >= cap:
                    return pairs
    return pairs


def _winner(a, b):
    """The node that survives: the one the record knows better."""
    if int(a.get("mentions") or 0) != int(b.get("mentions") or 0):
        return (a, b) if a["mentions"] > b["mentions"] else (b, a)
    if len(a["name"]) != len(b["name"]):
        return (a, b) if len(a["name"]) > len(b["name"]) else (b, a)
    return (a, b)


MOVE_OUT = """
MATCH (loser:Entity {uid:$loser})-[r:CLAIM]->(other:Entity)
MATCH (winner:Entity {uid:$winner})
WHERE other.uid <> $winner
MERGE (winner)-[n:CLAIM {relation:r.relation, source_url:r.source_url}]->(other)
ON CREATE SET n = properties(r)
DELETE r
"""

MOVE_IN = """
MATCH (other:Entity)-[r:CLAIM]->(loser:Entity {uid:$loser})
MATCH (winner:Entity {uid:$winner})
WHERE other.uid <> $winner
MERGE (other)-[n:CLAIM {relation:r.relation, source_url:r.source_url}]->(winner)
ON CREATE SET n = properties(r)
DELETE r
"""

MOVE_SOURCES = """
MATCH (loser:Entity {uid:$loser})-[c:CITED_IN]->(s:Source)
MATCH (winner:Entity {uid:$winner})
MERGE (winner)-[:CITED_IN]->(s)
DELETE c
"""

FOLD = """
MATCH (loser:Entity {uid:$loser}), (winner:Entity {uid:$winner})
SET winner.mentions = coalesce(winner.mentions,0) + coalesce(loser.mentions,0),
    winner.aliases = coalesce(winner.aliases, []) +
        [a IN coalesce(loser.aliases, [loser.name])
         WHERE NOT a IN coalesce(winner.aliases, [])],
    winner.type = CASE WHEN coalesce(winner.type,'Topic') = 'Topic'
                       AND coalesce(loser.type,'Topic') <> 'Topic'
                  THEN loser.type ELSE winner.type END,
    winner.first_seen = CASE WHEN loser.first_seen < winner.first_seen
                        THEN loser.first_seen ELSE winner.first_seen END
DETACH DELETE loser
"""


def apply_merge(winner, loser, reason, automatic=True):
    """Move everything from loser onto winner, then remove loser."""
    if winner["uid"] == loser["uid"]:
        return False
    try:
        for statement in (MOVE_OUT, MOVE_IN, MOVE_SOURCES, FOLD):
            db.query(statement, winner=winner["uid"], loser=loser["uid"])
    except Exception as exc:
        log.warning("merge failed for %s into %s: %s",
                    loser["name"], winner["name"], str(exc)[:120])
        return False

    record = {
        "ts": time.time(), "kept": winner["name"], "kept_uid": winner["uid"],
        "removed": loser["name"], "removed_uid": loser["uid"],
        "reason": reason, "automatic": automatic,
    }
    try:
        r = db.rds()
        pipe = r.pipeline()
        pipe.lpush(MERGE_LOG, json.dumps(record))
        pipe.ltrim(MERGE_LOG, 0, 499)
        pipe.execute()
    except Exception:
        pass
    db.stat("merged")
    db.activity("merge", f"{loser['name']} folded into {winner['name']} ({reason})")
    return True


def queue_review(a, b, reason):
    pair = "|".join(sorted((a["uid"], b["uid"])))
    try:
        r = db.rds()
        if r.sismember(REJECT_KEY, pair):
            return
        r.hset(REVIEW_KEY, pair, json.dumps({
            "pair": pair, "reason": reason, "ts": time.time(),
            "a": {"uid": a["uid"], "name": a["name"], "type": a.get("type"),
                  "mentions": a.get("mentions", 0)},
            "b": {"uid": b["uid"], "name": b["name"], "type": b.get("type"),
                  "mentions": b.get("mentions", 0)},
        }))
    except Exception:
        pass


def reviews():
    out = []
    try:
        raw = db.rds().hgetall(REVIEW_KEY) or {}
    except Exception:
        return out
    for value in raw.values():
        try:
            out.append(json.loads(value))
        except (ValueError, TypeError):
            continue
    out.sort(key=lambda r: -(r.get("ts") or 0))
    return out


def resolve(pair, accept):
    """Act on one reviewed pair. Returns a short message."""
    try:
        raw = db.rds().hget(REVIEW_KEY, pair)
    except Exception:
        raw = None
    if not raw:
        return "That pair is not waiting for review."
    item = json.loads(raw)
    db.rds().hdel(REVIEW_KEY, pair)
    if not accept:
        db.rds().sadd(REJECT_KEY, pair)
        return f"Left {item['a']['name']} and {item['b']['name']} separate."
    winner, loser = _winner(item["a"], item["b"])
    if apply_merge(winner, loser, item.get("reason", "approved by hand"), False):
        return f"Folded {loser['name']} into {winner['name']}."
    return "The merge did not go through. It has been logged."


def merges(limit=50):
    try:
        rows = db.rds().lrange(MERGE_LOG, 0, limit - 1)
        return [json.loads(r) for r in rows]
    except Exception:
        return []


def run(limit=3000):
    """One pass. Merges what is safe and queues the rest."""
    try:
        rows = db.query(
            "MATCH (e:Entity) RETURN e.uid AS uid, e.name AS name, e.key AS key, "
            "e.type AS type, coalesce(e.mentions,0) AS mentions "
            "ORDER BY mentions DESC LIMIT $limit", limit=limit)
    except Exception as exc:
        log.warning("could not read names to merge: %s", str(exc)[:100])
        return {"checked": 0, "merged": 0, "queued": 0}

    rows = [r for r in rows if r.get("key")]
    gone = set()
    merged = queued = 0
    for a, b in candidates(rows):
        if a["uid"] in gone or b["uid"] in gone:
            continue
        action, reason = judge(a, b)
        if action == "auto":
            winner, loser = _winner(a, b)
            if apply_merge(winner, loser, reason):
                gone.add(loser["uid"])
                merged += 1
        elif action == "review":
            queue_review(a, b, reason)
            queued += 1

    if merged or queued:
        log.info("merge pass: %d folded, %d waiting for review", merged, queued)
    return {"checked": len(rows), "merged": merged, "queued": queued}


def loop(stop, interval=1800):
    """Merging runs on its own clock. It is not on the path of a claim."""
    stop.wait(120)
    while not stop.is_set():
        try:
            result = run()
            if result["merged"]:
                db.activity("merge",
                            f"folded {result['merged']} duplicate names")
        except Exception as exc:
            log.error("merge pass failed: %s", str(exc)[:140])
        stop.wait(interval)
