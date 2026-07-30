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
import pipeline
import telegram_bot

log = logging.getLogger("khoj.main")


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
    db.activity("system", "started")

    stop = threading.Event()
    threads = [
        threading.Thread(target=health.loop, args=(stop,), name="health", daemon=True),
        threading.Thread(target=pipeline.crawl_loop, args=(stop,), name="crawler", daemon=True),
        threading.Thread(target=pipeline.worker_loop, args=(stop,), name="worker", daemon=True),
    ]
    for t in threads:
        t.start()
    log.info("crawler, worker and health checks running")

    def shutdown(signum, frame):
        log.info("shutting down")
        stop.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    asyncio.run(telegram_bot.run())


if __name__ == "__main__":
    main()
