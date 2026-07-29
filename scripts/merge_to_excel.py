#!/usr/bin/env python3
"""Write enrichment results into a NEW workbook. The original is never modified.

Appends columns rather than overwriting existing ones, so manually curated
assessments survive. Every appended column is prefixed so provenance is obvious.

Also writes a second sheet, "论文明细", with ONE ROW PER PAPER (title, this
author's institution on that specific paper, a link, and coauthors) — a roster
row only has room for a compact preview of recent work, but downstream use
(coauthor network analysis, checking a specific claim) needs the full list.

Usage:
  python merge_to_excel.py original.xlsx enriched.json --sheet 全部教授_论文与聚焦度 \
      --out enriched_output.xlsx
"""
import argparse, json, re, shutil, os, sys
from datetime import date
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_v2 as rv   # reuse the SAME alias table / resolver batch_enrich.py
                          # already used to find these candidates, instead of
                          # reinventing a weaker raw-substring check here.

# NOTE: "近年" here means "since whatever --since year batch_enrich.py was run
# with" (see recent_works_count / recent_works in the enriched JSON) — it is
# NOT hardcoded to a fixed 3-year window, despite what an earlier version of
# this column's name implied.
NEW_COLS = [
    ("OA_匹配状态", "enrich_status"),
    ("OA_匹配方式", "match_method"),
    ("OA_机构时效性", None),          # current(现任) / historical(仅历史上出现过) / — (无年份数据)
    ("OA_作者ID", "openalex_id"),
    ("OA_ORCID", "orcid"),
    ("OA_当前机构", None),
    ("OA_任教起始年", "academic_start_year"),
    ("OA_被引总数(历史总计)", "cited_by_count"),
    ("OA_发表论文总数(历史总计)", "total_works_count"),
    ("OA_近年发表数", None),
    ("OA_近年正式发表数", None),
    ("OA_最新发表年", None),
    ("OA_近年论文清单(标题/机构/链接见「论文明细」表)", None),
    ("OA_研究主题", None),
    ("OA_机构是否不一致", None),
    ("OA_候选人(需人工确认)", None),
    ("OA_合并记录说明", None),
    ("OA_可信度分", None),
    ("OA_可信度等级", None),
    ("OA_建议动作", None),
    ("OA_可信度依据", None),
]
WRAP_COLS = (12, 15, 16, 20)   # 0-based positions in vals[] that need wrap_text
WIDE_COLS = {12: 60, 15: 45, 20: 70}

PAPER_COLS = ["教授姓名", "名单机构", "论文标题", "发表年份", "期刊/会议",
             "该作者当次所属机构", "文章链接", "DOI", "合作者"]


def _norm_inst(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _institution_mismatch(inst_sheet, last, mailto=None):
    """Does `last` (this author's OpenAlex institution names) actually include
    the roster's institution?

    A raw substring test on the roster's raw text fails whenever the roster
    uses an acronym ("HKU") that never appears verbatim inside OpenAlex's full
    canonical name ("University of Hong Kong") — that check would flag a
    correct match as a mismatch. Resolve the roster string through the SAME
    alias table / resolver used to find this candidate in the first place
    (resolve_v2.resolve_institution — checks the local alias file before ever
    touching the network, and since batch_enrich.py already resolved every
    institution in this roster, this almost always hits that local cache).
    """
    if not inst_sheet or not last:
        return False
    try:
        _, canonical = rv.resolve_institution(inst_sheet, mailto)
    except Exception:
        canonical = None
    targets = {_norm_inst(canonical)} if canonical else set()
    targets.add(_norm_inst(inst_sheet))       # also allow a literal/raw match
    targets.discard("")
    for x in last:
        nx = _norm_inst(x)
        if not nx:
            continue
        if nx in targets or any(t and (t in nx or nx in t) for t in targets):
            return False    # a match was found — NOT a mismatch
    return True


def _write_roster_sheet(wb, ws, data, a):
    norm = lambda s: re.sub(r"\s+", "", str(s or "")).lower()
    # Key on (name, institution), not name alone: a roster with two different
    # people who share a name (common with frequent Chinese surnames) would
    # otherwise have the later one's enrichment silently overwrite the
    # earlier one's in this dict, and BOTH rows would then be merged with
    # whichever one happened to load last.
    by_name_inst = {(norm(r.get("name")), norm(r.get("institution"))): r for r in data}
    # Fallback for the (rare) case a name doesn't reduce to a unique
    # (name, institution) pair here but is otherwise unambiguous in `data`.
    by_name_only = {}
    for r in data:
        k = norm(r.get("name"))
        by_name_only[k] = None if k in by_name_only else r
    start = ws.max_column + 1
    BASE = Font(name="微软雅黑", size=9)
    for j, (title, _) in enumerate(NEW_COLS):
        c = ws.cell(1, start + j)
        c.value = title
        c.font = Font(name="微软雅黑", size=9, bold=True)
        c.fill = PatternFill("solid", fgColor="FFE7F0D9")
    for j, w in WIDE_COLS.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(start + j)].width = w

    n_ok = n_amb = n_moved = n_contaminated = 0
    for r in range(2, ws.max_row + 1):
        nm = ws.cell(r, a.name_col).value
        if not nm:
            continue
        inst_sheet_raw = str(ws.cell(r, a.inst_col).value or "")
        rec = by_name_inst.get((norm(nm), norm(inst_sheet_raw))) or by_name_only.get(norm(nm))
        if not rec:
            continue
        works = rec.get("recent_works") or []
        years = [w["year"] for w in works if w.get("year")]
        inst_sheet = inst_sheet_raw
        # effective_institutions already falls back to affiliation history when
        # OpenAlex's own last_known_institutions is empty (which it frequently is,
        # even for authors with a full affiliation record) — using the raw
        # last_known_institutions field alone silently shows "[]" for such rows.
        last = (rec.get("effective_institutions") or rec.get("last_known_institutions")
                or rec.get("affiliation_institutions") or [])
        method = str(rec.get("match_method") or "")
        if "_historical_institution_only" in method:
            timeliness = "historical（仅历史上出现过，可能已转校，需核实）"
        elif "current" in method:
            timeliness = "current（最近一次隶属）"
        elif method in ("name_only_unverified", "not_found"):
            timeliness = "—"
        else:
            timeliness = "unknown（无机构年份数据，无法判断时效性）"
        if "_profile_contamination_risk" in method:
            timeliness += " ⚠️疑似身份污染（该ID论文跨越不相关学科，可能混入他人成果）"
        mismatch = ""
        if rec.get("enrich_status") == "ok" and last and inst_sheet:
            if _institution_mismatch(inst_sheet, last, a.mailto):
                mismatch = "⚠ 需核实"
                n_moved += 1
        rel = rec.get("reliability") or {}
        vals = [
            rec.get("enrich_status"),
            rec.get("match_method"),
            timeliness,
            rec.get("openalex_id"),
            rec.get("orcid"),
            "；".join(map(str, last)),
            rec.get("academic_start_year"),
            rec.get("cited_by_count"),
            rec.get("total_works_count"),
            rec.get("recent_works_count", len(works)),
            sum(1 for w in works if w.get("published")),
            max(years) if years else None,
            " || ".join(f"{w.get('year')} {w.get('venue') or '—'} | {str(w.get('title'))[:60]}"
                        f"{' | ' + '/'.join(w.get('institutions') or []) if w.get('institutions') else ''}"
                        for w in works[:8]),
            "；".join((rec.get("topics") or [])[:6]),
            mismatch,
            "；".join(f"{c.get('name')}({c.get('works')}篇,{'/'.join(map(str,c.get('last_known') or []))[:28]})"
                     for c in (rec.get("candidates") or [])[:4]),
            ("合并了 " + " + ".join(rec.get("merged_names") or []) + f"（共{len(rec.get('merged_ids') or [])}条记录）")
            if rec.get("merged_ids") else "",
            rel.get("confidence"),
            rel.get("level"),
            rel.get("action"),
            "；".join((rel.get("reasons") or []) + (rel.get("flags") or [])),
        ]
        for j, v in enumerate(vals):
            cell = ws.cell(r, start + j)
            cell.value = v
            cell.font = BASE
            cell.alignment = Alignment(wrap_text=(j in WRAP_COLS), vertical="top")
        if rec.get("enrich_status") == "ok":
            n_ok += 1
        elif rec.get("enrich_status"):
            # Anything that isn't "ok" needs a human look — count it here rather
            # than maintaining a hardcoded status list that drifts out of sync
            # with batch_enrich.py every time a new status is added.
            n_amb += 1
            if rec.get("enrich_status") == "needs_review_contaminated":
                n_contaminated += 1
    return n_ok, n_amb, n_moved, n_contaminated


def _write_papers_sheet(wb, data, a):
    """One row per paper across every enriched roster member: title, this
    author's own institution ON that paper, a link, and coauthors — the detail
    a single roster row has no room for.
    """
    ws2 = wb.create_sheet("论文明细")
    BASE = Font(name="微软雅黑", size=9)
    for j, title in enumerate(PAPER_COLS, start=1):
        c = ws2.cell(1, j)
        c.value = title
        c.font = Font(name="微软雅黑", size=9, bold=True)
        c.fill = PatternFill("solid", fgColor="FFE7F0D9")
    for col, width in ((3, 55), (5, 30), (6, 30), (7, 40), (9, 45)):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

    r = 2
    n_papers = 0
    for rec in data:
        works = rec.get("works")
        if not works:
            continue
        roster_inst = rec.get("institution") or ""
        for w in works:
            coauthors = "；".join(c.get("name") for c in (w.get("coauthors") or [])
                                 if c.get("name"))
            row = [
                rec.get("name"),
                roster_inst,
                w.get("title"),
                w.get("year"),
                w.get("venue"),
                "；".join(w.get("institutions") or []),
                w.get("url"),
                w.get("doi"),
                coauthors,
            ]
            for j, v in enumerate(row, start=1):
                cell = ws2.cell(r, j)
                cell.value = v
                cell.font = BASE
                cell.alignment = Alignment(wrap_text=(j in (3, 9)), vertical="top")
            r += 1
            n_papers += 1
    return n_papers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original"); ap.add_argument("enriched")
    ap.add_argument("--sheet"); ap.add_argument("--out")
    ap.add_argument("--name-col", type=int, default=4)
    ap.add_argument("--inst-col", type=int, default=3)
    ap.add_argument("--mailto", help="only used if an institution isn't already "
                                     "in the local alias cache from batch_enrich.py")
    a = ap.parse_args()

    out = a.out or f"{os.path.splitext(a.original)[0]}_OA补全_{date.today().isoformat()}.xlsx"
    if os.path.abspath(out) == os.path.abspath(a.original):
        raise SystemExit("refusing to overwrite the original file")
    shutil.copy(a.original, out)          # work on a copy; original untouched

    wb = openpyxl.load_workbook(out)
    ws = wb[a.sheet] if a.sheet and a.sheet in wb.sheetnames else wb.active
    data = json.load(open(a.enriched, encoding="utf-8"))

    n_ok, n_amb, n_moved, n_contaminated = _write_roster_sheet(wb, ws, data, a)
    n_papers = _write_papers_sheet(wb, data, a)

    wb.save(out)
    print(f"原文件未改动：{a.original}")
    print(f"新文件已生成：{out}")
    print(f"  成功匹配 {n_ok} 行｜待人工确认 {n_amb} 行｜机构可能不一致 {n_moved} 行"
         f"｜疑似 OpenAlex 身份污染 {n_contaminated} 行")
    print(f"  新增 {len(NEW_COLS)} 列（均以 OA_ 开头，原有列未被覆盖）")
    print(f"  另新增「论文明细」工作表，共 {n_papers} 篇论文（标题/发文机构/链接/合作者）")


if __name__ == "__main__":
    main()
