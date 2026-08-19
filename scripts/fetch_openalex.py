#!/usr/bin/env python3
"""Fetch works, coauthors, affiliation timeline and yearly output from OpenAlex.

Affiliation year-ranges give the academic start year; counts_by_year reveals
output slowdowns that a static publication list hides.

Usage:
  python fetch_openalex.py --name "Jane Doe" --institution "Yale" --mailto you@x.com
  python fetch_openalex.py --author-id A5023888391 --mailto you@x.com
"""
import argparse, json, sys, time
import requests

BASE = "https://api.openalex.org"

# OpenAlex made API keys mandatory for all requests starting Feb 13, 2026 (the old
# mailto-based "polite pool" is retired). Without a key you get ~100 free demo
# credits/day, then every request fails — and no amount of waiting fixes that,
# since it isn't a per-second rate limit, it's a missing credential. Set once by
# each script's main() after parsing --api-key, read automatically by _get() —
# a module-level credential rather than threading a new parameter through the
# dozens of functions that already pass `mailto` around, which would be a much
# larger, more error-prone change for the same effect. Get a free key at
# https://openalex.org/settings/api (an OpenAlex account, ~30 seconds).
API_KEY = None


def short_id(obj):
    """OpenAlex ids are URLs, and some records carry a null id. Never assume."""
    v = obj if isinstance(obj, str) else (obj or {}).get("id")
    return v.rsplit("/", 1)[-1] if isinstance(v, str) and v else None


def _get(path, mailto, **params):
    """GET with a short retry/backoff for rate limits and transient errors —
    see resolve_v2._get for why this matters even for a single failed call."""
    if mailto:
        params["mailto"] = mailto
    if API_KEY:
        params["api_key"] = API_KEY
    last_exc = None
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE}/{path}", params=params, timeout=45)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (2 ** attempt))
                continue
            r.raise_for_status()
            time.sleep(0.15)
            return r.json()
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(1.5 * (2 ** attempt))
    raise last_exc or RuntimeError(f"OpenAlex request failed after retries: {path}")


def profile(author_id, mailto):
    a = _get(f"authors/{author_id}", mailto)
    affil = []
    for x in a.get("affiliations") or []:
        affil.append({"institution": (x.get("institution") or {}).get("display_name"),
                      "years": sorted(x.get("years") or [])})
    counts = {c["year"]: {"works": c["works_count"], "cites": c["cited_by_count"]}
              for c in a.get("counts_by_year") or []}
    academic_start = min([min(x["years"]) for x in affil if x["years"]], default=None)
    all_insts = [x["institution"] for x in affil if x.get("institution")]
    last = [i.get("display_name") for i in (a.get("last_known_institutions") or [])]
    # last_known_institutions is frequently empty even when the affiliation history is
    # populated; fall back so downstream display never looks like "no institution".
    effective = last or all_insts[:3]
    return {
        "id": author_id,
        "name": a.get("display_name"),
        "orcid": a.get("orcid"),
        "works_count": a.get("works_count"),
        "cited_by_count": a.get("cited_by_count"),
        "last_known_institutions": last,
        "affiliation_institutions": all_insts,
        "effective_institutions": effective,
        "affiliations": affil,
        "earliest_affiliation_year": academic_start,
        "counts_by_year": counts,
        "topics": [t.get("display_name") for t in (a.get("topics") or [])[:10]],
    }


def works(author_id, mailto, since=None, limit=200):
    """Fetch up to `limit` works (single page — OpenAlex's per-page max is 200,
    so a professor with more than 200 papers within the `since` window would
    still be truncated; that's rare enough in practice not to warrant full
    cursor pagination here, unlike reverse_lookup.py's institution-wide scan).
    """
    f = f"author.id:{author_id}"
    if since:
        f += f",from_publication_date:{since}-01-01"
    # NOTE: OpenAlex's actual parameter name is "per-page" (hyphen), which
    # can't be written as a Python keyword argument — passing per_page=...
    # instead silently sends a parameter OpenAlex doesn't recognise, and it
    # falls back to its own default page size (25) with no error. Must go
    # through **{"per-page": ...} like every other _get call in this project.
    d = _get("works", mailto, **{"filter": f, "per-page": min(limit, 200),
                                 "sort": "publication_year:desc"})
    out = []
    for w in d.get("results", []):
        wid = short_id(w)
        # Find THIS author's own authorship entry to read the institution(s) they
        # were affiliated with on THIS specific paper — not their current/overall
        # institution, which can differ from a paper written years ago.
        my_insts, coauthors = [], []
        for au in w.get("authorships") or []:
            au_id = short_id(au.get("author"))
            au_name = (au.get("author") or {}).get("display_name")
            if au_id == author_id:
                my_insts = [i.get("display_name") for i in (au.get("institutions") or [])
                           if i.get("display_name")]
            else:
                coauthors.append({"id": au_id, "name": au_name})
        out.append({
            "id": wid,
            "url": f"https://openalex.org/{wid}" if wid else None,
            "title": w.get("display_name"),
            "year": w.get("publication_year"),
            "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            # issn_l is the "linking ISSN" OpenAlex normalizes electronic/print
            # variants to; fall back to the first entry in the source's raw
            # issn list when issn_l is absent. Kept alongside venue name so a
            # future ISSN-based exact match (see journal_ranking_feature_handoff.md
            # §3) doesn't need a second OpenAlex round-trip.
            "venue_issn": (((w.get("primary_location") or {}).get("source") or {}).get("issn_l")
                          or (((w.get("primary_location") or {}).get("source") or {}).get("issn") or [None])[0]),
            "topics": [t.get("display_name") for t in (w.get("topics") or [])[:5]],
            # Additive, backward-compatible: "topics" above stays a flat list of
            # strings exactly as before (journal_ranking.py's _paper_text() and
            # anything else already reading it is untouched). topics_detail keeps
            # the subfield/field labels OpenAlex's own topic classifier already
            # assigns each topic — a curated taxonomy (~4,500 topics under ~250
            # subfields under 26 fields), not something this project computes.
            # Exists so advisor_recommend.py can match a stated research interest
            # against a paper's OpenAlex-assigned discipline label, not just its
            # title text — catches papers whose title never spells out the field
            # name but whose OpenAlex classification does. See
            # references/advisor-recommendation-design.md §2.
            "topics_detail": [
                {"topic": t.get("display_name"),
                 "subfield": (t.get("subfield") or {}).get("display_name"),
                 "field": (t.get("field") or {}).get("display_name"),
                 "score": t.get("score")}
                for t in (w.get("topics") or [])[:5]
            ],
            "type": w.get("type"),
            "doi": w.get("doi"),
            "is_published": (w.get("type") == "article"
                             and ((w.get("primary_location") or {}).get("source") is not None)),
            "institutions": my_insts,          # this author's affiliation ON this paper
            "coauthors": coauthors,             # everyone else on the paper
        })
    return out


def main():
    import os, sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import resolve_v2 as rv   # same resolver batch_enrich.py uses — institution-ID

    p = argparse.ArgumentParser()
    p.add_argument("--name"); p.add_argument("--institution")
    p.add_argument("--author-id"); p.add_argument("--mailto")
    p.add_argument("--api-key", help="OpenAlex API key (required since Feb 2026 — "
                                     "free at https://openalex.org/settings/api)")
    p.add_argument("--field", help="e.g. finance — helps break ties among candidates")
    p.add_argument("--since", help="YYYY, restrict works")
    a = p.parse_args()
    global API_KEY
    API_KEY = a.api_key
    rv.API_KEY = a.api_key
    if not a.author_id:
        if not a.name:
            p.error("need --name or --author-id")
        cands, how = rv.find_author(a.name, a.institution, a.mailto, field=a.field)
        if len(cands) != 1:
            print(json.dumps({"status": "ambiguous", "how": how, "candidates": cands[:10],
                              "note": "Resolve by institution/topic before proceeding. "
                                      "Do not guess."}, ensure_ascii=False, indent=2))
            return
        a.author_id = cands[0]["id"]
        print(f"# resolved to {a.author_id} ({how})", file=sys.stderr)
    prof = profile(a.author_id, a.mailto)
    prof["works"] = works(a.author_id, a.mailto, a.since)
    print(json.dumps(prof, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
