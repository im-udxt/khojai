"""Where documents come from.

Three kinds of source, in the order they were added.

Feeds are the cheapest and most reliable, so they come first. Topic searches
sit on top of them to reach reporting the section feeds miss. Listing pages
are last and are the only ones that need a crawler, because courts, police
headquarters and the data portal publish to plain HTML pages with no feed.

Not every entry here will work. Government sites go down, change paths and
sometimes refuse a request that is not a browser. Rather than pretend
otherwise, every source records what it returned the last time it was tried
and the status page shows which ones are producing nothing.
"""
import logging
import os
import re

import feedparser

import config

log = logging.getLogger("khoj.sources")

# outlet id, display name, url, tier (1 is the most reliable for sourcing)
NEWS_FEEDS = [
    ("thehindu", "The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", 1),
    ("thehindu_biz", "The Hindu Business", "https://www.thehindu.com/business/feeder/default.rss", 1),
    ("indianexpress", "Indian Express", "https://indianexpress.com/section/india/feed/", 1),
    ("ie_cities", "Indian Express Cities", "https://indianexpress.com/section/cities/feed/", 2),
    ("ie_business", "Indian Express Business", "https://indianexpress.com/section/business/feed/", 2),
    ("livemint", "LiveMint", "https://www.livemint.com/rss/news", 1),
    ("bstandard", "Business Standard", "https://www.business-standard.com/rss/latest.rss", 1),
    ("businessline", "BusinessLine", "https://www.thehindubusinessline.com/feeder/default.rss", 2),
    ("ndtv", "NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories", 2),
    ("hindustantimes", "Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml", 2),
    ("thequint", "The Quint", "https://www.thequint.com/stories.rss", 2),
    ("newslaundry", "Newslaundry", "https://www.newslaundry.com/feed", 2),
    ("frontline", "Frontline", "https://frontline.thehindu.com/feeder/default.rss", 1),
    ("economictimes", "Economic Times", "https://economictimes.indiatimes.com/rssfeedsdefault.cms", 2),
    ("moneycontrol", "Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml", 2),
    ("newsminute", "The News Minute", "https://www.thenewsminute.com/feed", 2),
    ("toi", "Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", 2),
    ("barandbench", "Bar and Bench", "https://www.barandbench.com/feed", 1),
    ("mongabay", "Mongabay India", "https://india.mongabay.com/feed/", 2),
    ("pib", "Press Information Bureau", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", 1),
    ("rbi", "Reserve Bank of India", "https://rbi.org.in/pressreleases_rss.xml", 1),
    ("sebi", "SEBI", "https://www.sebi.gov.in/sebirss.xml", 1),
    ("bbc_india", "BBC India", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", 1),
]


# These outlets stopped answering a plain feed request. Four return a bot
# page with a 200, two redirect into something that is not XML, and two are
# simply 404 now. Their reporting is still indexed, so they are read through
# a search scoped to the outlet instead. It is a worse source than a feed,
# because the body still has to be fetched from a site that may refuse, but
# it is much better than losing the outlet.
VIA_SEARCH = [
    ("thewire", "The Wire", "site:thewire.in", 1),
    ("scroll", "Scroll.in", "site:scroll.in", 1),
    ("theprint", "ThePrint", "site:theprint.in", 2),
    ("livelaw", "LiveLaw", "site:livelaw.in", 1),
    ("caravan", "The Caravan", "site:caravanmagazine.in", 2),
    ("article14", "Article 14", "site:article-14.com", 1),
    ("firstpost", "Firstpost", "site:firstpost.com", 2),
    ("reuters_india", "Reuters India", "reuters india", 1),
    ("financialexpress", "Financial Express", "site:financialexpress.com", 2),
    ("thefederal", "The Federal", "site:thefederal.com", 2),
    ("deccanherald", "Deccan Herald", "site:deccanherald.com", 2),
    ("telegraph", "Telegraph India", "site:telegraphindia.com", 2),
    ("tnie", "New Indian Express", "site:newindianexpress.com", 2),
    ("indiaspend", "IndiaSpend", "site:indiaspend.com", 1),
    ("downtoearth", "Down To Earth", "site:downtoearth.org.in", 2),
]


def google_news(query, days=3):
    """A search feed. Google still serves these without a key or a cookie."""
    from urllib.parse import quote_plus
    return ("https://news.google.com/rss/search?q="
            f"{quote_plus(query)}+when:{days}d&hl=en-IN&gl=IN&ceid=IN:en")


# Section feeds carry whatever an outlet chose to promote. These ask the
# question directly instead, which is how court and enforcement reporting
# gets in at all, since almost none of it publishes a feed.
TOPICS = [
    ("t_sc", "Supreme Court coverage", "Supreme Court India judgment OR verdict", 1),
    ("t_hc", "High Court coverage", "High Court India order OR petition", 1),
    ("t_ed", "Enforcement Directorate coverage", "Enforcement Directorate attachment OR summons", 1),
    ("t_cbi", "CBI coverage", "CBI FIR OR chargesheet OR raid India", 1),
    ("t_cag", "CAG coverage", "CAG audit report irregularities", 1),
    ("t_tender", "Contract and tender coverage", "tender awarded contract crore government India", 1),
    ("t_funding", "Political funding coverage", "political party donation OR electoral bonds funding", 1),
    ("t_party", "Party organisation coverage", "party appoints OR expels state unit president India", 2),
    ("t_assets", "Candidate declaration coverage", "MLA OR MP affidavit assets declared", 2),
    ("t_sebi", "Market regulator coverage", "SEBI order penalty OR ban company", 1),
    ("t_nclt", "Insolvency coverage", "NCLT insolvency resolution creditors", 2),
    ("t_it", "Income tax coverage", "Income Tax department survey OR raid premises", 2),
    ("t_lokayukta", "State vigilance coverage", "Lokayukta OR vigilance bureau case registered", 2),
    ("t_rti", "Right to information coverage", "RTI reply revealed government", 2),
    ("t_cabinet", "Cabinet decision coverage", "cabinet approves project crore India", 2),
    ("t_land", "Land and mining coverage", "land allotment OR mining lease granted India", 2),
    ("t_scam", "Fraud coverage", "scam OR fraud probe crore India arrested", 1),
]

# Listing pages with no feed. These are read by crawl.walk, which asks each
# host for its robots file first.
#
# Every entry below was tried before it was added, and the pattern is the one
# that actually matches document links on that page rather than its menu.
# These were tried and left out, so nobody has to find out the hard way:
#
#   data.gov.in            its robots file refuses us, so we do not read it
#   Competition Commission its certificate chain does not verify
#   Delhi Police           its certificate has expired
#   Election Commission    the list is drawn by script, so the page has no links
#   Enforcement Directorate, Home Affairs, NIA, ADR, Corporate Affairs
#                          every path tried returns 404, the sites moved
#   SEBI enforcement       returns 403 to anything that is not a browser
#
# Court judgments are mostly PDF and are skipped for now, which is the largest
# gap in what this reads.
# id, display name, listing url, pattern a link must match, tier
SITES = [
    ("s_cbi", "Central Bureau of Investigation", "https://cbi.gov.in/press-releases",
     r"press-detail", 1),
    ("s_pib", "Press Information Bureau", "https://pib.gov.in/allRel.aspx",
     r"PRID|PressRelease|Pressrelease", 1),
    ("s_nhrc", "National Human Rights Commission", "https://nhrc.nic.in/media/press-release",
     r"/media/press-release/", 1),
    ("s_prs", "PRS Legislative Research", "https://prsindia.org/billtrack",
     r"/billtrack/|/bills/", 1),
    ("s_scobserver", "Supreme Court Observer", "https://www.scobserver.in/journal/",
     r"/journal/|/reports/|/cases/", 1),
    ("s_cag", "Comptroller and Auditor General", "https://cag.gov.in/en/press-release",
     r"/press-release/|/audit-report/", 1),
    ("s_ngt", "National Green Tribunal", "https://www.greentribunal.gov.in/news-update",
     r"/news-update/|judgment|order", 2),
    ("s_nclt", "National Company Law Tribunal", "https://nclt.gov.in/order-judgement-date-wise",
     r"/order|/judgement", 2),
    ("s_sansad", "Parliament of India", "https://sansad.in/ls",
     r"question|/ls/[a-z]", 2),
    ("s_mumbaipolice", "Mumbai Police", "https://mumbaipolice.gov.in/PressRelease",
     r"PressRelease|Press", 2),
]

# How many listing pages to walk in one sweep. They are slower and less
# reliable than feeds, so they are taken a few at a time in rotation instead
# of all at once every few minutes.
SITES_PER_SWEEP = int(os.environ.get("SITES_PER_SWEEP", "5"))

# Older callers still import FEEDS.
FEEDS = NEWS_FEEDS


def topic_feeds():
    """The topic searches in the same shape as an ordinary feed entry."""
    return [(tid, name, google_news(query), tier)
            for tid, name, query, tier in TOPICS]


def outlet_search_feeds():
    """Outlets that have to be reached through a search rather than a feed."""
    return [(oid, name, google_news(query), tier)
            for oid, name, query, tier in VIA_SEARCH]


def all_feeds():
    return NEWS_FEEDS + outlet_search_feeds() + topic_feeds()


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
    """Pull every feed once and return document dicts.

    What each feed returned is recorded, so a feed that has quietly died
    shows up on the status page instead of just contributing nothing.
    """
    import crawl

    docs = []
    for outlet_id, name, url, tier in (feeds if feeds is not None else all_feeds()):
        found = 0
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
                    "via": "feed",
                })
                found += 1
            crawl.note(outlet_id, found, "ok" if found else "feed returned nothing")
        except Exception as exc:
            crawl.note(outlet_id, 0, str(exc)[:70])
            log.warning("feed failed %s: %s", outlet_id, str(exc)[:100])
    return docs


def read_sites(count=None, sites=None):
    """Walk a few listing pages, taking a different few each sweep.

    A listing page costs a request and a parse whether or not anything on it
    is new, so they are rotated rather than all read every time.
    """
    import crawl
    import db

    pool = sites if sites is not None else SITES
    if not pool:
        return []
    count = count or SITES_PER_SWEEP
    try:
        cursor = int(db.rds().incrby("khoj:site:cursor", count)) - count
    except Exception:
        cursor = 0

    docs = []
    for step in range(min(count, len(pool))):
        site = pool[(cursor + step) % len(pool)]
        try:
            docs.extend(crawl.walk(site))
        except Exception as exc:
            log.warning("site walk failed %s: %s", site[0], str(exc)[:100])
            crawl.note(site[0], 0, str(exc)[:70])
    return docs


def fetch_article(url):
    """Get the readable body of an article. Returns empty string on failure.

    The address came from a feed or a search result, so it is checked against
    private ranges before anything is requested.
    """
    try:
        resp = config.polite_get(url, timeout=20, check_public=True)
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
    """Quotes from Yahoo's chart endpoint.

    The older quote endpoint started requiring a session cookie and returns
    401, so this uses the chart endpoint, which is still open.
    """
    from urllib.parse import quote

    out = []
    for symbol, label, kind in MARKETS:
        price = change = None
        try:
            resp = config.polite_get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
                "?interval=1d&range=5d",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; KhojAI/2.0)"})
            if resp.status_code == 200:
                meta = resp.json()["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice")
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                if price and prev:
                    change = round((price - prev) / prev * 100, 2)
        except Exception as exc:
            log.debug("quote failed for %s: %s", symbol, str(exc)[:80])
        out.append({"symbol": symbol, "label": label, "kind": kind,
                    "price": price, "change_pct": change})
    return out
