"""One off migration: give every name a single node.

Node ids used to include the entity type, so a name whose type changed became
a second node and its links were split between the two. Ids now come from the
name alone. This merges any existing duplicates onto the new id and refreshes
the type, keeping the stored type unless the rules clearly say otherwise.

    docker-compose exec -T agents python retype.py
"""
import db
import entities


def run():
    rows = db.query(
        "MATCH (e:Entity) RETURN e.uid AS uid, e.name AS name, "
        "e.key AS key, e.type AS type, coalesce(e.mentions,0) AS mentions")
    merged = retyped = 0
    for row in rows:
        # Pass the stored type as the hint so a name keeps it unless a rule
        # such as the party list overrides it.
        fresh = entities.canonical(row["name"], row.get("type"))
        if not fresh:
            continue
        target = fresh["uid"]
        if target != row["uid"]:
            db.query("""
                MATCH (old:Entity {uid:$old})
                MERGE (new:Entity {uid:$new})
                ON CREATE SET new.name=$name, new.key=$key, new.type=$type,
                              new.first_seen=old.first_seen, new.mentions=0,
                              new.aliases=coalesce(old.aliases,[$name])
                SET new.last_seen=coalesce(new.last_seen, old.last_seen),
                    new.mentions=coalesce(new.mentions,0)+$mentions
            """, old=row["uid"], new=target, name=fresh["name"],
                key=fresh["key"], type=fresh["type"], mentions=row["mentions"])
            db.query("""
                MATCH (old:Entity {uid:$old})-[r:CLAIM]->(b:Entity)
                MATCH (new:Entity {uid:$new})
                WHERE b.uid <> $new
                MERGE (new)-[nr:CLAIM {relation:r.relation, source_url:r.source_url}]->(b)
                SET nr.quote=r.quote, nr.outlet=r.outlet, nr.created=r.created,
                    nr.published=r.published, nr.last_seen=r.last_seen
            """, old=row["uid"], new=target)
            db.query("""
                MATCH (a:Entity)-[r:CLAIM]->(old:Entity {uid:$old})
                MATCH (new:Entity {uid:$new})
                WHERE a.uid <> $new
                MERGE (a)-[nr:CLAIM {relation:r.relation, source_url:r.source_url}]->(new)
                SET nr.quote=r.quote, nr.outlet=r.outlet, nr.created=r.created,
                    nr.published=r.published, nr.last_seen=r.last_seen
            """, old=row["uid"], new=target)
            db.query("MATCH (old:Entity {uid:$old}) DETACH DELETE old", old=row["uid"])
            merged += 1
        elif fresh["type"] != row["type"]:
            db.query("MATCH (e:Entity {uid:$uid}) SET e.type=$type",
                     uid=row["uid"], type=fresh["type"])
            retyped += 1
    print(f"checked {len(rows)} names, merged {merged} onto a single id, "
          f"re-typed {retyped} in place")


if __name__ == "__main__":
    run()
