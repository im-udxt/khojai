"""Merge rules, written from the merges that went wrong in production.

Folding two names together cannot be undone, so every pair below is a
real decision the running system made. The wrong ones are kept as tests
so the rule that caused them cannot come back.

    python tests/test_merge_rules.py
"""
import os
import sys, types, io as _io
sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
for n, at in [("redis", {"Redis": type("R", (), {"from_url": staticmethod(lambda *a, **k: None)})}),
              ("neo4j", {"GraphDatabase": type("G", (), {"driver": staticmethod(lambda *a, **k: None)})})]:
    m = types.ModuleType(n)
    for k, v in at.items():
        setattr(m, k, v)
    sys.modules.setdefault(n, m)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agents'))

import entities, merge

def ent(name, etype="Topic", mentions=1):
    c = entities.canonical(name)
    key = c["key"] if c else name.lower()
    return {"uid": key[:16], "name": name, "key": key, "type": etype,
            "mentions": mentions}

# Pairs the live run folded automatically. Anything marked "auto" here must
# stay auto; anything marked otherwise must never fold on its own again.
CASES = [
    # These were real mistakes in production.
    ("Nationalist Congress Party NCP", "Congress Party", "Party", "not auto"),
    ("Tamil Nadu Social Welfare", "Tamil Nadu Finance", "Government", "not auto"),
    ("Karnataka cabinet", "Karnataka", "Government", "not auto"),
    ("Survey of India", "Geological Survey of India", "Government", "not auto"),
    ("Crime Branch", "Kollam District Crime Branch", "Government", "not auto"),
    ("Delhi court", "Delhi High Court", "Court", "not auto"),
    ("Lok Sabha", "Lok Sabha LoP", "Government", "not auto"),
    ("Special court", "Special Sessions Court for PoCSO", "Court", "not auto"),
    ("K.A. Ratheesh and R. Chandrasekharan", "K.A. Ratheesh", "Person", "not auto"),
    ("Meta India", "Meta India head", "Company", "not auto"),
    ("Civil Supplies", "Irrigation and Civil Supplies", "Government", "not auto"),
    ("Transport Department", "Karnataka Transport Department", "Government", "not auto"),
    ("RBI Board", "RBI Central Board", "Government", "not auto"),

    # These were correct and must keep folding without being asked.
    ("Devendranath Mahto", "Devendra Nath Mahto", "Person", "auto"),
    ("KC Venugopal", "K.C. Venugopal", "Person", "auto"),
    ("Chandrababu Naidu", "N. Chandrababu Naidu", "Person", "auto"),
    ("Senthil Balaji", "V Senthil Balaji", "Person", "auto"),
    ("Government of Jharkhand", "Jharkhand Government", "Government", "auto"),
    ("Delhi University", "University of Delhi", "Government", "auto"),
    ("Government of Andhra Pradesh", "Andhra Pradesh Government", "Government", "auto"),
]

fails = 0
print("--- merge decisions ---")
for a_name, b_name, etype, expected in CASES:
    a, b = ent(a_name, etype), ent(b_name, etype)
    action, reason = merge.judge(a, b)
    ok = (action == "auto") if expected == "auto" else (action != "auto")
    if not ok:
        fails += 1
    print(f"{'ok  ' if ok else 'FAIL'} {a_name[:34]:34} + {b_name[:32]:32} -> {action:6} [{reason[:40]}]")

# Names that should never have become nodes at all.
JUNK = [
    "ten persons including Sachin Waze and others",
    "M. Geethanandan and three others",
    "for Roads and Buildings B.C. Janardhan",
    "Raja, a native of Tamil Nadu, and Arjun",
    "for Revenue",
    "Tamil Nadu s for Housing and Urban Development Department",
]
KEEP = [
    "Reserve Bank of India", "K.C. Venugopal", "Adani Ports",
    "Supreme Court of India", "Bharatiya Janata Party", "Narendra Modi",
    "Enforcement Directorate", "Ministry of Home Affairs",
]

print()
print("--- names that must be rejected ---")
for name in JUNK:
    rejected = entities.canonical(name) is None
    if not rejected:
        fails += 1
    print(f"{'ok  ' if rejected else 'FAIL'} {name[:60]}")

print()
print("--- names that must survive ---")
for name in KEEP:
    kept = entities.canonical(name) is not None
    if not kept:
        fails += 1
    print(f"{'ok  ' if kept else 'FAIL'} {name}")

print()
print(f"{fails} failures" if fails else "all correct")
sys.exit(1 if fails else 0)
