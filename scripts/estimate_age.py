#!/usr/bin/env python3
"""Three-tier age estimation with provenance and industry-gap detection.

Tier 1 birth year  -> most reliable
Tier 2 bachelor+22 -> unaffected by industry gaps; PREFER over tier 3
Tier 3 phd+29      -> systematically underestimates anyone with an industry career

Usage: python estimate_age.py roster.json --now 2026 --retirement-age 65
"""
import argparse, json

TIERS = {
    1: "birth year (published)",
    2: "bachelor year + 22 (unaffected by industry gap)",
    3: "PhD year + 29 (underestimates if industry career)",
}


def estimate(rec, now):
    if rec.get("birth_year"):
        return now - rec["birth_year"], 1
    if rec.get("bachelor_year"):
        return now - rec["bachelor_year"] + 22, 2
    if rec.get("phd_year"):
        return now - rec["phd_year"] + 29, 3
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster")
    ap.add_argument("--now", type=int, default=2026)
    ap.add_argument("--retirement-age", type=int, default=65,
                    help="institution-specific; many Asian universities 60-65, US often none")
    ap.add_argument("--programme-years", type=int, default=5)
    a = ap.parse_args()
    out = []
    for rec in json.load(open(a.roster, encoding="utf-8")):
        age, tier = estimate(rec, a.now)
        r = dict(rec)
        r["estimated_age"] = age
        r["age_tier"] = TIERS.get(tier)
        r["pipeline_risk"] = None
        r["industry_gap_flag"] = False
        if age is None:
            out.append(r); continue

        age_at_completion = age + a.programme_years
        if age_at_completion > a.retirement_age + 5:
            r["pipeline_risk"] = (f"HIGH: ~{age} now, ~{age_at_completion} at completion, "
                                  f"well past a {a.retirement_age} retirement age.")
        elif age_at_completion > a.retirement_age:
            r["pipeline_risk"] = (f"ELEVATED: ~{age} now, ~{age_at_completion} at completion, "
                                  f"crosses a {a.retirement_age} retirement age. Confirm plans.")
        elif age_at_completion > a.retirement_age - 5:
            r["pipeline_risk"] = (f"MODERATE: ~{age} now, ~{age_at_completion} at completion, "
                                  f"approaching retirement age.")

        # industry-gap trap: long non-academic career hidden by a short post-PhD record
        if rec.get("phd_year") and tier in (1, 2):
            implied = age - 29 - (a.now - rec["phd_year"])
            if implied >= 5 and age >= 50:
                r["industry_gap_flag"] = True
                r["pipeline_risk"] = ((r["pipeline_risk"] or "") +
                    f" INDUSTRY GAP: ~{implied}y outside academia. A short academic record does "
                    f"NOT mean a young researcher — judge retirement risk on age {age}, "
                    f"not on {a.now - rec['phd_year']} years since PhD.").strip()
        out.append(r)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
