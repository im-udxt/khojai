# Sources

65 sources in four kinds. 60 were producing at the last sweep.

The status page has a Sources tab showing what each one returned the last time
it was tried, so a source that has quietly died looks different from one that
is working. That page is the current truth; this file explains the shape of it.

| Kind | Count | What it is |
| --- | --- | --- |
| Direct feeds | 23 | An outlet's own RSS |
| Outlets through search | 15 | Outlets whose feed stopped working |
| Topic searches | 17 | A question asked across every outlet |
| Listing pages | 10 | Pages with no feed, walked like a browser |

## Direct feeds

The cheapest and most reliable, so they are read first and in full. National
papers, business papers, legal reporting, and the official feeds that still
work: the Press Information Bureau, the Reserve Bank and SEBI.

## Outlets reached through search

Fifteen outlets stopped answering a plain feed request. Some return a bot
challenge page with a 200 status, some redirect into something that is not XML,
some are simply 404 now. A more honest user agent did not help; they are
blocking anything that is not a browser.

Their reporting is still indexed, so they are read through a search scoped to
the outlet instead. This includes The Wire, ThePrint, LiveLaw, The Caravan,
Article 14, Reuters India, Telegraph India, New Indian Express, Financial
Express, The Federal, IndiaSpend and Down To Earth.

It is a much worse source than a feed, for the reason in the next section, and
it should be treated as a way of knowing something was published rather than a
way of reading it.

Scroll, Firstpost and Deccan Herald were moved off search and onto their own
section pages, which can be walked directly. That gets the body back, which
search never could.

## Topic searches

Section feeds carry whatever an outlet chose to promote on its front page.
These ask the question directly instead, and they are how court and enforcement
reporting gets in at all, since almost none of it publishes a feed.

Seventeen of them: Supreme Court and High Court coverage, the Enforcement
Directorate, the CBI, CAG audit reports, tenders and contracts, political
funding and party organisation, candidate asset declarations, SEBI orders,
insolvency, income tax action, state vigilance, RTI replies, cabinet decisions,
land and mining, and fraud investigations.

**They return headlines, not articles.** A Google News link goes to a redirect
page that only a browser can follow, so the body can never be fetched and a
claim needs a sentence quoted from the body. Measured on live traffic, 31 of
40 documents arriving this way had no readable body.

They were counted as high yield because they returned a lot of items. Items
are not claims. A source that returns fifty headlines and no article text
contributes nothing to the graph, and the Sources tab now separates the two.

## Listing pages

Pages with a list of links and no feed, read by `crawl.py`. Each host is asked
for its robots file first and a refusal is obeyed.

Producing:

| Source | What comes from it |
| --- | --- |
| Central Bureau of Investigation | Press releases, chargesheets, arrests |
| Press Information Bureau | Government press releases |
| National Human Rights Commission | Press releases and suo motu notices |
| PRS Legislative Research | Bill tracking |
| Supreme Court Observer | Case reporting and analysis |

Fetching but matching nothing:

| Source | Why |
| --- | --- |
| Comptroller and Auditor General | Certificate handshake fails intermittently |
| National Green Tribunal | Documents are behind a rendered index |
| National Company Law Tribunal | Orders are PDF |
| Parliament of India | Question lists are drawn by script |
| Mumbai Police | Releases are behind a rendered index |

These are left in place rather than removed. They cost one request per sweep,
they are reported honestly as producing nothing, and any of them may start
working again if the site changes.

## Tried and left out

Documented so nobody spends an afternoon finding out again.

| Source | Why not |
| --- | --- |
| data.gov.in | Its robots file refuses us |
| Competition Commission of India | Certificate chain does not verify |
| Delhi Police | Certificate has expired |
| Election Commission of India | The list is drawn by script, the page has no links |
| Enforcement Directorate | Every path tried returns 404 |
| Ministry of Home Affairs | Every path tried returns 404 |
| National Investigation Agency | Every path tried returns 404 |
| Association for Democratic Reforms | Every path tried returns 404 |
| Ministry of Corporate Affairs | Navigation only |
| SEBI enforcement orders | Returns 403 to anything that is not a browser |

Neither certificate problem was worked around by turning verification off. That
would trade a real protection for a few more articles.

## The biggest gap

**Court judgments are mostly PDF and are skipped entirely.** Binary formats are
filtered out before a request is made, because a PDF fetched as text is noise
that fills the queue. A PDF reader is the single change that would open up the
largest body of material this project does not currently see.

## Adding a source

Feeds and topic searches go in the lists at the top of `agents/sources.py`.

A listing page needs a URL and a pattern that its document links match but its
navigation does not. Get this wrong and the menu arrives as twenty documents.
Two things guard against that: the pattern, and a rule that link text under 25
characters is navigation rather than a title.

Check it before committing:

```python
import crawl
docs = crawl.walk(("s_test", "Test", "https://example.gov.in/press", r"press-detail", 1))
```

If it returns menu items, the pattern is too loose.
