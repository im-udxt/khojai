"""Service health, written to Redis for the API and the status page.

Reachability is not liveness. An earlier version asked Ollama whether it was
listening and reported everything healthy while the worker was dead and the
queue grew to thousands. Every moving part now reports a heartbeat and health
is judged on progress, not on whether a port answers.
"""
import json
import logging
import time

import config
import db
import extract

log = logging.getLogger("khoj.health")

WORKER_BEAT = "khoj:beat:worker"
CRAWLER_BEAT = "khoj:beat:crawler"
WORKER_FAILS = "khoj:worker:fails"
STALE_WORKER = 300
STALE_CRAWLER_FACTOR = 3


def beat(key, detail=""):
    try:
        db.rds().set(key, json.dumps({"at": time.time(), "detail": detail}), ex=3600)
    except Exception:
        pass


def _read_beat(key):
    try:
        raw = db.rds().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _age(beat_data):
    return time.time() - beat_data["at"] if beat_data else None


def check():
    services = {}
    rds = None

    try:
        db.query("RETURN 1 AS ok")
        services["graph"] = {"state": "up", "note": "Neo4j"}
    except Exception as exc:
        services["graph"] = {"state": "down", "note": str(exc)[:120]}

    try:
        rds = db.rds()
        rds.ping()
        services["queue"] = {"state": "up", "note": "Redis"}
    except Exception as exc:
        services["queue"] = {"state": "down", "note": str(exc)[:120]}

    reachable = extract.model_ready()
    fails = 0
    try:
        fails = int(rds.get(WORKER_FAILS) or 0) if rds else 0
    except Exception:
        pass
    if not reachable:
        services["model"] = {"state": "down",
                             "note": f"{config.LLM_MODEL} not answering at {config.OLLAMA_URL}"}
    elif fails >= 3:
        services["model"] = {"state": "down",
                             "note": f"answering but {fails} extractions in a row failed"}
    else:
        services["model"] = {"state": "up", "note": config.LLM_MODEL}

    pending = 0
    try:
        pending = rds.llen("khoj:queue") + rds.llen("khoj:queue:priority") if rds else 0
    except Exception:
        pass

    worker = _read_beat(WORKER_BEAT)
    age = _age(worker)
    if age is None:
        services["worker"] = {"state": "down", "note": "never reported in"}
    elif age > STALE_WORKER:
        services["worker"] = {"state": "down",
                              "note": f"no sign of life for {int(age)}s, {pending} waiting"}
    elif pending > 500 and (worker or {}).get("detail") == "idle":
        services["worker"] = {"state": "down",
                              "note": f"idle while {pending} articles wait"}
    else:
        services["worker"] = {"state": "up",
                              "note": (worker or {}).get("detail") or "reading"}

    crawler = _read_beat(CRAWLER_BEAT)
    c_age = _age(crawler)
    limit = config.CRAWL_INTERVAL * STALE_CRAWLER_FACTOR
    if c_age is None:
        services["crawler"] = {"state": "down", "note": "never reported in"}
    elif c_age > limit:
        services["crawler"] = {"state": "down", "note": f"last swept {int(c_age)}s ago"}
    else:
        services["crawler"] = {"state": "up", "note": f"every {config.CRAWL_INTERVAL}s"}

    day = time.strftime("%Y%m%d", time.gmtime())
    processed = 0
    try:
        processed = int(rds.get(f"khoj:stat:{day}:processed") or 0) if rds else 0
    except Exception:
        pass

    down = [k for k, v in services.items() if v["state"] != "up"]
    return {
        "epoch": time.time(),
        "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "services": services,
        "queue_depth": pending,
        "processed_today": processed,
        "healthy": not down,
        "down": down,
    }


def publish():
    snapshot = check()
    try:
        db.rds().set("khoj:health", json.dumps(snapshot), ex=300)
    except Exception:
        pass
    return snapshot


def loop(stop, interval=30):
    while not stop.is_set():
        try:
            snapshot = publish()
            if snapshot["down"]:
                log.warning("down: %s", ", ".join(snapshot["down"]))
        except Exception as exc:
            log.error("health check failed: %s", exc)
        stop.wait(interval)
