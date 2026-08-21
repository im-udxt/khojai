"""Entity normalisation and typing.

The first version of this project stored whatever the model returned. That
filled the graph with dates, weekdays, place names typed as people, and the
same organisation under four spellings. Search was poor as a direct result.
This module is the single place where a raw string becomes a canonical entity.
"""
import hashlib
import re

HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "prof", "shri", "smt", "sri", "sh",
    "hon", "honble", "justice", "adv", "advocate", "capt", "col", "gen",
    "lt", "maj", "cm", "pm", "president", "minister", "chief",
}

COMPANY_SUFFIXES = {
    "ltd", "limited", "pvt", "private", "llp", "llc", "inc", "incorporated",
    "corp", "corporation", "co", "company", "plc", "gmbh", "holdings",
    "industries", "enterprises", "ventures", "group", "technologies", "tech",
    "solutions", "services", "systems", "labs", "motors", "bank", "finance",
    "capital", "infra", "infrastructure", "energy", "power", "steel", "cement",
    "ports", "port", "mills", "textiles", "pharma", "pharmaceuticals",
    "chemicals", "minerals", "mining", "logistics", "telecom", "airlines",
}

GOVERNMENT_WORDS = {
    "ministry", "department", "commission", "authority", "board", "bureau",
    "agency", "directorate", "council", "committee", "tribunal", "court",
    "parliament", "assembly", "sabha", "government", "govt", "corporation",
    "municipal", "panchayat", "secretariat", "cabinet", "police", "cbi", "ed",
    "sebi", "rbi", "cag", "eci", "nia", "ncb", "gst", "income tax",
}

COURT_WORDS = {"court", "tribunal", "bench", "judiciary", "nclt", "nclat", "itat"}

# Bodies whose names carry no word that says what they are. The Reserve Bank
# of India reads as a company because of "bank", and anything beginning with
# "Union" is the central government rather than a union.
KNOWN_GOVERNMENT = {
    "reserve bank of india", "state bank of india", "securities and exchange board of india", "comptroller and auditor general of india",
    "election commission of india", "niti aayog", "lokpal", "lokayukta",
    "enforcement directorate", "central bureau of investigation",
    "national investigation agency", "narcotics control bureau",
    "central vigilance commission", "income tax department",
}

# Strings that are never useful entities on their own.
STOPWORDS = {
    "india", "indian", "bharat", "the", "this", "that", "these", "those",
    "today", "yesterday", "tomorrow", "now", "here", "there", "news", "report",
    "reports", "update", "updates", "story", "article", "video", "photo",
    "live", "breaking", "exclusive", "opinion", "editorial", "analysis",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "people", "person", "man", "woman", "men", "women", "child", "children",
    "police", "government", "state", "states", "country", "city", "district",
    "year", "years", "month", "months", "week", "day", "days", "time",
    "crore", "lakh", "million", "billion", "percent", "rupees", "rs", "usd",
}

DATE_RE = re.compile(
    r"^\s*(\d{1,2}[\s/-]|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|"
    r"\d{4}[-/]\d{1,2})", re.IGNORECASE)
NUMBER_RE = re.compile(r"^[\d\s.,%+/-]+$")
MONEY_RE = re.compile(r"^(rs\.?|inr|usd|\$|₹)\s*[\d,.]+", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[\"'`''\"\"()\[\]{}<>|\\]")

VALID_TYPES = {"Person", "Company", "Government", "Court", "Place", "Party",
               "Event", "Topic"}

# Party names carry weight in this material, so they get their own type rather
# than being filed under Government or Company.
# "Union" was on this list and had to come off. In Indian government naming
# it means the central government, not a political one, so it typed the Union
# Home Affairs Ministry and the Union Territories as parties.
PARTY_WORDS = {
    "party", "dal", "sena", "congress", "morcha", "manch", "kazhagam",
    "sangh", "samaj", "samiti", "front", "league",
}
PARTY_NAMES = {
    "bjp", "bharatiya janata party", "indian national congress", "congress",
    "aap", "aam aadmi party", "dmk", "aiadmk", "tmc", "trinamool congress",
    "ncp", "shiv sena", "jdu", "janata dal united", "rjd", "sp",
    "samajwadi party", "bsp", "bahujan samaj party", "cpi", "cpim",
    "cpi m", "left front", "ysrcp", "trs", "brs", "bjd", "akali dal",
    "shiromani akali dal", "national conference", "pdp", "mim", "aimim",
    "jmm", "inld", "rld", "tdp", "janasena", "mns", "iuml", "kerala congress",
}


def clean(name):
    """Trim quotes, collapse whitespace, drop a leading article."""
    if not name:
        return ""
    text = PUNCT_RE.sub(" ", str(name))
    text = WS_RE.sub(" ", text).strip(" .,;:-—–")
    if text.lower().startswith("the "):
        text = text[4:].strip()
    return text


def is_junk(name):
    """True when the string should never become a node."""
    text = clean(name)
    if len(text) < 3 or len(text) > 90:
        return True
    low = text.lower()
    if low in STOPWORDS:
        return True
    if NUMBER_RE.match(text) or MONEY_RE.match(text) or DATE_RE.match(text):
        return True
    if not re.search(r"[A-Za-z]", text):
        return True
    # Names are capitalised. A phrase with no capital letter at all is a
    # description, not a name. This throws out things like "six accused",
    # "quashed clean chit" and "government bus driver", which smaller models
    # return as if they were entities.
    if not any(w[:1].isupper() for w in text.split()):
        return True
    # A phrase where lowercase words outnumber capitalised ones is a
    # description, not a name: "Government bus driver", "accused Ramesh said".
    # Small joining words are ignored so "Reserve Bank of India" survives.
    joiners = {"of", "and", "the", "for", "in", "on", "at", "to", "de", "van"}
    words = [w for w in text.split() if w.lower() not in joiners]
    if len(words) >= 2:
        upper = sum(1 for w in words if w[:1].isupper())
        if upper < len(words) - upper:
            return True
    words = [w for w in re.split(r"\W+", low) if w]
    if words and all(w in STOPWORDS for w in words):
        return True

    # Sentence fragments the model returned as if they were names. These are
    # what put "ten persons including Sachin Waze and others" into the graph
    # as a node, which then pulled two unrelated people together when
    # duplicate names were folded.
    parts = text.split()
    if "," in text:
        return True
    if len(parts) > 6:
        return True
    if parts and parts[0][:1].islower():
        # "for Roads and Buildings", "ten persons including". A name does not
        # begin with a lowercase word.
        return True
    if set(w.strip(".,") for w in low.split()) & {
            "including", "others", "other", "persons", "along", "alias",
            "namely", "etc", "various", "several"}:
        return True
    return False


def infer_type(name, hint=None):
    """Decide the node label from the name, using the model hint as a tiebreak."""
    text = clean(name)
    low = text.lower()
    words = set(re.split(r"\W+", low)) - {""}

    # A name that is a known party is a party whatever else it contains.
    stripped = re.sub(r"[^a-z0-9 ]", "", low).strip()
    if stripped in PARTY_NAMES:
        return "Party"
    if stripped in KNOWN_GOVERNMENT or stripped.startswith("union "):
        return "Government"

    # Court and government words are checked before the looser party words,
    # because a name carrying both is far more often a state body than a
    # party: "Congress Working Committee" is the exception, "Union Home
    # Affairs Ministry" is the rule.
    if words & COURT_WORDS:
        return "Court"
    if words & GOVERNMENT_WORDS or low.startswith(("ministry of", "department of")):
        return "Government"
    if words & PARTY_WORDS:
        return "Party"
    if words & COMPANY_SUFFIXES:
        return "Company"

    if hint in VALID_TYPES:
        # Trust the hint only when it does not contradict the rules above.
        if hint == "Person" and (words & COMPANY_SUFFIXES or words & GOVERNMENT_WORDS):
            return "Company"
        return hint

    # Two or three capitalised words with no corporate marker reads as a person.
    parts = text.split()
    if 2 <= len(parts) <= 3 and all(p[:1].isupper() for p in parts if p):
        return "Person"
    return "Topic"


def canonical(name, hint=None):
    """Return the canonical form of an entity, or None when it is junk.

    The key is what makes two spellings the same node: lowercase, no
    honorifics, no legal suffixes, no punctuation.
    """
    text = clean(name)
    if is_junk(text):
        return None

    etype = infer_type(text, hint)
    words = [w for w in re.split(r"[\s.]+", text.lower()) if w]
    while words and words[0].strip(".") in HONORIFICS:
        words.pop(0)
    if not words:
        return None

    if etype == "Company":
        while words and words[-1].strip(".") in COMPANY_SUFFIXES:
            words.pop()
        if not words:
            return None

    key = " ".join(words)
    key = re.sub(r"[^a-z0-9 ]", "", key).strip()
    if len(key) < 3:
        return None

    display = " ".join(w for w in text.split()
                       if w.lower().strip(".") not in HONORIFICS) or text
    return {
        "key": key,
        "name": display,
        "type": etype,
        # The id comes from the name alone. Including the type meant that
        # improving the typing rules split one name into two nodes and
        # scattered its links.
        "uid": hashlib.sha1(key.encode()).hexdigest()[:16],
    }


def resolve_many(raw_entities):
    """Normalise a list of {name, type} and merge duplicates."""
    out = {}
    for item in raw_entities or []:
        name = item.get("name") if isinstance(item, dict) else item
        hint = item.get("type") if isinstance(item, dict) else None
        ent = canonical(name, hint)
        if not ent:
            continue
        existing = out.get(ent["key"])
        if existing:
            # Keep the longer display form, it is usually the fuller name.
            if len(ent["name"]) > len(existing["name"]):
                existing["name"] = ent["name"]
        else:
            out[ent["key"]] = ent
    return list(out.values())
