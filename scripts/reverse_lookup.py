#!/usr/bin/env python3
"""Reverse lookup: find a person by narrowing the pool first, then matching the name.

Searching a common name globally and then filtering by institution is unreliable —
"Yingying Li" returns medical researchers, physicists and economists, and any of
them can survive a loose institution filter.

Inverting the query is far more robust: list the authors who actually published
from this institution in this field, then look for the name inside that small pool.

Usage:
  python reverse_lookup.py --institution HKUST --field finance --mailto you@x.com
  python reverse_lookup.py --institution HKUST --field finance --name "Yingying Li"
"""
import argparse, json, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_v2 as rv

# Single source of truth for field keywords lives in resolve_v2.FIELD_HINTS —
# batch_enrich.py's field-tie-break and this reverse lookup must agree on what
# "finance" or "om" means, or the two tools would silently disagree about the
# same person.
FIELD_TOPICS = rv.FIELD_HINTS


def authors_at(institution, field, mailto=None, years=6, max_pages=8):
    """Authors with recent publications from this institution in this field."""
    inst_id, inst_name = rv.resolve_institution(institution, mailto)
    if not inst_id:
        return None, None, {}
    from datetime import date
    since = date.today().year - years
    topics = FIELD_TOPICS.get((field or "").lower(), [field or ""])
    people = defaultdict(lambda: {"name": None, "works": 0, "titles": [], "id": None})

    for topic in topics:
        cursor = "*"
        for _ in range(max_pages):
            try:
                d = rv._get("works", mailto, **{
                    "filter": (f"authorships.institutions.lineage:{inst_id},"
                               f"from_publication_date:{since}-01-01,"
                               f"default.search:{topic}"),
                    "per-page": 200, "cursor": cursor,
                    "select": "id,display_name,publication_year,authorships"})
            except Exception:
                break
            for w in d.get("results", []):
                for au in w.get("authorships") or []:
                    a = au.get("author") or {}
                    sid = rv._short_id(a)
                    if not sid:
                        continue
                    inst_hit = any(rv._short_id(i) == inst_id
                                   for i in (au.get("institutions") or []))
                    if not inst_hit:
                        continue
                    p = people[sid]
                    p["id"] = sid
                    p["name"] = a.get("display_name")
                    p["works"] += 1
                    if len(p["titles"]) < 3:
                        p["titles"].append(f"{w.get('publication_year')} {w.get('display_name')}")
            cursor = (d.get("meta") or {}).get("next_cursor")
            if not cursor:
                break
    return inst_id, inst_name, people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--field", default="finance")
    ap.add_argument("--name", help="optional: highlight matches for this person")
    ap.add_argument("--mailto"); ap.add_argument("--years", type=int, default=6)
    ap.add_argument("--out")
    a = ap.parse_args()

    inst_id, inst_name, people = authors_at(a.institution, a.field, a.mailto, a.years)
    if not inst_id:
        print(f"could not resolve institution: {a.institution}"); return
    ranked = sorted(people.values(), key=lambda p: -p["works"])
    print(f"{inst_name} ({inst_id}) — {len(ranked)} authors publishing in "
          f"'{a.field}' in the last {a.years} years\n")

    if a.name:
        toks = {t.lower() for t in rv.name_variants(a.name)[0].split()} if rv.name_variants(a.name) else set()
        hits = [p for p in ranked
                if toks and toks <= {w.lower() for w in str(p["name"]).split()}]
        loose = [p for p in ranked
                 if p not in hits and toks & {w.lower() for w in str(p["name"]).split()}]
        print(f"== exact name match: {len(hits)} ==")
        for p in hits:
            print(f"  {p['id']}  {p['name']}  ({p['works']} works here)")
            for t in p["titles"]:
                print(f"      {t[:88]}")
        if loose:
            print(f"\n== partial match: {len(loose)} ==")
            for p in loose[:10]:
                print(f"  {p['id']}  {p['name']}  ({p['works']} works here)")
        if not hits and not loose:
            print("  none — this person may publish under a different romanisation, "
                  "may not be indexed, or may not publish in this field.")
    else:
        for p in ranked[:60]:
            print(f"  {p['id']}  {str(p['name'])[:38]:<40} {p['works']} works")

    if a.out:
        json.dump(ranked, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
