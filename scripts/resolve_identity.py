#!/usr/bin/env python3
"""Resolve a name+institution to stable IDs, reporting ambiguity rather than guessing.

Identity resolution is the largest single error source in faculty research.
This script never picks a winner when the evidence is thin — it reports.

Cross-checks OpenAlex against ORCID independently; when both single-candidate
resolutions agree, that is strong evidence. Uses the same resolver
(resolve_v2.find_author) as the batch pipeline — institution-ID filtering,
recency ("current" vs "historical" affiliation) checks, the clean-profile
heuristic, and profile-contamination detection all apply here too, so a
one-off check and a batch run never disagree on the same person.

Usage: python resolve_identity.py --name "Jane Doe" --institution "Yale" --mailto you@x.com
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_v2 as rv
import fetch_orcid as orc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--institution")
    ap.add_argument("--field", help="e.g. finance — helps break ties among candidates")
    ap.add_argument("--mailto")
    ap.add_argument("--api-key", help="OpenAlex API key (required since Feb 2026 — "
                                      "free at https://openalex.org/settings/api)")
    a = ap.parse_args()
    rv.API_KEY = a.api_key

    result = {"query": {"name": a.name, "institution": a.institution, "field": a.field}}
    try:
        cands, how = rv.find_author(a.name, a.institution, a.mailto, field=a.field)
        result["openalex"] = {"how": how, "candidates": cands[:10]}
        result["openalex_id"] = cands[0]["id"] if len(cands) == 1 else None
    except Exception as e:
        result["openalex"] = {"error": str(e)}

    parts = a.name.split()
    if len(parts) >= 2:
        try:
            hits = orc.search(parts[-1], parts[0], a.institution)
            result["orcid"] = {"candidates": hits[:10]}
            result["orcid_id"] = hits[0]["orcid"] if len(hits) == 1 else None
        except Exception as e:
            result["orcid"] = {"error": str(e)}

    resolved = bool(result.get("openalex_id") or result.get("orcid_id"))
    result["status"] = "resolved" if resolved else "ambiguous_or_absent"
    if not resolved:
        result["note"] = ("Do not proceed on a guess. Add department or research field, "
                          "or ask the user for an ORCID / personal page. Common surnames "
                          "cannot be resolved by name alone.")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
