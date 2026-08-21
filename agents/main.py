"""Entry point. Starts the crawler, the model worker, health checks and the bot."""
import asyncio
import logging
import signal
import sys
import threading
import time

import config
import db
import health
import merge
import metrics
import pipeline
import sources
import telegram_bot

log = logging.getLogger("khoj.main")


def markets_loop(stop, interval=300):
    """Refresh the small market strip shown on the site."""
    import json
    while not stop.is_set():
        try:
            db.rds().set("khoj:markets",
                         json.dumps({"quotes": sources.market_quotes()}), ex=1800)
        except Exception as exc:
            log.warning("market refresh failed: %s", str(exc)[:100])
        stop.wait(interval)


def wait_for_graph(attempts=40):
    for i in range(attempts):
        try:
            db.query("RETURN 1 AS ok")
            return True
        except Exception as exc:
            log.info("waiting for the graph (%d/%d): %s", i + 1, attempts, str(exc)[:80])
            time.sleep(5)
    return False


def main():
    if not wait_for_graph():
        log.error("graph never came up, exiting so the container restarts")
        sys.exit(1)

    db.ensure_schema()
    health.publish()
    metrics.publish()
    db.activity("system", "started")

    stop = threading.Event()
    threads = [
        threading.Thread(target=health.loop, args=(stop,), name="health", daemon=True),
        threading.Thread(target=pipeline.crawl_loop, args=(stop,), name="crawler", daemon=True),
        threading.Thread(target=pipeline.worker_loop, args=(stop,), name="worker", daemon=True),
        threading.Thread(target=markets_loop, args=(stop,), name="markets", daemon=True),
        threading.Thread(target=metrics.loop, args=(stop,), name="metrics", daemon=True),
        threading.Thread(target=merge.loop, args=(stop,), name="merge", daemon=True),
    ]
    for t in threads:
        t.start()
    log.info("crawler, worker, health, metrics and merge threads running")

    def shutdown(signum, frame):
        log.info("shutting down")
        stop.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Collection must survive anything the bot does. If the loop ever exits,
    # hold the process open so the crawler and worker threads keep going.
    try:
        asyncio.run(telegram_bot.run())
    except Exception as exc:
        log.error("telegram loop ended, collection continues: %s", str(exc)[:160])
    while not stop.is_set():
        time.sleep(60)


if __name__ == "__main__":
    main()
