"""Where documents come from.

The feed list is deliberately shorter than the first version. Dead and
rate limited feeds were removed. Every entry here was checked to return items.
"""
import logging
import re

import feedparser

import config

log = logging.getLogger("khoj.sources")

# outlet id, display name, url, tier (1 is the most reliable for sourcing)
FEEDS = [
    ("thehindu", "The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", 1),
    ("indianexpress", "Indian Express", "https://indianexpress.com/section/india/feed/", 1),
    ("thewire", "The Wire", "https://thewire.in/rss", 1),
    ("scroll", "Scroll.in", "https://scroll.in/feed", 1),
    ("livemint", "LiveMint", "https://www.livemint.com/rss/news", 1),
    ("bstandard", "Business Standard", "https://www.business-standard.com/rss/latest.rss", 1),
    ("ndtv", "NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories", 2),
    ("hindustantimes", "Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml", 2),
    ("theprint", "ThePrint", "https://theprint.in/feed/", 2),
    ("thequint", "The Quint", "https://www.thequint.com/stories.rss", 2),
    ("newslaundry", "Newslaundry", "https://www.newslaundry.com/feed", 2),
    ("caravan", "The Caravan", "https://caravanmagazine.in/feed", 2),
    ("economictimes", "Economic Times", "https://economictimes.indiatimes.com/rssfeedsdefault.cms", 2),
    ("moneycontrol", "Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml", 2),
    ("thefederal", "The Federal", "https://thefederal.com/feeds/news.xml", 2),
    ("newsminute", "The News Minute", "https://www.thenewsminute.com/feed", 2),
    ("livelaw", "LiveLaw", "https://www.livelaw.in/rss/top-stories", 1),
    ("barandbench", "Bar and Bench", "https://www.barandbench.com/feed", 1),
    ("indiaspend", "IndiaSpend", "https://www.indiaspend.com/feed", 1),
    ("article14", "Article 14", "https://article-14.com/rss.xml", 1),
    ("downtoearth", "Down To Earth", "https://www.downtoearth.org.in/rss/all", 2),
    ("pib", "Press Information Bureau", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", 1),
    ("rbi", "Reserve Bank of India", "https://rbi.org.in/pressreleases_rss.xml", 1),
    ("sebi", "SEBI", "https://www.sebi.gov.in/sebirss.xml", 1),
    ("reuters_india", "Reuters India", "https://news.google.com/rss/search?q=when:1d+allinurl:reuters.com+india&hl=en-IN&gl=IN&ceid=IN:en", 1),
    ("bbc_india", "BBC India", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", 1),
]

# Market lines shown on the site. Kept short on purpose.
MARKETS = [
    ("^NSEI", "Nifty 50", "index"),
    ("^BSESN", "Sensex", "index"),
    ("INR=X", "USD/INR", "currency"),
    ("GC=F", "Gold", "commodity"),
    ("BZ=F", "Brent Crude", "commodity"),
    ("BTC-USD", "Bitcoin", "crypto"),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(html):
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        text = soup.get_text(" ")
    except Exception:
        text = TAG_RE.sub(" ", html)
    return WS_RE.sub(" ", text).strip()


def read_feeds(feeds=None):
    """Pull every feed once and return document dicts."""
    docs = []
    for outlet_id, name, url, tier in (feeds or FEEDS):
        try:
            parsed = feedparser.parse(url, agent=config.USER_AGENT)
            for item in parsed.entries[:60]:
                link = getattr(item, "link", "")
                title = getattr(item, "title", "")
                if not link or not title:
                    continue
                summary = strip_html(getattr(item, "summary", ""))
                docs.append({
                    "url": link.split("?utm")[0],
                    "title": title.strip(),
                    "text": summary,
                    "outlet": name,
                    "outlet_id": outlet_id,
                    "tier": tier,
                    "published": getattr(item, "published", "") or getattr(item, "updated", ""),
                })
        except Exception as exc:
            log.warning("feed failed %s: %s", outlet_id, str(exc)[:100])
    return docs


def fetch_article(url):
    """Get the readable body of an article. Returns empty string on failure."""
    try:
        resp = config.polite_get(url, timeout=20)
        if resp.status_code != 200:
            return ""
        text = strip_html(resp.text)
        return text[:14000]
    except Exception:
        return ""


def search_news(query, limit=30):
    """On demand news search used by investigations."""
    from urllib.parse import quote_plus
    url = ("https://news.google.com/rss/search?q="
           f"{quote_plus(query)}+when:180d&hl=en-IN&gl=IN&ceid=IN:en")
    docs = []
    try:
        parsed = feedparser.parse(url, agent=config.USER_AGENT)
        for item in parsed.entries[:limit]:
            link = getattr(item, "link", "")
            title = getattr(item, "title", "")
            if not link or not title:
                continue
            outlet = title.rsplit(" - ", 1)[-1] if " - " in title else "Google News"
            docs.append({
                "url": link, "title": title.rsplit(" - ", 1)[0].strip(),
                "text": strip_html(getattr(item, "summary", "")),
                "outlet": outlet, "outlet_id": "search", "tier": 2,
                "published": getattr(item, "published", ""),
            })
    except Exception as exc:
        log.warning("news search failed: %s", str(exc)[:120])
    return docs


def market_quotes():
    """Quotes from the public Yahoo Finance endpoint. No API key needed."""
    symbols = ",".join(s for s, _, _ in MARKETS)
    out = []
    try:
        resp = config.polite_get(
            "https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + symbols,
            timeout=15)
        data = resp.json().get("quoteResponse", {}).get("result", [])
        by_symbol = {q.get("symbol"): q for q in data}
    except Exception as exc:
        log.warning("market quotes failed: %s", str(exc)[:100])
        by_symbol = {}
    for symbol, label, kind in MARKETS:
        q = by_symbol.get(symbol, {})
        out.append({
            "symbol": symbol, "label": label, "kind": kind,
            "price": q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
        })
    return out
