#!/usr/bin/env python3
"""Score how much each enrichment result should be trusted, with stated reasons.

Deliberately deterministic rather than model-based: the checks are cheap, auditable,
and reproducible, and a language model adds nothing to questions like "does the
institution in the record match the institution in the roster".

Usage: python confidence.py enriched.json --out scored.json
"""
import argparse, json, os, re, sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from resolve_v2 import same_institution, norm_inst, ALIASES, initials_match
except Exception:                                   # standalone fallback
    ALIASES = {}
    def initials_match(abbrev, full_name):
        return False

    def norm_inst(name):
        n = re.sub(r"[^\w\s]", " ", str(name or "").lower())
        return re.sub(r"^the ", "", re.sub(r"\s+", " ", n).strip())

    def same_institution(a, b):
        x, y = norm_inst(a), norm_inst(b)
        return bool(x and y and (x == y or x in y or y in x))


# Base trust by how identity was resolved. "current_institution" methods mean the
# author's MOST RECENT recorded affiliation is the roster institution (see
# resolve_v2.institution_match_level) — the strongest evidence available given that
# roster institutions are read off official, current faculty pages. "historical"
# methods mean the roster institution only ever appears in the author's past, which
# is why they score low and are always routed to manual review upstream regardless.
# Every key here is a literal string resolve_v2.find_author() can actually return —
# keep this list in sync with that function rather than accumulating entries for
# retired return values.
METHOD_BASE = {
    "matched_on_current_institution_verified": 95,
    "matched_on_current_institution_and_field": 90,
    "matched_on_current_institution_clean_profile_heuristic": 82,
    "matched_on_current_institution_excluding_contaminated_candidates": 75,
    "merged_duplicate_records": 65,
    "matched_on_historical_institution_only": 30,
    "merged_duplicate_records_historical_institution_only": 25,
    "ambiguous_same_institution": 15,
    "ambiguous_same_institution_historical_institution_only": 10,
    "name_only_unverified": 12,
    "not_found": 0,
    "field_mismatch_needs_review": 5,   # institution+name narrowed to exactly one
                                        # candidate, but their topics show zero
                                        # overlap with the configured --field — a
                                        # structural blind spot in name matching for
                                        # Chinese names (see pitfalls.md #19), not
                                        # treated as trustworthy just because it's
                                        # the only candidate found.
    "api_error": 0,   # every OpenAlex call for this person raised an exception (see
                      # resolve_v2._find_author_inner) — untrustworthy for the same
                      # reason not_found is, but for a different reason: re-running
                      # may well find them, this isn't necessarily "not on OpenAlex."
}

# Keyword flag for the "contaminated profile" pitfall (see pitfalls.md #4): topics or
# venues from clearly unrelated fields (medicine, physics, materials science, etc.)
# showing up on a supposedly finance/econ/business scholar's recent work.
OFF_FIELD = re.compile(
    r"\b(clinical|cardiolog\w*|oncolog\w*|radiolog\w*|tumou?r|carcinoma|cancer|"
    r"diabetes|neutrino|collider|astrophys\w*|photovoltaic|semiconductor|"
    r"nanoparticle|drug delivery|pharmacolog\w*|biolog\w*|genomic\w*|proteomic\w*|"
    r"immunolog\w*|surgical|pathogen\w*|virus|vaccine)\b", re.I)


def _inst_agrees(roster_inst, record_insts):
    """Institution names are unique, so compare the expanded name exactly.

    Similarity scoring is the wrong tool here: 'Hong Kong University of Science and
    Technology' and 'University of Science and Technology of China' overlap heavily
    while denoting different places. Initials are used earlier to *resolve* an
    abbreviation, never to *verify* one — 'CUHK' is the initialism of both the
    Chinese University and the City University of Hong Kong.

    Returns True (confirmed match) / False (confirmed mismatch) / None (either no
    data, or — importantly — the roster institution is an abbreviation this script
    has no expansion for). same_institution() falls back to comparing the raw,
    un-expanded abbreviation string when the local alias table doesn't have an
    entry for it (this script deliberately makes no network calls of its own to
    resolve one, unlike merge_to_excel.py's _institution_mismatch — see
    pitfalls.md #20's "unknown vs mismatch" fix there for the same underlying
    problem). A raw abbreviation almost never appears verbatim inside OpenAlex's
    expanded institution name ("NUS" is not a substring of "National University
    of Singapore"), so treating that fallback's failure as a confirmed mismatch
    would flag correct matches as wrong purely because the alias wasn't cached
    yet when this particular script ran — the exact false-positive pattern a
    real run produced en masse. Only trust a "no match" verdict when the alias
    table actually had an expansion to compare against.
    """
    if not roster_inst or not record_insts:
        return None
    resolved = (ALIASES.get(str(roster_inst).strip()) or {}).get("display_name")
    agree = any(same_institution(roster_inst, r) for r in record_insts)
    if agree:
        return True
    if resolved:
        return False       # compared against a real expansion and still disagreed
    # no cached expansion — the abbreviation might still plausibly be this
    # institution's initials even though the alias table hasn't confirmed it
    # (e.g. a fresh session that hasn't resolved it yet); a genuine mismatch
    # would fail this too, so it's not a strong "match" signal, but failing
    # it on top of an unresolved alias is not a strong "mismatch" signal either.
    if any(initials_match(roster_inst, r) for r in record_insts):
        return None
    return None


def score_one(rec, expect_field="finance"):
    pts, why, flags = 0, [], []
    method = rec.get("match_method") or ""
    # "_profile_contamination_risk" can be appended on top of any base method (see
    # resolve_v2.find_author) — strip it for the base lookup, then apply its own
    # penalty once, rather than enumerating every combined string. "api_error" carries
    # a dynamic exception message after it ("api_error: ConnectionError: ...") that
    # must also be stripped before the METHOD_BASE lookup, or it never matches the
    # "api_error" entry and silently falls through to the generic-unknown default.
    base_method = method.replace("_profile_contamination_risk", "")
    if base_method.startswith("api_error"):
        base_method = "api_error"
    if base_method.startswith("field_mismatch_needs_review"):
        base_method = "field_mismatch_needs_review"
    base = METHOD_BASE.get(base_method, 25)
    pts += base
    why.append(f"匹配方式「{base_method or '未知'}」基准 {base} 分")
    if "_profile_contamination_risk" in method:
        pts -= 35
        flags.append("profile_contamination_risk")
        why.append("该 OpenAlex ID 自身的论文跨越明显不相关学科（如医学+计算机）−35"
                   "，很可能是 OpenAlex 消歧错误、混入了另一个同名人的成果，务必人工核实")

    insts = (rec.get("effective_institutions") or rec.get("last_known_institutions")
             or rec.get("affiliation_institutions") or [])
    roster_inst = str(rec.get("institution") or "")
    agree = _inst_agrees(roster_inst, insts)
    if agree is True:
        pts += 10; why.append(f"机构与名单一致 +10（{insts[0]}）")
    elif agree is False:
        pts -= 15
        why.append(f"机构与名单不一致 −15（名单「{roster_inst}」vs 记录「{insts[:2]}」）")
        flags.append("institution_mismatch")
    else:
        if insts:
            pts -= 2
            why.append(f"机构缩写「{roster_inst}」未能确认展开后是否与记录一致 −2"
                       f"（不代表真的不一致，多半是本地别名缓存还没有这条，"
                       f"记录「{insts[:2]}」）")
        else:
            pts -= 5; why.append("记录中无任何机构信息 −5")

    merged = rec.get("merged_ids") or []
    if merged:
        n = len(merged)
        names = rec.get("merged_names") or []
        uniq = len({str(x).lower() for x in names})
        if n >= 5:
            pts -= 30; flags.append("over_merge")
            why.append(f"合并了 {n} 条记录 −30（数量过多，很可能混入了他人）")
        elif uniq > 1:
            pts -= 10
            why.append(f"合并了 {n} 条记录、{uniq} 种写法 −10（请核对是否同一人）")
        else:
            why.append(f"合并了 {n} 条同名记录（写法一致，风险较低）")

    works = rec.get("recent_works") or []
    if works:
        venues = " ".join(str(w.get("venue") or "") for w in works)
        titles = " ".join(str(w.get("title") or "") for w in works)
        off = OFF_FIELD.findall(venues + " " + titles)
        if off:
            pts -= 25; flags.append("off_field_papers")
            why.append(f"论文含明显跨领域内容 −25（{sorted(set(x.lower() for x in off))[:3]}）")
        yrs = [w.get("year") for w in works if w.get("year")]
        if yrs and max(yrs) >= date.today().year - 2:
            pts += 5; why.append("含近年论文 +5")
    else:
        pts -= 10; why.append("未取到任何近三年论文 −10")

    if rec.get("orcid"):
        pts += 5; why.append("有 ORCID +5")

    pts = max(0, min(100, pts))
    level = ("高" if pts >= 80 else "中" if pts >= 55 else "低" if pts >= 30 else "不可用")
    action = {
        "高": "可直接采用",
        "中": "建议抽查一眼论文与机构",
        "低": "必须人工确认后再用",
        "不可用": "不要采用，请人工查证",
    }[level]
    return {"confidence": pts, "level": level, "action": action,
            "reasons": why, "flags": flags}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched"); ap.add_argument("--out", default="scored.json")
    ap.add_argument("--field", default="finance")
    a = ap.parse_args()
    data = json.load(open(a.enriched, encoding="utf-8"))
    for r in data:
        r["reliability"] = score_one(r, a.field)
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    c = Counter(r["reliability"]["level"] for r in data)
    print("=== 可信度分布 ===")
    for lv in ("高", "中", "低", "不可用"):
        if c.get(lv):
            print(f"  {lv}: {c[lv]} 位")
    print("\n=== 需要人工处理的（低 / 不可用）===")
    for r in sorted(data, key=lambda x: x["reliability"]["confidence"]):
        rel = r["reliability"]
        if rel["level"] in ("低", "不可用"):
            print(f"\n  [{rel['confidence']}分·{rel['level']}] {r.get('name')} ({r.get('institution')})")
            print(f"     → {rel['action']}")
            for w in rel["reasons"]:
                print(f"       · {w}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
