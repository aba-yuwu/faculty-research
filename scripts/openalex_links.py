#!/usr/bin/env python3
"""Generate browser URLs for manual verification on OpenAlex.

The web UI is hard to drive by hand for this task; these URLs land directly on a
filtered author list so a human can confirm an identity in seconds.

Usage:
  python openalex_links.py --name "Yingying Li" --institution HKUST
  python openalex_links.py --roster enriched.json --out 待人工确认.md    # all non-ok rows
  python openalex_links.py --roster enriched.json > links.md              # shell redirect also works
  python openalex_links.py --roster enriched.json --status possible_move  # one status only

--out writes the report to a file directly (needed when this is run through a
wrapper that streams stdout for live progress rather than capturing it for shell
redirection — e.g. a notebook cell using Popen to show real-time output; ">
file.md" from that context never actually creates the file, since nothing
captures the child process's stdout to redirect). Content still prints to
stdout either way, so live progress is visible regardless of whether --out is
used.
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
    ap.add_argument("--api-key", help="OpenAlex API key (required since Feb 2026 — "
                                      "free at https://openalex.org/settings/api)")
    ap.add_argument("--out", help="write the report to this file directly, instead of "
                                  "relying on shell '>' redirection to capture stdout")
    a = ap.parse_args()
    rv.API_KEY = a.api_key

    buf = []
    def emit(line=""):
        print(line)     # still visible live (e.g. via a notebook's streaming wrapper)
        buf.append(line)

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
        emit(f"# 待人工确认 {len(rows)} 位\n")
        for r in rows:
            L = links(r.get("name"), r.get("institution"), a.mailto)
            emit(f"## {r.get('name')}  ({r.get('institution')})  "
                f"[{r.get('enrich_status')} / {r.get('match_method')}]")
            emit(f"- 解析到的机构：{L.get('resolved_institution')}  `{L.get('institution_id')}`")
            emit(f"- 尝试过的姓名：{', '.join(L['name_variants'])}")
            if L.get("authors_at_institution"):
                emit(f"- **在该机构内按姓名查**：{L['authors_at_institution']}")
            emit(f"- 仅按姓名查（会有同名他人）：{L['name_only']}")
            for c in (r.get("candidates") or [])[:5]:
                emit(f"    - 候选 `{c.get('id')}` {c.get('name')} | {c.get('works')}篇 "
                    f"| {c.get('last_known')} | {(c.get('topics') or [])[:3]}")
            emit()
    else:
        emit(json.dumps(links(a.name, a.institution, a.mailto), ensure_ascii=False, indent=2))

    if a.out:
        open(a.out, "w", encoding="utf-8").write("\n".join(buf) + "\n")
        print(f"\nwrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
