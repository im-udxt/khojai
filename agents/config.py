import logging
import os
import threading

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# httpx logs a line for every request. With one feed that was fine. With
# dozens of feeds, topic searches and listing pages it buries everything
# this project actually says, so it is raised to warnings only.
for noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b-instruct")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "150"))
# Longest gap between tries when the model keeps failing. Without a cap
# on the wait, a wedged model is retried every fifteen seconds forever.
#
# This must stay well under the model's keep alive. At 300 seconds it matched
# it exactly, so the model unloaded between every retry, each retry paid the
# reload and timed out, and the backoff kept the loop alive indefinitely.
WORKER_MAX_BACKOFF = int(os.environ.get("WORKER_MAX_BACKOFF", "90"))
# How long Ollama holds the model in memory after a request. Loading it costs
# about fifty seconds here, so it is held rather than reloaded.
LLM_KEEP_ALIVE = os.environ.get("LLM_KEEP_ALIVE", "30m")
# Loading is slower than answering, so warming gets its own longer allowance.
LLM_LOAD_TIMEOUT = float(os.environ.get("LLM_LOAD_TIMEOUT", "300"))
LLM_CONTEXT = int(os.environ.get("LLM_CONTEXT", "8192"))
LLM_DAILY_LIMIT = int(os.environ.get("LLM_DAILY_LIMIT", "0"))

ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "/archive")
CRAWL_INTERVAL = int(os.environ.get("CRAWL_INTERVAL_SECONDS", "180"))
# Measured from the start of one sweep to the start of the next, so a slow
# sweep does not stretch the cycle. This is the floor between sweeps.
CRAWL_MIN_GAP = int(os.environ.get("CRAWL_MIN_GAP_SECONDS", "20"))
# How many documents a sweep looks at. Looking is one Redis lookup, so this
# is wide enough to reach every source. What it must never do is cut the
# source list short, which is what happened when it was 300.
MAX_DOCS_PER_SWEEP = int(os.environ.get("MAX_DOCS_PER_SWEEP", "2500"))
# How many new bodies a sweep fetches. This is the expensive number: each
# one is a request to somebody else's server at one per second.
MAX_FETCH_PER_SWEEP = int(os.environ.get("MAX_FETCH_PER_SWEEP", "120"))
EXTRACT_MIN_CHARS = int(os.environ.get("EXTRACT_MIN_CHARS", "280"))
# Second model pass over each claim. Off by default: with a 3B model it
# dropped correct claims as often as it caught wrong ones. Worth trying
# again on a larger model.
VERIFY_CLAIMS = os.environ.get("VERIFY_CLAIMS", "false").lower() == "true"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_USER = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

USER_AGENT = "KhojAI/2.0 (public data research)"
REQUEST_DELAY = 1.0

_last_hit = {}
_net_lock = threading.Lock()


def is_public_url(url):
    """Reject anything that points back inside the network.

    The crawler follows links that come from feeds and search results, which
    are outside our control. Without this check a crafted link could make the
    crawler read the database admin page, the model server, or a cloud
    metadata address, and store the response.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = parts.hostname
        if not host:
            return False
        if host.lower() in ("localhost", "metadata", "metadata.google.internal"):
            return False
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False


def polite_get(url, timeout=25.0, check_public=False, **kw):
    """One request per second per host, with an honest user agent.

    Pass check_public=True for any address that came from outside.
    """
    import time
    from urllib.parse import urlparse

    import httpx

    if check_public and not is_public_url(url):
        raise ValueError("address is not a public host")

    host = urlparse(url).netloc.lower()
    with _net_lock:
        wait = REQUEST_DELAY - (time.time() - _last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)

    follow = kw.pop("follow_redirects", True)
    if check_public and follow:
        # Follow redirects by hand so each hop is checked too. A public URL
        # can redirect to an internal one.
        current = url
        for _ in range(4):
            resp = httpx.get(current, timeout=timeout, headers=headers,
                             follow_redirects=False, **kw)
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp
            target = resp.headers.get("location", "")
            if not target:
                return resp
            current = str(httpx.URL(current).join(target))
            if not is_public_url(current):
                raise ValueError("redirect points at a private address")
        return resp

    return httpx.get(url, timeout=timeout, headers=headers,
                     follow_redirects=follow, **kw)
