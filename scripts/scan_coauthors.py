#!/usr/bin/env python3
"""Detect co-authorship within a roster by title/DOI match, not surname match.

Surname matching produces overwhelming false positives on rosters with Chinese,
Korean or Indian names. This script requires a shared work identifier.

Input JSON: [{"id":1,"name":"...","openalex_id":"A123","works":[{"id":"W1",
             "title":"...","year":2024,"doi":"..."}]}, ...]

Usage: python scan_coauthors.py roster.json --min-year 2000 > edges.json
"""
import argparse, json, re
from collections import defaultdict
from itertools import combinations

MASS_AUTHOR_HINTS = re.compile(
    r"non-?standard errors|many analysts|replication (game|project)|crowdsourc", re.I)


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster")
    ap.add_argument("--min-year", type=int, default=0)
    ap.add_argument("--max-authors", type=int, default=25,
                    help="skip works above this author count (mass collaborations)")
    a = ap.parse_args()
    roster = json.load(open(a.roster, encoding="utf-8"))

    # index each roster member's works by the strongest available key
    idx = defaultdict(set)          # key -> {member_id}
    meta = {}                       # key -> (title, year)
    for m in roster:
        for w in m.get("works") or []:
            if (w.get("year") or 0) < a.min_year:
                continue
            if MASS_AUTHOR_HINTS.search(w.get("title") or ""):
                continue
            if len(w.get("coauthors") or []) > a.max_authors:
                continue
            key = (w.get("doi") or w.get("id") or norm_title(w.get("title")))
            if not key:
                continue
            idx[key].add(m["id"])
            meta[key] = (w.get("title"), w.get("year"))

    pairs = defaultdict(list)
    for key, ids in idx.items():
        if len(ids) < 2:
            continue
        for x, y in combinations(sorted(ids), 2):
            pairs[(x, y)].append({"key": key, "title": meta[key][0], "year": meta[key][1]})

    names = {m["id"]: m["name"] for m in roster}
    edges = []
    for (x, y), works in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
        edges.append({
            "source": x, "target": y,
            "source_name": names.get(x), "target_name": names.get(y),
            "weight": len(works),
            "evidence": works,
        })
    print(json.dumps({"edges": edges,
                      "note": "Every edge is backed by a shared work identifier. "
                              "No surname-only matches are included."},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
