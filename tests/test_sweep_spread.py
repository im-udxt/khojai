"""The sweep must reach every source, not just the first few.

This is written from a real outage. The source list grew from 26 to 65, the
sweep still cut a flat list at 300, and the cut landed inside the fifth
source. Forty seven sources went unread for hours while the status page
reported healthy, because the queue was empty rather than backed up.

    python tests/test_sweep_spread.py
"""
import os
import sys
import types

for name, attrs in [
    ("redis", {"Redis": type("R", (), {"from_url": staticmethod(lambda *a, **k: None)})}),
    ("neo4j", {"GraphDatabase": type("G", (), {"driver": staticmethod(lambda *a, **k: None)})}),
    ("feedparser", {"parse": lambda *a, **k: None}),
    ("httpx", {"get": lambda *a, **k: None, "post": lambda *a, **k: None}),
]:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agents'))

import pipeline

fails = 0


def check(label, ok):
    global fails
    if not ok:
        fails += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}")


# 52 sources, 60 items each, which is what the live crawler actually returns.
docs = [{"outlet_id": f"src{s:02d}", "url": f"https://e.com/{s}/{i}"}
        for s in range(52) for i in range(60)]

kept = pipeline.interleave(docs, 300)
sources_reached = {d["outlet_id"] for d in kept}

print(f"{len(docs)} items from 52 sources, cap 300")
print(f"reached {len(sources_reached)} sources, kept {len(kept)} items")
print()

check("the cap is respected", len(kept) == 300)
check("every source is reached", len(sources_reached) == 52)
check("no source takes more than its share",
      max(sum(1 for d in kept if d["outlet_id"] == s) for s in sources_reached) <= 6)
check("the newest item of each source is taken first",
      all(f"https://e.com/{s}/0" in {d["url"] for d in kept}
          for s in range(52)))

# The old behaviour, kept here so the regression is visible.
old_kept = docs[:300]
old_reached = {d["outlet_id"] for d in old_kept}
check("the flat cut this replaced reached only 5 sources", len(old_reached) == 5)

# A cap larger than the input must not lose anything or loop forever.
small = [{"outlet_id": "a", "url": "1"}, {"outlet_id": "b", "url": "2"}]
check("a cap above the input returns everything",
      len(pipeline.interleave(small, 500)) == 2)
check("an empty list is handled", pipeline.interleave([], 100) == [])

# Uneven sources: one big, several small. The small ones must still appear.
uneven = ([{"outlet_id": "big", "url": f"b{i}"} for i in range(200)] +
          [{"outlet_id": f"small{s}", "url": f"s{s}"} for s in range(5)])
spread = pipeline.interleave(uneven, 20)
check("small sources survive beside a large one",
      len({d["outlet_id"] for d in spread}) == 6)

print()
print("all correct" if not fails else f"{fails} failures")
sys.exit(1 if fails else 0)
