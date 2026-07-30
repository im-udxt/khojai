import logging
import os
import threading

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b-instruct")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))
LLM_CONTEXT = int(os.environ.get("LLM_CONTEXT", "8192"))
LLM_DAILY_LIMIT = int(os.environ.get("LLM_DAILY_LIMIT", "0"))

ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "/archive")
CRAWL_INTERVAL = int(os.environ.get("CRAWL_INTERVAL_SECONDS", "180"))
MAX_DOCS_PER_SWEEP = int(os.environ.get("MAX_DOCS_PER_SWEEP", "400"))
EXTRACT_MIN_CHARS = int(os.environ.get("EXTRACT_MIN_CHARS", "280"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_USER = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

USER_AGENT = "KhojAI/2.0 (public data research)"
REQUEST_DELAY = 1.0

_last_hit = {}
_net_lock = threading.Lock()


def polite_get(url, timeout=25.0, **kw):
    """One request per second per host, with an honest user agent."""
    import time
    from urllib.parse import urlparse

    import httpx

    host = urlparse(url).netloc.lower()
    with _net_lock:
        wait = REQUEST_DELAY - (time.time() - _last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    return httpx.get(url, timeout=timeout, headers=headers,
                     follow_redirects=kw.pop("follow_redirects", True), **kw)
