#!/usr/bin/env python3
"""Tiered scoring with placeholder stripping and a recency gate.

Order matters: strip placeholders -> apply recency gate -> apply bonus rules.
Skipping the gate makes a list of decades-old classics score as high activity.

Usage: python score_roster.py roster.json --weights weights.json --now 2026
"""
import argparse, json, re

PLACEHOLDER = re.compile(r"^\s*(近三年|无|暂无|未检索|未见|待核实|待补|N/?A|nan|[-—])\s*$", re.I)

DEFAULT_WEIGHTS = {
    "direction_fit": 0.30, "effort": 0.30, "recency": 0.10,
    "admin": 0.10, "authorship": 0.10, "bonus": 0.10,
}
DEFAULT_TOP_VENUES = [
    "Journal of Finance", "Journal of Financial Economics", "Review of Financial Studies",
    "Econometrica", "American Economic Review", "Journal of Political Economy",
    "Quarterly Journal of Economics", "Review of Economic Studies", "Management Science",
    "Journal of Accounting and Economics", "Journal of Accounting Research",
    "The Accounting Review", "Journal of Financial and Quantitative Analysis",
]


def is_placeholder(title):
    t = (title or "").strip()
    if not t:
        return True
    if PLACEHOLDER.match(t):
        return True
    return len(t) <= 6 and not re.search(r"[A-Za-z]", t)


def clean_papers(rec):
    kept, dropped = [], []
    for p in rec.get("papers") or []:
        (dropped if is_placeholder(p.get("title")) else kept).append(p)
    return kept, dropped


def bonus(rec, papers, now, top_venues, recency_years=3):
    if not papers:
        return 0.5, "no valid recent-work entries"
    years = [y for p in papers for y in re.findall(r"(20\d{2})", str(p.get("venue_year") or p.get("year") or ""))]
    years = [int(y) for y in years]
    newest = max(years) if years else None
    if not newest or newest < now - recency_years:
        return 0.5, (f"recency gate: newest entry {newest or 'undated'}, "
                     f"not within {recency_years} years")
    ntop = sum(1 for p in papers
               if any(v.lower() in str(p.get("venue_year") or p.get("venue") or "").lower()
                      for v in top_venues))
    if len(papers) >= 3 and ntop >= 2:
        return 1.0, f"rule C: {len(papers)} entries, {ntop} top-tier, recent"
    if 1 <= len(papers) <= 2 and ntop >= 1 and ntop / len(papers) >= 0.5:
        return 1.0, f"rule A: {len(papers)} entries, {ntop} top-tier (>=50%), recent"
    if rec.get("phd_year") and (now - rec["phd_year"]) <= 8:
        nwp = sum(1 for p in papers if re.search(
            r"working paper|conference|arxiv|preprint|工作论文|会议",
            str(p.get("venue_year") or ""), re.I))
        if nwp >= 2:
            return 1.0, f"rule B: early career ({now-rec['phd_year']}y), {nwp} working papers"
    return 0.5, f"no rule met ({len(papers)} entries, {ntop} top-tier)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster"); ap.add_argument("--weights")
    ap.add_argument("--now", type=int, default=2026)
    ap.add_argument("--recent-threshold", type=int, default=20,
                    help="years since PhD below which the recency component scores 1")
    a = ap.parse_args()
    W = dict(DEFAULT_WEIGHTS)
    if a.weights:
        W.update(json.load(open(a.weights, encoding="utf-8")))

    out = []
    for rec in json.load(open(a.roster, encoding="utf-8")):
        papers, dropped = clean_papers(rec)
        r = dict(rec)
        if dropped:
            r["dropped_placeholders"] = [d.get("title") for d in dropped]
        b, why = bonus(rec, papers, a.now, DEFAULT_TOP_VENUES)
        r["bonus_flag"], r["bonus_reason"] = b, why

        need = ("direction_fit", "effort_score", "admin_level", "years_since_phd")
        if all(isinstance(rec.get(k), (int, float)) for k in need):
            recency = 1.0 if rec["years_since_phd"] <= a.recent_threshold else 0.5
            admin = 0.5 if rec["admin_level"] >= 2 else 1.0
            r["total_score"] = round(
                W["direction_fit"] * rec["direction_fit"] + W["effort"] * rec["effort_score"]
                + W["recency"] * recency + W["admin"] * admin
                + W["authorship"] * rec.get("authorship_score", 1.0) + W["bonus"] * b, 4)
            r["score_tier"] = 1
        else:
            r["total_score"] = None
            r["score_tier"] = 2 if rec.get("phd_institution") else 3
            r["missing_inputs"] = [k for k in need
                                   if not isinstance(rec.get(k), (int, float))]
        out.append(r)

    out.sort(key=lambda x: (x["score_tier"],
                            x["total_score"] if x["total_score"] is not None else 9e9,
                            x.get("id", 0)))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    counts = {t: sum(1 for r in out if r["score_tier"] == t) for t in (1, 2, 3)}
    print(json.dumps({"tier_counts": counts, "weights": W, "roster": out},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
