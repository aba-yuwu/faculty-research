#!/usr/bin/env python3
"""Batch-enrich an entire roster from OpenAlex in one run.

Fills the fields a ranking formula actually needs — recent output, venues,
career start, coauthors — for everyone at once, so that ranking is not biased
by how much manual attention each person happened to receive.

Deliberately does NOT try to resolve every ambiguous name. Unresolved rows are
reported for manual handling rather than guessed at.

Input CSV/XLSX must contain at least: id, name, institution
Usage:
  python batch_enrich.py roster.xlsx --sheet Sheet1 --mailto you@x.com --out enriched.json
  python batch_enrich.py roster.json --mailto you@x.com --out enriched.json --since 2022
"""
import argparse, json, os, sys, time, traceback
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_openalex as oa
import resolve_v2 as rv

CACHE = ".openalex_cache.json"


def load_roster(path, sheet=None, cols=None):
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        hdr = {str(ws.cell(1, c).value).strip(): c for c in range(1, ws.max_column + 1)
               if ws.cell(1, c).value}
        cmap = cols or {}
        idc = cmap.get("id") or hdr.get("id") or 1
        nmc = cmap.get("name") or hdr.get("name") or 4
        inc = cmap.get("institution") or hdr.get("institution") or 3
        out = []
        for r in range(2, ws.max_row + 1):
            if not ws.cell(r, nmc).value:
                continue
            out.append({"id": ws.cell(r, idc).value,
                        "name": str(ws.cell(r, nmc).value),
                        "institution": str(ws.cell(r, inc).value or "")})
        return out
    return json.load(open(path, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster")
    ap.add_argument("--sheet"); ap.add_argument("--mailto")
    ap.add_argument("--out", default="enriched.json")
    ap.add_argument("--since", type=int, help="restrict works to this year onward")
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--field", default="finance",
                    help="expected field, used to break ties: finance/accounting/economics/is/om")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore .openalex_cache.json and re-fetch everyone")
    a = ap.parse_args()

    cache = ({} if a.no_cache else
             (json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}))
    roster = load_roster(a.roster, a.sheet)
    print(f"roster: {len(roster)} rows", file=sys.stderr)

    out, stats = [], Counter()
    for i, rec in enumerate(roster, 1):
        # field/since must be part of the key: changing either between runs
        # (e.g. re-running with a different --field, or a different --since
        # window) must NOT silently reuse a result computed under the old
        # settings just because name+institution match.
        key = f"{rec['name']}|{rec['institution']}|{a.field}|{a.since}"
        if key in cache:
            rec.update(cache[key]); stats["cached"] += 1; out.append(rec); continue

        # note: rv.find_author() already strips honorifics/CJK internally
        # (name_variants / _split_name), so no separate cleaning is needed here.
        try:
            cands, how = rv.find_author(rec["name"], rec["institution"], a.mailto, field=a.field)
        except Exception as e:
            rec["enrich_status"] = f"error: {e}"
            rec["error_detail"] = traceback.format_exc()[-600:]
            stats["error"] += 1; out.append(rec)
            print(f"  [{i}/{len(roster)}] ERROR      {rec['name']}  -> {type(e).__name__}: {e}",
                  file=sys.stderr)
            print(f"        {rec['error_detail'].strip().splitlines()[-3]}", file=sys.stderr)
            continue

        rec["match_method"] = how
        # "historical_institution_only" means the roster's (current, official-page)
        # institution only shows up in this author's PAST, never as the most recent
        # one on record — i.e. either the person has since moved, or the OpenAlex
        # identity is not clean. "profile_contamination_risk" means this ONE
        # OpenAlex entity's own topics span clearly unrelated fields (e.g. medicine
        # + computer science on the same ID) — a sign OpenAlex's own author
        # disambiguation has absorbed a different real person's work into this ID.
        # Institution/recency checks cannot catch this (it's not a candidate-vs-
        # candidate comparison), so it is checked separately and never auto-accepted
        # even when it is the only candidate found.
        NEEDS_REVIEW = ("name_only_unverified", "not_found")
        is_historical_only = "_historical_institution_only" in how
        is_contaminated = "_profile_contamination_risk" in how
        if len(cands) != 1 or how in NEEDS_REVIEW or is_historical_only or is_contaminated:
            if is_contaminated:
                rec["enrich_status"] = "possible_move" if is_historical_only else "needs_review_contaminated"
            elif is_historical_only:
                rec["enrich_status"] = "possible_move"
            else:
                rec["enrich_status"] = "ambiguous" if cands else "not_found"
            rec["candidates"] = [{"id": c["id"], "name": c["name"], "works": c["works"],
                                  "last_known": c["last_known"], "topics": c["topics"],
                                  "contamination_domains": c.get("contamination_domains"),
                                  "url": f"https://openalex.org/{c['id']}"}
                                 for c in cands[:5]]
            import urllib.parse as _u
            rec["verify_url"] = ("https://openalex.org/authors?search="
                                 + _u.quote(str(rec.get("name", ""))))
            stats[rec["enrich_status"]] += 1; out.append(rec)
            print(f"  [{i}/{len(roster)}] {rec['enrich_status'].upper():<10} {rec['name']}"
                  f"  ({how}, {len(cands)} cand)", file=sys.stderr)
            continue

        aid = cands[0]["id"]
        merged_info = {k: cands[0][k] for k in ("merged_ids", "merged_names", "merge_note")
                       if k in cands[0]}
        try:
            prof = oa.profile(aid, a.mailto)
            works = oa.works(aid, a.mailto, a.since)
        except Exception as e:
            rec["enrich_status"] = f"error: {e}"
            rec["error_detail"] = traceback.format_exc()[-600:]
            stats["error"] += 1; out.append(rec)
            print(f"  [{i}/{len(roster)}] ERROR      {rec['name']}  -> {type(e).__name__}: {e}",
                  file=sys.stderr)
            for ln in traceback.format_exc().strip().splitlines()[-3:]:
                print(f"        {ln.strip()}", file=sys.stderr)
            continue

        recent = [w for w in works if (w.get("year") or 0) >= (a.since or 0)]
        add = {
            "openalex_id": aid,
            "match_method": how,
            "orcid": prof.get("orcid"),
            "academic_start_year": prof.get("earliest_affiliation_year"),
            "last_known_institutions": prof.get("last_known_institutions"),
            "effective_institutions": prof.get("effective_institutions"),
            "affiliation_institutions": prof.get("affiliation_institutions"),
            "topics": prof.get("topics"),
            "counts_by_year": prof.get("counts_by_year"),
            "cited_by_count": prof.get("cited_by_count"),          # 历史总被引（非近年窗口）
            "total_works_count": prof.get("works_count"),          # OpenAlex 记录的历史发表论文总数
            "recent_works_count": len(recent),                     # since 年份起的发表数
            "recent_works": [{"title": w["title"], "year": w["year"], "venue": w["venue"],
                              "published": w["is_published"], "doi": w["doi"],
                              "url": w.get("url"), "institutions": w.get("institutions")}
                             for w in recent[:12]],
            "works": works,   # 完整列表（含 url/institutions/coauthors），供导出逐篇明细用
            "enrich_status": "ok",
            **merged_info,
        }
        rec.update(add); cache[key] = add
        stats["ok"] += 1; out.append(rec)
        print(f"  [{i}/{len(roster)}] ok         {rec['name']}  "
              f"({len(recent)} recent works, {how})", file=sys.stderr)
        time.sleep(a.sleep)
        if i % 25 == 0:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n{dict(stats)}", file=sys.stderr)
    print(f"wrote {a.out}", file=sys.stderr)
    amb = [(r["name"], r.get("enrich_status")) for r in out if r.get("enrich_status") != "ok"]
    if amb:
        print(f"\n{len(amb)} names need manual resolution (not guessed):", file=sys.stderr)
        for n, st in amb[:30]:
            print(f"  - {n}  [{st}]", file=sys.stderr)


if __name__ == "__main__":
    main()
