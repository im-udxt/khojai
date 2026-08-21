"""Site walking: link extraction, robots, and the source lists.

    python tests/test_crawl.py
"""
import os
import sys, types

for name, attrs in [
    ("redis", {"Redis": type("R", (), {"from_url": staticmethod(lambda *a, **k: None)})}),
    ("neo4j", {"GraphDatabase": type("G", (), {"driver": staticmethod(lambda *a, **k: None)})}),
    ("feedparser", {"parse": lambda *a, **k: types.SimpleNamespace(entries=[])}),
]:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules.setdefault(name, m)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agents'))

import crawl
import sources

HTML = '''
<html><body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<ul>
  <li><a href="/press-release/detail?PRID=2001">Enforcement Directorate attaches assets worth 400 crore</a></li>
  <li><a href="press-release/detail?PRID=2002">CBI books former officer in bribery case</a></li>
  <li><a href="https://other-site.com/press-release/x">Offsite story that should be dropped</a></li>
  <li><a href="/files/order.pdf">Order copy in PDF, not readable as text</a></li>
  <li><a href="#top">Back to top</a></li>
  <li><a href="mailto:a@b.com">Write to us</a></li>
  <li><a href="/press-release/detail?PRID=2003">Short</a></li>
  <li><a href="/press-release/detail?PRID=2001">Enforcement Directorate attaches assets worth 400 crore</a></li>
</ul>
</body></html>
'''

base = "https://enforcementdirectorate.gov.in/press-release"
links = crawl.links_on(base, HTML, r"press-release")

print("links kept:")
for l in links:
    print("  ", l["url"], "|", l["text"][:60])

urls = [l["url"] for l in links]
checks = [
    ("relative link resolved", "https://enforcementdirectorate.gov.in/press-release/detail?PRID=2001" in urls),
    ("second relative resolved", any("PRID=2002" in u for u in urls)),
    ("offsite dropped", not any("other-site.com" in u for u in urls)),
    ("pdf dropped", not any(u.endswith(".pdf") for u in urls)),
    ("anchor dropped", not any("#top" in u for u in urls)),
    ("mailto dropped", not any(u.startswith("mailto") for u in urls)),
    ("duplicate collapsed", len(urls) == len(set(urls))),
    ("nav links filtered by pattern", not any(u.rstrip("/").endswith("about") for u in urls)),
]

fails = 0
for label, ok in checks:
    if not ok:
        fails += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}")

# robots parsing, with no network
import unittest.mock as mock
with mock.patch.object(crawl, "_robots_text", return_value="User-agent: *\nDisallow: /private\n"):
    allowed_pub = crawl.allowed("https://example.gov.in/press-release")
    allowed_priv = crawl.allowed("https://example.gov.in/private/thing")
print(f"{'ok  ' if allowed_pub else 'FAIL'} robots allows a permitted path")
print(f"{'ok  ' if not allowed_priv else 'FAIL'} robots refusal is obeyed")
fails += (0 if allowed_pub else 1) + (0 if not allowed_priv else 1)

# Source lists are well formed.
print()
print(f"news feeds:     {len(sources.NEWS_FEEDS)}")
print(f"topic searches: {len(sources.TOPICS)}")
print(f"outlets via search: {len(sources.VIA_SEARCH)}")
print(f"listing pages:  {len(sources.SITES)}")
print(f"all feeds:      {len(sources.all_feeds())}")

seen = set()
for group, rows, width in (("feed", sources.NEWS_FEEDS, 4),
                           ("search", sources.VIA_SEARCH, 4),
                           ("topic", sources.TOPICS, 4),
                           ("site", sources.SITES, 5)):
    for row in rows:
        if len(row) != width:
            print(f"FAIL {group} row has {len(row)} fields: {row[0]}")
            fails += 1
        if row[0] in seen:
            print(f"FAIL duplicate id {row[0]}")
            fails += 1
        seen.add(row[0])

for tid, name, url, tier in sources.topic_feeds():
    if not url.startswith("https://news.google.com/rss/search?q="):
        print(f"FAIL topic url malformed: {tid}")
        fails += 1

print()
print("all source ids unique and well formed" if not fails else f"{fails} problems")
sys.exit(1 if fails else 0)
