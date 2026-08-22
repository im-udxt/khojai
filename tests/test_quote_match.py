"""The verbatim quote rule is what makes a claim checkable.

It is allowed to ignore typography, because an article writing "in-charge"
and a model writing "in charge" is the same sentence. It is not allowed to
ignore a changed, added, dropped or reordered word, because then the quote
stops being evidence.

    python tests/test_quote_match.py
"""
import os
import sys
import types

for name, attrs in [
    ("redis", {"Redis": type("R", (), {"from_url": staticmethod(lambda *a, **k: None)})}),
    ("neo4j", {"GraphDatabase": type("G", (), {"driver": staticmethod(lambda *a, **k: None)})}),
    ("httpx", {"get": lambda *a, **k: None, "post": lambda *a, **k: None}),
]:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agents'))

import extract

BODY = (
    "Congress general secretary in-charge of communications, Jairam Ramesh, "
    "claimed that the Modi government’s ruling weakens worker safeguards. "
    "The Enforcement Directorate attached assets worth ₹400 crore on Tuesday. "
    "Joyalukkas and Kalyan Jewellers won the contract — a first for the state."
)


def matches(quote):
    """The same test claims_from applies to a quote."""
    return (extract._normalise(quote) in extract._normalise(BODY)
            or extract._words(quote) in extract._words(BODY))


ACCEPT = [
    ("exact copy",
     "The Enforcement Directorate attached assets worth ₹400 crore on Tuesday."),
    ("hyphen written as a space",
     "Congress general secretary in charge of communications, Jairam Ramesh, claimed"),
    ("straight apostrophe for a curly one",
     "the Modi government's ruling weakens worker safeguards"),
    ("em dash written as a hyphen",
     "Joyalukkas and Kalyan Jewellers won the contract - a first for the state"),
    ("different spacing",
     "The  Enforcement   Directorate attached assets worth ₹400 crore"),
    ("case changed",
     "THE ENFORCEMENT DIRECTORATE ATTACHED ASSETS WORTH ₹400 CRORE"),
]

REJECT = [
    ("a word changed",
     "The Enforcement Directorate seized assets worth ₹400 crore on Tuesday."),
    ("a number changed",
     "The Enforcement Directorate attached assets worth ₹500 crore on Tuesday."),
    ("a word added",
     "The Enforcement Directorate illegally attached assets worth ₹400 crore"),
    ("a word dropped",
     "The Enforcement Directorate attached worth ₹400 crore on Tuesday."),
    ("words reordered",
     "Assets worth ₹400 crore were attached by the Enforcement Directorate"),
    ("a sentence that is not in the article at all",
     "The Enforcement Directorate said the company had cooperated fully."),
    ("two real fragments joined that were never adjacent",
     "The Enforcement Directorate attached assets worth ₹400 crore and "
     "Joyalukkas won the contract"),
]

fails = 0
print("must be accepted:")
for label, quote in ACCEPT:
    ok = matches(quote)
    fails += 0 if ok else 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")

print()
print("must be rejected:")
for label, quote in REJECT:
    ok = not matches(quote)
    fails += 0 if ok else 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")

print()
print("all correct" if not fails else f"{fails} wrong")
sys.exit(1 if fails else 0)
