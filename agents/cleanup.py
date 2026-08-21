"""Remove names that the current rules would never have stored.

The rules for what counts as a name got stricter after sentence fragments
turned up in the graph as nodes: "ten persons including Sachin Waze and
others", "for Roads and Buildings", "Union Home Affairs Ministry, Union
Ministry of Corporate Affairs". New ones cannot get in any more, but the ones
already stored stay until something removes them.

This reports first and changes nothing unless asked:

    docker-compose exec -T agents python cleanup.py            # report only
    docker-compose exec -T agents python cleanup.py --apply    # remove them

Removing a name also removes the links attached to it, so take a backup
first with scripts/backup.sh. The quote and the source url of a removed link
are gone from the graph, though the article itself is still in the archive.
"""
import sys

import db
import entities


def doomed():
    """Every stored name the current rules would reject, with its cost."""
    rows = db.query(
        "MATCH (e:Entity) "
        "OPTIONAL MATCH (e)-[r:CLAIM]-() "
        "RETURN e.uid AS uid, e.name AS name, e.type AS type, "
        "       count(r) AS links "
        "ORDER BY links DESC")
    out = []
    for row in rows:
        if entities.canonical(row["name"]) is None:
            out.append(row)
    return out


def run(apply=False):
    rows = doomed()
    if not rows:
        print("nothing to remove, every stored name still passes the rules")
        return

    links = sum(r["links"] for r in rows)
    print(f"{len(rows)} names would be removed, taking {links} links with them")
    print()
    for row in rows[:40]:
        print(f"   {row['links']:4} links  {row['type']:11} {row['name'][:70]}")
    if len(rows) > 40:
        print(f"   and {len(rows) - 40} more")

    if not apply:
        print()
        print("nothing was changed. run with --apply to remove them.")
        return

    removed = 0
    for row in rows:
        try:
            db.query("MATCH (e:Entity {uid:$uid}) DETACH DELETE e", uid=row["uid"])
            removed += 1
        except Exception as exc:
            print(f"could not remove {row['name'][:40]}: {str(exc)[:80]}")
    db.activity("cleanup", f"removed {removed} names that are not names")
    print()
    print(f"removed {removed} names and the links attached to them")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
