#!/usr/bin/env python3
"""Fetch education history from ORCID. Best source for degree years.

Usage:
  python fetch_orcid.py --orcid 0000-0002-1825-0097
  python fetch_orcid.py --search "Lastname" "Firstname" --institution "Yale"
"""
import argparse, json, sys, time
import requests

BASE = "https://pub.orcid.org/v3.0"
H = {"Accept": "application/json"}


def search(family, given, institution=None):
    q = f"family-name:{family}+AND+given-names:{given}"
    if institution:
        q += f"+AND+affiliation-org-name:{institution}"
    r = requests.get(f"{BASE}/expanded-search/",
                     params={"q": q, "rows": 20}, headers=H, timeout=30)
    r.raise_for_status()
    out = []
    for it in r.json().get("expanded-result") or []:
        out.append({
            "orcid": it.get("orcid-id"),
            "name": f"{it.get('given-names','')} {it.get('family-names','')}".strip(),
            "institutions": it.get("institution-name") or [],
        })
    return out


def educations(orcid):
    r = requests.get(f"{BASE}/{orcid}/educations", headers=H, timeout=30)
    r.raise_for_status()
    rows = []
    for grp in r.json().get("affiliation-group") or []:
        for s in grp.get("summaries") or []:
            e = s.get("education-summary") or {}
            def yr(d):
                d = e.get(d) or {}
                y = (d or {}).get("year") or {}
                return y.get("value")
            rows.append({
                "organization": ((e.get("organization") or {}).get("name")),
                "role": e.get("role-title"),
                "department": e.get("department-name"),
                "start_year": yr("start-date"),
                "end_year": yr("end-date"),
            })
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--orcid")
    p.add_argument("--search", nargs=2, metavar=("FAMILY", "GIVEN"))
    p.add_argument("--institution")
    a = p.parse_args()
    if a.search:
        hits = search(a.search[0], a.search[1], a.institution)
        if not hits:
            print(json.dumps({"status": "no_match",
                              "note": "No ORCID record. Fall back to dissertation "
                                      "databases or ask the user for a CV."}, indent=2))
            return
        if len(hits) > 1:
            print(json.dumps({"status": "ambiguous", "candidates": hits,
                              "note": "Disambiguate by institution before proceeding."},
                             ensure_ascii=False, indent=2))
            return
        a.orcid = hits[0]["orcid"]
        print(f"# resolved to {a.orcid} ({hits[0]['name']})", file=sys.stderr)
    if not a.orcid:
        p.error("need --orcid or --search")
    time.sleep(0.2)
    print(json.dumps({"orcid": a.orcid, "educations": educations(a.orcid)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
