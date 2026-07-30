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

RELATIONS = [
    "WORKS_AT", "LEADS", "OWNS", "MEMBER_OF", "AWARDED_CONTRACT",
    "RECEIVED_CONTRACT", "INVESTIGATED_BY", "CHARGED_BY", "ACCUSED_OF",
    "FILED_CASE", "NAMED_IN", "RULED_ON", "APPROVED", "BLOCKED",
    "MET_WITH", "DONATED_TO", "APPOINTED", "RESIGNED_FROM",
]
TYPES = ["Person", "Company", "Government", "Court", "Place"]

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

Entity types: Person, Company, Government, Court, Place

Reply with this JSON shape and nothing else:
{{"claims":[{{"subject":"name","subject_type":"Person","relation":"WORKS_AT","object":"name","object_type":"Company","quote":"the sentence from the article that says this"}}]}}

Rules:
1. Copy the quote from the article exactly. Do not shorten or reword it.
2. Use full names as the article writes them.
3. Skip anything the article only hints at.
4. If the article states no clear relationship, reply {{"claims":[]}}.

TITLE: {title}

ARTICLE:
{body}
"""


def _normalise(text):
    return WS.sub(" ", (text or "")).strip().lower()


def call_model(prompt, system=SYSTEM, json_mode=True, timeout=None, schema=None):
    payload = {
        "model": config.LLM_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": config.LLM_CONTEXT},
    }
    if schema:
        payload["format"] = schema
    elif json_mode:
        payload["format"] = "json"
    resp = httpx.post(f"{config.OLLAMA_URL}/api/generate", json=payload,
                      timeout=timeout or config.LLM_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


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
    out = []
    for item in (data.get("claims") or [])[:12]:
        if not isinstance(item, dict):
            continue
        quote = (item.get("quote") or "").strip()
        if len(quote) < 25:
            continue
        if _normalise(quote) not in haystack:
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

        out.append({
            "subject": subject,
            "relation": relation,
            "object": obj,
            "quote": quote,
        })
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
