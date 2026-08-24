"""Turning article text into sourced claims.

The model is only allowed to copy. Every relationship it returns must carry a
quote that appears in the article word for word. Anything else is dropped
before it reaches the graph.
"""
import json
import logging
import re

import httpx

import config
import entities

log = logging.getLogger("khoj.extract")

WS = re.compile(r"\s+")

SYSTEM = (
    "You read one news article and list the relationships it states. "
    "You never use outside knowledge. You never guess. "
    "If the article does not state a relationship, you leave it out. "
    "You reply with JSON only."
)

# MENTIONED_WITH is the honest fallback. Without it a small model forces a
# specific relation it is not sure about, and WORKS_AT becomes a dumping
# ground for anything it cannot classify.
RELATIONS = [
    "WORKS_AT", "LEADS", "OWNS", "MEMBER_OF", "AWARDED_CONTRACT",
    "RECEIVED_CONTRACT", "INVESTIGATED_BY", "CHARGED_BY", "ACCUSED_OF",
    "FILED_CASE", "NAMED_IN", "RULED_ON", "APPROVED", "BLOCKED",
    "MET_WITH", "DONATED_TO", "APPOINTED", "RESIGNED_FROM", "MENTIONED_WITH",
]
TYPES = ["Person", "Company", "Government", "Court", "Place", "Party"]

# A schema, not a suggestion. Ollama constrains generation to this shape, so
# the quote can never be left out and the relation can never be invented.
# Without it a 3B model drops the quote field on most articles and the claim
# is thrown away, which made the yield close to zero.
SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string", "minLength": 25},
                    "subject": {"type": "string", "minLength": 2},
                    "subject_type": {"type": "string", "enum": TYPES},
                    "relation": {"type": "string", "enum": RELATIONS},
                    "object": {"type": "string", "minLength": 2},
                    "object_type": {"type": "string", "enum": TYPES},
                },
                "required": ["quote", "subject", "subject_type", "relation",
                             "object", "object_type"],
            },
        }
    },
    "required": ["claims"],
}

PROMPT = """Read the article and list relationships it directly states.

Allowed relations: WORKS_AT, LEADS, OWNS, MEMBER_OF, AWARDED_CONTRACT,
RECEIVED_CONTRACT, INVESTIGATED_BY, CHARGED_BY, ACCUSED_OF, FILED_CASE,
NAMED_IN, RULED_ON, APPROVED, BLOCKED, MET_WITH, DONATED_TO, APPOINTED,
RESIGNED_FROM

Entity types: Person, Company, Government, Court, Place, Party
Party means a political party.

Reply with this JSON shape and nothing else:
{{"claims":[{{"subject":"name","subject_type":"Person","relation":"WORKS_AT","object":"name","object_type":"Company","quote":"the sentence from the article that says this"}}]}}

What the relations mean:
WORKS_AT is employment only. A person held in a jail does not work at it.
LEADS is heading an organisation. APPOINTED is naming someone to a post.
AWARDED_CONTRACT is the buyer, RECEIVED_CONTRACT is the supplier.
CHARGED_BY and INVESTIGATED_BY name the agency doing it.
MENTIONED_WITH means the two are linked but the article does not say how.

Rules:
1. Copy the quote from the article exactly. Do not shorten or reword it.
2. Use full names as the article writes them. Never use a description such as
   "six accused" or "the convict" as a name.
3. Skip anything the article only hints at.
4. Use MENTIONED_WITH when you are not certain which relation applies. Do not
   guess a specific one.
5. If the article states no clear relationship, reply {{"claims":[]}}.

TITLE: {title}

ARTICLE:
{body}
"""


def _normalise(text):
    return WS.sub(" ", (text or "")).strip().lower()


WORD_ONLY = re.compile(r"[a-z0-9]+")


def _words(text):
    """The word sequence, with typography and punctuation removed.

    The verbatim rule is what makes a claim checkable, so it stays. But it was
    also throwing away good claims over a curly apostrophe or a hyphen: an
    article writes "in-charge" and the model writes "in charge", and a real
    sentence was treated as invented. Comparing the words in order keeps the
    guarantee, because the model still cannot add, drop or reorder a word,
    while ignoring differences that carry no meaning.
    """
    import unicodedata
    text = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(WORD_ONLY.findall(text))


# Models that reason out loud before answering. Ollama puts that reasoning in
# a separate field and leaves the answer empty, so a schema that is obeyed
# perfectly still arrives as nothing. Asking them not to think is what makes
# them usable here: we want the sentence copied, not an argument about it.
THINKING_MODELS = ("qwen3", "deepseek-r1", "magistral", "phi4-reasoning")


def thinks(model):
    name = (model or "").lower()
    return any(name.startswith(prefix) for prefix in THINKING_MODELS)


def call_model(prompt, system=SYSTEM, json_mode=True, timeout=None, schema=None):
    payload = {
        "model": config.LLM_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        # Ollama unloads a model after five minutes idle and reloading it
        # from disk costs about fifty seconds on this machine. That is longer
        # than most extractions take, so an unloaded model turned every first
        # request into a timeout. Holding it resident is the difference
        # between working and not.
        "keep_alive": config.LLM_KEEP_ALIVE,
        "options": {"temperature": 0, "num_ctx": config.LLM_CONTEXT},
    }
    if thinks(config.LLM_MODEL):
        payload["think"] = False
    if schema:
        payload["format"] = schema
    elif json_mode:
        payload["format"] = "json"
    resp = httpx.post(f"{config.OLLAMA_URL}/api/generate", json=payload,
                      timeout=timeout or config.LLM_TIMEOUT)
    if resp.status_code == 400 and "think" in payload:
        # An older Ollama, or a model that does not take the option at all.
        payload.pop("think")
        resp = httpx.post(f"{config.OLLAMA_URL}/api/generate", json=payload,
                          timeout=timeout or config.LLM_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    answer = (body.get("response") or "").strip()
    if not answer:
        # Some builds ignore think=False and answer in the thinking field
        # anyway. The reply is still there, so use it rather than dropping
        # the whole article.
        answer = (body.get("thinking") or "").strip()
    return answer


def model_ready():
    try:
        resp = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        wanted = config.LLM_MODEL.split(":")[0]
        return any(n.startswith(wanted) for n in names)
    except Exception:
        return False


def warm():
    """Load the model and keep it resident.

    Called at startup and whenever it looks unloaded, so the cost of loading
    is paid once here rather than inside an extraction that then times out.
    """
    try:
        resp = httpx.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": config.LLM_MODEL, "prompt": "ok", "stream": False,
                  "keep_alive": config.LLM_KEEP_ALIVE,
                  "options": {"num_predict": 1}},
            timeout=config.LLM_LOAD_TIMEOUT)
        return resp.status_code == 200
    except Exception as exc:
        log.warning("could not warm the model: %s", str(exc)[:90])
        return False


def loaded():
    """True when the model is already in memory, so no reload is coming."""
    try:
        resp = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5)
        if resp.status_code != 200:
            return False
        wanted = config.LLM_MODEL.split(":")[0]
        return any((m.get("name") or "").startswith(wanted)
                   for m in resp.json().get("models", []))
    except Exception:
        return False


def _parse(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[4:] if raw[:4].lower() == "json" else raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def claims_from(doc):
    """Return validated claims for one document.

    Each claim is {subject, relation, object, quote} with subject and object
    already resolved to canonical entities.
    """
    body = (doc.get("text") or "").strip()
    if len(body) < config.EXTRACT_MIN_CHARS:
        return []

    budget = max((config.LLM_CONTEXT - 900) * 3, 2000)
    prompt = PROMPT.format(title=doc.get("title", ""), body=body[:budget])
    try:
        raw = call_model(prompt, schema=SCHEMA)
    except Exception as exc:
        log.warning("model call failed: %s", str(exc)[:120])
        raise

    data = _parse(raw)
    if not isinstance(data, dict):
        return []

    # The quote must come from the body. Small models otherwise copy the
    # headline for every claim, which proves nothing.
    haystack = _normalise(body)
    haystack_words = _words(body)
    out = []
    for item in (data.get("claims") or [])[:12]:
        if not isinstance(item, dict):
            continue
        quote = (item.get("quote") or "").strip()
        if len(quote) < 25:
            continue
        if _normalise(quote) not in haystack and _words(quote) not in haystack_words:
            continue

        subject = entities.canonical(item.get("subject"), item.get("subject_type"))
        obj = entities.canonical(item.get("object"), item.get("object_type"))
        if not subject or not obj or subject["uid"] == obj["uid"]:
            continue

        # The quote has to actually mention what it is being used to prove.
        # This catches the common failure where a real sentence is attached to
        # an unrelated claim.
        quoted = _normalise(quote)
        if not (_mentions(quoted, subject) or _mentions(quoted, obj)):
            continue

        relation = (item.get("relation") or "").upper()
        if relation not in RELATIONS:
            continue

        # Fall back to the honest label rather than dropping the pair, so a
        # real co-appearance is not lost to a badly chosen relation.
        if relation != "MENTIONED_WITH" and not plausible(subject, relation, obj):
            relation = "MENTIONED_WITH"

        out.append({
            "subject": subject,
            "relation": relation,
            "object": obj,
            "quote": quote,
        })
    return _one_per_pair(out)


def _one_per_pair(claims):
    """Keep one relation for each pair of names in an article.

    A model that is unsure does not say so. It offers every relation it can
    think of for the same two names: on one test article a larger model
    returned that the same person had received a contract from a company,
    owned it, approved it, met it and donated to it, all from one sentence.
    Five of those are invented, and the fact that they contradict each other
    is the evidence for that.

    So a pair gets one relation per article. Where the model offered three or
    more, it was guessing, and the pair drops to the honest label instead of
    keeping whichever guess happened to come first.
    """
    order, seen = [], {}
    for claim in claims:
        pair = tuple(sorted((claim["subject"]["uid"], claim["object"]["uid"])))
        if pair not in seen:
            seen[pair] = {"claim": claim, "relations": set()}
            order.append(pair)
        seen[pair]["relations"].add(claim["relation"])

    out = []
    for pair in order:
        entry = seen[pair]
        claim = entry["claim"]
        specific = entry["relations"] - {"MENTIONED_WITH"}
        if len(specific) >= 3:
            claim = dict(claim, relation="MENTIONED_WITH")
        out.append(claim)
    return out


def _mentions(quoted_text, entity):
    """True when the quote contains the entity name or a distinctive part."""
    parts = [p for p in entity["key"].split() if len(p) > 3]
    if not parts:
        return entity["key"] in quoted_text
    return any(p in quoted_text for p in parts)


def summarise(question, evidence_lines):
    """Plain summary built only from the evidence lines given."""
    if not evidence_lines:
        return "Nothing documented yet."
    prompt = (
        "Answer the question using only the numbered facts below. "
        "Cite each fact you use as [n]. Do not add anything not listed. "
        "Write at most four short sentences in plain English.\n\n"
        f"QUESTION: {question}\n\nFACTS:\n" + "\n".join(evidence_lines[:20]) +
        '\n\nReply as JSON: {"answer":"..."}'
    )
    try:
        data = _parse(call_model(prompt, system="You summarise facts. JSON only.",
                                 timeout=120))
        if isinstance(data, dict) and data.get("answer"):
            return str(data["answer"]).strip()
    except Exception as exc:
        log.warning("summary failed: %s", str(exc)[:120])
    return "Summary unavailable. The documented facts are listed below."

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {"type": "boolean"},
        "better": {"type": "string", "enum": RELATIONS + ["NONE"]},
    },
    "required": ["correct", "better"],
}

VERIFY_PROMPT = """Here is one sentence from a news article.

SENTENCE: {quote}

Someone claims this sentence says:
  {subject} -- {relation} --> {object}

Does the sentence actually state that? Judge only the sentence.
If it does, set correct to true and better to NONE.
If it does not, set correct to false and put the relation the sentence really
states, or NONE if the sentence states no relation between those two.
"""


def verify(claim):
    """Second look at one claim, using only its quote.

    The first pass reads a whole article and often picks a relation that is
    nearly right. Asking again with just the sentence catches that. This is
    what stops wrong links from being chained into confident nonsense.
    """
    try:
        raw = call_model(
            VERIFY_PROMPT.format(
                quote=claim["quote"][:600],
                subject=claim["subject"]["name"],
                relation=claim["relation"],
                object=claim["object"]["name"]),
            system="You check whether a sentence states a relationship. JSON only.",
            schema=VERIFY_SCHEMA,
            timeout=60)
    except Exception as exc:
        log.debug("verify call failed, keeping claim: %s", str(exc)[:80])
        return claim
    data = _parse(raw)
    if not isinstance(data, dict):
        return claim
    if data.get("correct") is True:
        return claim
    better = (data.get("better") or "NONE").upper()
    if better in RELATIONS and better != claim["relation"]:
        claim["relation"] = better
        return claim
    return None

# Which relations make sense between which kinds of name. A 3B model happily
# writes "Supreme Court received a contract from Delhi High Court", and asking
# it to check its own work proved unreliable in both directions: it dropped
# correct claims and mis-corrected wrong ones. These rules are deterministic,
# free, and catch exactly that class of nonsense.
SUBJECT_MUST_BE = {
    "WORKS_AT": {"Person"},
    "LEADS": {"Person"},
    "MEMBER_OF": {"Person"},
    "RESIGNED_FROM": {"Person"},
    "LEADS_PARTY": {"Person"},
    "RULED_ON": {"Court"},
    "APPOINTED": {"Person", "Government", "Company", "Court"},
    "DONATED_TO": {"Person", "Company"},
    "AWARDED_CONTRACT": {"Government", "Company"},
    "RECEIVED_CONTRACT": {"Company", "Person"},
    "FILED_CASE": {"Person", "Company", "Government"},
}
OBJECT_MUST_BE = {
    "WORKS_AT": {"Company", "Government", "Court", "Party"},
    "LEADS": {"Company", "Government", "Court", "Party"},
    "MEMBER_OF": {"Company", "Government", "Court", "Party"},
    "RESIGNED_FROM": {"Company", "Government", "Court", "Party"},
    "INVESTIGATED_BY": {"Government", "Court"},
    "CHARGED_BY": {"Government", "Court"},
    "AWARDED_CONTRACT": {"Company", "Person"},
    "RECEIVED_CONTRACT": {"Government", "Company"},
    "DONATED_TO": {"Person", "Company", "Government", "Party"},
}
# A contract or a ruling between two courts is a sign the relation was guessed.
SAME_TYPE_BANNED = {"RECEIVED_CONTRACT", "AWARDED_CONTRACT", "DONATED_TO",
                    "WORKS_AT", "LEADS", "MEMBER_OF"}


def plausible(subject, relation, obj):
    """False when the relation cannot hold between these two kinds of name."""
    s_type, o_type = subject["type"], obj["type"]
    allowed_s = SUBJECT_MUST_BE.get(relation)
    if allowed_s and s_type not in allowed_s:
        return False
    allowed_o = OBJECT_MUST_BE.get(relation)
    if allowed_o and o_type not in allowed_o:
        return False
    if relation in SAME_TYPE_BANNED and s_type == o_type and s_type in {"Court", "Government"}:
        return False
    return True
