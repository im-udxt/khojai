"""Manage the watchlist without Telegram.

Watches were only settable from the bot, which meant that when the bot token
was revoked the whole feature went with it. The list lives in Redis, not in
Telegram, so there is no reason it should.

    docker-compose exec -T agents python watch_cli.py list
    docker-compose exec -T agents python watch_cli.py add "Adani Ports"
    docker-compose exec -T agents python watch_cli.py remove "Adani Ports"
    docker-compose exec -T agents python watch_cli.py seed 8

seed follows the names that already appear in the most recorded links, which
is a starting point rather than a judgement about who is worth watching.
"""
import sys

import db
import watch


def show():
    items = watch.listing()
    if not items:
        print("not following anything")
        return
    print(f"following {len(items)} names")
    for item in items:
        hits = int(item.get("hits") or 0)
        print(f"   {hits:4} links   {item['name']}")


def seed(count):
    """Follow the names with the most links, skipping any already followed."""
    rows = db.query(
        "MATCH (e:Entity)-[r:CLAIM]-() "
        "WHERE e.type IN ['Person','Company','Party','Government'] "
        "WITH e, count(r) AS links WHERE links > 1 "
        "RETURN e.name AS name, links ORDER BY links DESC LIMIT $limit",
        limit=count * 3)
    added = 0
    for row in rows:
        if added >= count:
            break
        ok, message = watch.add(row["name"], note="seeded from the busiest names")
        print(("  added   " if ok else "  skipped ") + message)
        if ok:
            added += 1
    print(f"following {added} more names")


def main():
    args = sys.argv[1:]
    command = args[0] if args else "list"
    rest = " ".join(args[1:]).strip()

    if command == "list":
        show()
    elif command == "add" and rest:
        print(watch.add(rest)[1])
    elif command == "remove" and rest:
        print(watch.remove(rest)[1])
    elif command == "seed":
        seed(int(rest) if rest.isdigit() else 8)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
