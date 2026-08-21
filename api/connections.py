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


def classify(chain):
    """Give the chain a short label describing the shape it makes."""
    relations = set(chain)
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
        label, why = classify(relations)
        sentence, caution, where = describe(names, relations, outlets)
        steps = [
            {
                "from": names[i],
                "relation": relations[i],
                "phrase": phrase(relations[i]),
                "to": names[i + 1],
                "quote": (row.get("quotes") or [None] * len(relations))[i],
                "url": (row.get("urls") or [None] * len(relations))[i],
                "outlet": (row.get("outlets") or [None] * len(relations))[i],
            }
            for i in range(len(relations))
        ]
        out.append({
            "label": label,
            "why": why,
            "sentence": sentence,
            "caution": caution,
            "sources": where,
            "names": names,
            "uids": row.get("uids") or [],
            "steps": steps,
            "outlet_count": len({o for o in outlets if o}),
            "hops": len(relations),
        })

    rank = {"money then decision": 0, "money and a case": 1, "decision and a case": 2,
            "shared people": 3, "case link": 4, "money link": 5, "plain link": 6}
    out.sort(key=lambda c: (rank.get(c["label"], 9), -c["outlet_count"], c["hops"]))
    return out
