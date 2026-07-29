#!/usr/bin/env python3
"""Consistency checks. Run after every batch.

Catches: profile links pointing at other institutions, placeholder rows,
non-numeric numeric columns, orphaned markers, contaminated topic sets,
and prestige-without-recency.

Usage: python audit_dataset.py roster.json [--domains domains.json]
"""
import argparse, json, re
from collections import Counter

PERSONAL_HOSTS = ("sites.google.com", "github.io", "wordpress.", "weebly.",
                  "scholar.harvard.edu", "sites.harvard.edu", "notion.")
PLACEHOLDER = re.compile(r"^\s*(近三年|无|暂无|未检索|未见|待核实|待补|N/?A|nan|[-—])\s*$", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster"); ap.add_argument("--domains")
    ap.add_argument("--now", type=int, default=2026)
    a = ap.parse_args()
    roster = json.load(open(a.roster, encoding="utf-8"))
    dom = json.load(open(a.domains, encoding="utf-8")) if a.domains else {}
    issues = []

    for r in roster:
        rid, name = r.get("id"), r.get("name")

        url = (r.get("profile_url") or "").lower()
        inst = r.get("institution")
        if url.startswith("http") and inst in dom:
            if not any(k in url for k in dom[inst]) and \
               not any(h in url for h in PERSONAL_HOSTS):
                issues.append({"type": "link_institution_mismatch", "id": rid, "name": name,
                               "detail": f"{inst} but URL is {url[:70]}"})

        for p in r.get("papers") or []:
            if p.get("title") and PLACEHOLDER.match(p["title"].strip()):
                issues.append({"type": "placeholder_row", "id": rid, "name": name,
                               "detail": f"title={p['title']!r} venue={p.get('venue_year')!r}"})

        for k in ("phd_year", "bachelor_year", "years_since_phd", "estimated_age"):
            v = r.get(k)
            if v is not None and not isinstance(v, (int, float)):
                issues.append({"type": "non_numeric_in_numeric_column", "id": rid,
                               "name": name, "detail": f"{k}={v!r}"})

        yrs = [int(y) for p in r.get("papers") or []
               for y in re.findall(r"(20\d{2})", str(p.get("venue_year") or ""))]
        if yrs and max(yrs) < a.now - 3 and r.get("bonus_flag") == 1:
            issues.append({"type": "prestige_without_recency", "id": rid, "name": name,
                           "detail": f"bonus granted but newest entry is {max(yrs)}"})

        topics = [t.lower() for t in (r.get("topics") or [])]
        off = [t for t in topics if re.search(
            r"oncol|cardio|surg|clinic|patient|gene|protein|alloy|corrosion|semiconduct", t)]
        if off and len(off) >= 2:
            issues.append({"type": "possible_profile_contamination", "id": rid, "name": name,
                           "detail": f"off-field topics: {off[:4]}"})

        if r.get("marker") and not r.get("name"):
            issues.append({"type": "orphan_marker", "id": rid, "name": name, "detail": ""})

    print(json.dumps({"total_records": len(roster), "issue_count": len(issues),
                      "by_type": Counter(i["type"] for i in issues), "issues": issues},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
