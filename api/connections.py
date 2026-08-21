"""Turning separate facts into chains a person can read.

A single claim says one thing: this person works at that company. The value is
in the chain. Someone gave money to a body that later ruled on them. A company
and a regulator share an officer. Those are not stored anywhere. They are
found by walking the graph.

Nothing here asserts a cause. Each chain is a set of separately recorded
facts that happen to meet at a name, and every sentence says so.
"""

# Relations grouped by what they mean, so a chain can be described in words
# rather than as a list of arrow labels.
MONEY = {"DONATED_TO", "AWARDED_CONTRACT", "RECEIVED_CONTRACT", "OWNS"}
PARTY_LINKED = {"MEMBER_OF", "LEADS", "DONATED_TO", "APPOINTED"}
POWER = {"APPROVED", "BLOCKED", "RULED_ON", "APPOINTED"}
TROUBLE = {"INVESTIGATED_BY", "CHARGED_BY", "ACCUSED_OF", "FILED_CASE", "NAMED_IN"}
ROLE = {"WORKS_AT", "LEADS", "MEMBER_OF", "APPOINTED", "RESIGNED_FROM"}

PHRASE = {
    "WORKS_AT": "works at",
    "LEADS": "leads",
    "OWNS": "owns",
    "MEMBER_OF": "is a member of",
    "AWARDED_CONTRACT": "awarded a contract to",
    "RECEIVED_CONTRACT": "received a contract from",
    "INVESTIGATED_BY": "is investigated by",
    "CHARGED_BY": "was charged by",
    "ACCUSED_OF": "is accused of",
    "FILED_CASE": "filed a case against",
    "NAMED_IN": "is named in",
    "RULED_ON": "ruled on",
    "APPROVED": "approved",
    "BLOCKED": "blocked",
    "MET_WITH": "met with",
    "DONATED_TO": "donated to",
    "APPOINTED": "appointed",
    "RESIGNED_FROM": "resigned from",
    "MENTIONED_WITH": "is mentioned alongside",
}


def phrase(relation):
    return PHRASE.get(relation, (relation or "").lower().replace("_", " "))


def classify(chain, types=None):
    """Give the chain a short label describing the shape it makes."""
    relations = set(chain)
    kinds = set(types or [])
    if "Party" in kinds and relations & MONEY:
        return ("party and money",
                "A political party sits on the chain, and another step is "
                "money, a contract or ownership.")
    if "Party" in kinds and relations & POWER:
        return ("party and a decision",
                "A political party sits on the chain, and another step is a "
                "decision or an appointment.")
    if relations & MONEY and relations & POWER:
        return ("money then decision",
                "One step is money or a contract. Another is a decision or an "
                "appointment. They are recorded separately.")
    if relations & MONEY and relations & TROUBLE:
        return ("money and a case",
                "One step involves money or ownership. Another involves an "
                "investigation or a case.")
    if relations & POWER and relations & TROUBLE:
        return ("decision and a case",
                "One step is a decision or appointment. Another is an "
                "investigation or a case.")
    if len(relations & ROLE) >= 2:
        return ("shared people",
                "The same person connects both sides through their roles.")
    if relations & TROUBLE:
        return ("case link", "The chain passes through a case or investigation.")
    if relations & MONEY:
        return ("money link", "The chain passes through money or ownership.")
    return ("plain link", "The names are connected by recorded facts.")


def describe(names, relations, outlets):
    """Write the chain as one sentence, then say plainly what it is not."""
    parts = [names[0]]
    for rel, name in zip(relations, names[1:]):
        parts.append(f"{phrase(rel)} {name}")
    sentence = " ".join(parts) + "."

    sources = sorted({o for o in outlets if o})
    if len(names) > 2:
        caution = (
            f"{names[0]} and {names[-1]} are not linked directly. "
            f"They meet through {names[1]}. Each step was reported on its own, "
            "so the chain is a route through the records, not a finding."
        )
    else:
        caution = "This is a single recorded fact, not a conclusion."
    where = (f"Reported by {', '.join(sources)}." if sources
             else "Source links are listed with each step.")
    return sentence, caution, where


def confidence(outlets_backing):
    """How much independent reporting sits behind one step.

    One outlet can be wrong. Two agreeing is meaningfully different. This is
    reported per step, and a chain is only as strong as its weakest step.
    """
    n = outlets_backing or 1
    if n >= 3:
        return {"level": "well sourced", "outlets": n,
                "note": f"{n} outlets report this independently."}
    if n == 2:
        return {"level": "corroborated", "outlets": n,
                "note": "Two outlets report this independently."}
    return {"level": "single source", "outlets": 1,
            "note": "Only one outlet reports this. Read it before relying on it."}


def timeline(steps):
    """Put the steps in the order they were published, when dates allow.

    Order is what turns a set of links into a sequence. Without it, an
    appointment and a contract are just two facts.
    """
    dated = [s for s in steps if s.get("when")]
    if len(dated) < 2:
        return {"ordered": False, "note": "Not enough dates to place these in order.",
                "events": []}
    order = sorted(dated, key=lambda s: s["when"])
    events = [{"when": s["when"], "what": f"{s['from']} {s['phrase']} {s['to']}"}
              for s in order]
    same = order[0]["when"][:10] == order[-1]["when"][:10]
    note = ("All of these were reported on the same day, so the order says "
            "little." if same else
            f"Reported between {order[0]['when'][:10]} and {order[-1]['when'][:10]}. "
            "Publication order is not the order events happened.")
    return {"ordered": True, "note": note, "events": events}


def build(rows):
    """Shape raw path rows into readable chains, best first."""
    out, seen = [], set()
    for row in rows:
        names = [n for n in (row.get("names") or []) if n]
        relations = [r for r in (row.get("relations") or []) if r]
        if len(names) < 2 or len(relations) != len(names) - 1:
            continue
        key = tuple(sorted([names[0], names[-1]])) + (tuple(relations),)
        if key in seen:
            continue
        seen.add(key)

        outlets = row.get("outlets") or []
        label, why = classify(relations, row.get("types"))
        sentence, caution, where = describe(names, relations, outlets)
        quotes = row.get("quotes") or [None] * len(relations)
        urls = row.get("urls") or [None] * len(relations)
        outlet_list = row.get("outlets") or [None] * len(relations)
        backing = row.get("backing") or [1] * len(relations)
        dates = row.get("dates") or [None] * len(relations)
        steps = [
            {
                "from": names[i],
                "relation": relations[i],
                "phrase": phrase(relations[i]),
                "to": names[i + 1],
                "quote": quotes[i] if i < len(quotes) else None,
                "url": urls[i] if i < len(urls) else None,
                "outlet": outlet_list[i] if i < len(outlet_list) else None,
                "outlets_backing": backing[i] if i < len(backing) else 1,
                "confidence": confidence(backing[i] if i < len(backing) else 1),
                "when": dates[i] if i < len(dates) else None,
            }
            for i in range(len(relations))
        ]
        weakest = min([s["outlets_backing"] or 1 for s in steps] or [1])
        out.append({
            "label": label,
            "why": why,
            "sentence": sentence,
            "caution": caution,
            "sources": where,
            "names": names,
            "uids": row.get("uids") or [],
            "steps": steps,
            "types": row.get("types") or [],
            "confidence": confidence(weakest),
            "weakest_backing": weakest,
            "timeline": timeline(steps),
            "outlet_count": len({o for o in outlets if o}),
            "hops": len(relations),
        })

    rank = {"party and money": 0, "party and a decision": 1,
            "money then decision": 2, "money and a case": 3,
            "decision and a case": 4, "shared people": 5, "case link": 6,
            "money link": 7, "plain link": 8}
    out.sort(key=lambda c: (rank.get(c["label"], 9), -c["outlet_count"], c["hops"]))
    return out
