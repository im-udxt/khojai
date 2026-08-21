"""Entity typing, written from names that were typed wrongly on the live site.

Type decides which page a name shows up on, so a party that is really a
ministry puts a government body on the parties page. Every case below was
seen in the running graph.

    python tests/test_entity_types.py
"""
import os
import sys
import types

for name, attrs in [
    ("redis", {"Redis": type("R", (), {"from_url": staticmethod(lambda *a, **k: None)})}),
    ("neo4j", {"GraphDatabase": type("G", (), {"driver": staticmethod(lambda *a, **k: None)})}),
]:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agents'))

import entities

CASES = [
    # Parties, which must keep being parties.
    ("Bharatiya Janata Party", "Party"),
    ("Congress", "Party"),
    ("Shiv Sena", "Party"),
    ("Jan Suraaj Party", "Party"),
    ("Trinamool Congress", "Party"),
    ("Samajwadi Party", "Party"),

    # These were showing up on the parties page because "union" was treated
    # as a party word. In Indian government naming it means the centre.
    ("Union Home Affairs Ministry", "Government"),
    ("Union Ministry of Corporate Affairs", "Government"),
    ("Union Civil Aviation", "Government"),

    # Bodies whose names carry no word saying what they are.
    ("Reserve Bank of India", "Government"),
    ("Enforcement Directorate", "Government"),
    ("Election Commission of India", "Government"),

    # The rest of the types must be unaffected.
    ("Delhi High Court", "Court"),
    ("Supreme Court of India", "Court"),
    ("Adani Ports", "Company"),
    ("Tata Motors", "Company"),
    ("Narendra Modi", "Person"),
    ("K.C. Venugopal", "Person"),
    ("Ministry of Home Affairs", "Government"),
]

fails = 0
for name, expected in CASES:
    found = entities.canonical(name)
    got = found["type"] if found else "REJECTED"
    ok = got == expected
    if not ok:
        fails += 1
    print(f"{'ok  ' if ok else 'FAIL'} {name:38} -> {got:11} (wanted {expected})")

print()
print("all correct" if not fails else f"{fails} wrong")
sys.exit(1 if fails else 0)
