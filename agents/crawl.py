"""Walking sites that have no feed.

Most of the useful record in India is not in an RSS feed. Court cause lists,
tender notices, press releases from a police headquarters and the dataset
index on data.gov.in are ordinary web pages with a list of links on them.
This module treats such a page the way a person would: open it, look at the
links, follow the ones that look like documents, and stop.

Two rules keep this from being rude. Every host is asked for its robots file
first and a refusal is obeyed, and no host is touched more than once a second.
"""
import logging
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import config
import db

log = logging.getLogger("khoj.crawl")

ROBOTS_TTL = 86400
# Anything that is plainly not a document. Checked before a request is made.
# Documents we cannot read as text. Court judgments are mostly PDF, so a
# large part of the record is out of reach until there is a PDF reader here.
SKIP_EXT = re.compile(
    r"\.(jpg|jpeg|png|gif|svg|webp|ico|css|js|zip|exe|mp4|mp3|woff2?|ttf|"
    r"pdf|doc|docx|xls|xlsx|ppt|pptx)$",
    re.IGNORECASE)
SKIP_HREF = re.compile(
    r"^(#|mailto:|tel:|javascript:|data:)", re.IGNORECASE)
LINK_RE = re.compile(r'<a\s[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                     re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# Redis holds the robots file between runs. This dict holds it between links
# on one page, so a listing page with forty links costs one robots request
# even if Redis is unavailable.
_robots_memo = {}


def _robots_text(host_root):
    """Fetch and cache one robots file. An unreachable file means no rules."""
    if host_root in _robots_memo:
        return _robots_memo[host_root]
    key = f"khoj:robots:{host_root}"
    try:
        cached = db.rds().get(key)
        if cached is not None:
            _robots_memo[host_root] = cached
            return cached
    except Exception:
        pass
    text = ""
    try:
        resp = config.polite_get(f"{host_root}/robots.txt", timeout=10,
                                 check_public=True)
        if resp.status_code == 200 and len(resp.text) < 200000:
            text = resp.text
    except Exception as exc:
        log.debug("no robots file for %s: %s", host_root, str(exc)[:60])
    try:
        db.rds().set(key, text, ex=ROBOTS_TTL)
    except Exception:
        pass
    if len(_robots_memo) > 200:
        _robots_memo.clear()
    _robots_memo[host_root] = text
    return text


def allowed(url):
    """True when the site's robots file permits us to read this address."""
    try:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        root = f"{parts.scheme}://{parts.netloc}"
        text = _robots_text(root)
        if not text.strip():
            return True
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return parser.can_fetch(config.USER_AGENT, url)
    except Exception:
        # A robots file we cannot parse is not a reason to assume permission
        # was refused, but it is a reason to log it.
        log.debug("robots check failed for %s", url[:80])
        return True


def _same_site(a, b):
    """Compare the last two labels of the host, so a subdomain still counts."""
    try:
        ha = urlparse(a).netloc.lower().split(":")[0].split(".")
        hb = urlparse(b).netloc.lower().split(":")[0].split(".")
        return ha[-2:] == hb[-2:]
    except Exception:
        return False


def links_on(page_url, html, pattern=None, same_site_only=True):
    """Every link on a page that could be a document, with its anchor text."""
    found, seen = [], set()
    match = re.compile(pattern, re.IGNORECASE) if pattern else None
    for href, label in LINK_RE.findall(html or ""):
        href = href.strip()
        if not href or SKIP_HREF.match(href):
            continue
        url = urljoin(page_url, href).split("#")[0]
        if url in seen or SKIP_EXT.search(urlparse(url).path):
            continue
        if same_site_only and not _same_site(page_url, url):
            continue
        if match and not match.search(url):
            continue
        seen.add(url)
        text = WS_RE.sub(" ", TAG_RE.sub(" ", label)).strip()
        found.append({"url": url, "text": text[:300]})
    return found


def walk(site, limit=40):
    """Read one listing page and return the documents linked from it.

    site is (id, display name, listing url, link pattern, tier). Only the
    listing page is fetched here. The body of each document is fetched later
    by the same code that handles feed items, so nothing is read twice.
    """
    site_id, name, url, pattern, tier = site
    if not allowed(url):
        log.info("%s asks us not to read %s", name, url)
        note(site_id, 0, "robots file says no")
        return []
    try:
        resp = config.polite_get(url, timeout=25, check_public=True)
        if resp.status_code != 200:
            note(site_id, 0, f"returned {resp.status_code}")
            return []
        html = resp.text
    except Exception as exc:
        note(site_id, 0, str(exc)[:70])
        return []

    docs = []
    for link in links_on(url, html, pattern):
        if len(docs) >= limit:
            break
        title = link["text"]
        # Menu labels are short: "Press Release", "Orders", "Home". Real
        # document titles on these sites run well past this. Checking the
        # length of the link text is what keeps a page of navigation from
        # arriving as twenty documents.
        if len(title) < 25:
            continue
        if not allowed(link["url"]):
            continue
        docs.append({
            "url": link["url"],
            "title": title,
            "text": "",
            "outlet": name,
            "outlet_id": site_id,
            "tier": tier,
            "published": "",
            "via": "site",
        })
    note(site_id, len(docs), "ok" if docs else "no document links found")
    return docs


def note(source_id, count, detail=""):
    """Record what a source produced, so a dead source is visible."""
    try:
        db.rds().hset("khoj:source:health", source_id, f"{int(time.time())}|{count}|{detail}")
    except Exception:
        pass


def source_health():
    """What every source did the last time it was tried."""
    out = []
    try:
        raw = db.rds().hgetall("khoj:source:health") or {}
    except Exception:
        return out
    for source_id, value in raw.items():
        parts = (value or "").split("|", 2)
        try:
            when = int(parts[0])
        except (ValueError, IndexError):
            continue
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        out.append({
            "source": source_id,
            "items": count,
            "detail": parts[2] if len(parts) > 2 else "",
            "age_seconds": int(time.time() - when),
        })
    out.sort(key=lambda r: (r["items"], -r["age_seconds"]))
    return out
