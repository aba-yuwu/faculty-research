#!/usr/bin/env python3
"""Generate browser URLs for manual verification on OpenAlex.

The web UI is hard to drive by hand for this task; these URLs land directly on a
filtered author list so a human can confirm an identity in seconds.

Usage:
  python openalex_links.py --name "Yingying Li" --institution HKUST
  python openalex_links.py --roster enriched.json > links.md              # all non-ok rows
  python openalex_links.py --roster enriched.json --status possible_move  # one status only
"""
import argparse, json, sys, urllib.parse
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import resolve_v2 as rv


def links(name, institution, mailto=None):
    inst_id, inst_name = rv.resolve_institution(institution, mailto)
    variants = rv.name_variants(name)
    q = urllib.parse.quote(variants[0] if variants else name)
    out = {"name": name, "institution": institution,
           "resolved_institution": inst_name, "institution_id": inst_id,
           "name_variants": variants}
    if inst_id:
        out["authors_at_institution"] = (
            f"https://openalex.org/authors?page=1&filter=display_name.search%3A{q},"
            f"affiliations.institution.id%3A{inst_id}")
        out["all_authors_at_institution"] = (
            f"https://openalex.org/institutions/{inst_id}")
        out["api_check"] = (
            f"https://api.openalex.org/authors?filter=display_name.search:{q},"
            f"affiliations.institution.id:{inst_id}")
    out["name_only"] = f"https://openalex.org/authors?page=1&filter=display_name.search%3A{q}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name"); ap.add_argument("--institution")
    ap.add_argument("--roster")
    ap.add_argument("--status", help="filter to one status/method prefix "
                                     "(e.g. possible_move); omit for ALL non-ok rows")
    ap.add_argument("--mailto")
    a = ap.parse_args()
    if a.roster:
        data = json.load(open(a.roster, encoding="utf-8"))
        if a.status:
            # explicit filter: one status or match_method prefix only
            rows = [r for r in data if str(r.get("enrich_status", "")).startswith(a.status)
                    or str(r.get("match_method", "")).startswith(a.status)]
        else:
            # default: everything that isn't "ok" needs a human look — matches the
            # same "not ok" rule merge_to_excel.py uses, so this report and the
            # xlsx's "待人工确认" count always agree on how many rows that is.
            rows = [r for r in data if r.get("enrich_status") != "ok"]
        print(f"# 待人工确认 {len(rows)} 位\n")
        for r in rows:
            L = links(r.get("name"), r.get("institution"), a.mailto)
            print(f"## {r.get('name')}  ({r.get('institution')})  "
                 f"[{r.get('enrich_status')} / {r.get('match_method')}]")
            print(f"- 解析到的机构：{L.get('resolved_institution')}  `{L.get('institution_id')}`")
            print(f"- 尝试过的姓名：{', '.join(L['name_variants'])}")
            if L.get("authors_at_institution"):
                print(f"- **在该机构内按姓名查**：{L['authors_at_institution']}")
            print(f"- 仅按姓名查（会有同名他人）：{L['name_only']}")
            for c in (r.get("candidates") or [])[:5]:
                print(f"    - 候选 `{c.get('id')}` {c.get('name')} | {c.get('works')}篇 "
                      f"| {c.get('last_known')} | {(c.get('topics') or [])[:3]}")
            print()
    else:
        print(json.dumps(links(a.name, a.institution, a.mailto), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
