"""Service health, written to Redis for the API and the status page."""
import json
import logging
import time

import config
import db
import extract

log = logging.getLogger("khoj.health")


def check():
    services = {}

    try:
        db.query("RETURN 1 AS ok")
        services["graph"] = {"state": "up", "note": "Neo4j"}
    except Exception as exc:
        services["graph"] = {"state": "down", "note": str(exc)[:120]}

    try:
        db.rds().ping()
        services["queue"] = {"state": "up", "note": "Redis"}
    except Exception as exc:
        services["queue"] = {"state": "down", "note": str(exc)[:120]}

    if extract.model_ready():
        services["model"] = {"state": "up", "note": config.LLM_MODEL}
    else:
        services["model"] = {"state": "down",
                             "note": f"{config.LLM_MODEL} not reachable at {config.OLLAMA_URL}"}

    services["crawler"] = {"state": "up", "note": f"every {config.CRAWL_INTERVAL}s"}

    try:
        pending = db.rds().llen("khoj:queue") + db.rds().llen("khoj:queue:priority")
    except Exception:
        pending = 0

    down = [k for k, v in services.items() if v["state"] != "up"]
    return {
        "epoch": time.time(),
        "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "services": services,
        "queue_depth": pending,
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
