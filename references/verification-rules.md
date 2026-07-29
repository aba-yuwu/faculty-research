# Verification rules

Field-by-field acceptance criteria. If a rule cannot be satisfied, write the UNVERIFIED marker plus a note on what was tried.

## Contents
1. Identity resolution
2. Degree fields
3. Position and title
4. Recent output
5. Co-authorship
6. Age and career-stage estimation
7. Scoring

---

## 1. Identity resolution

Accept a profile as the right person only if **two or more** of these align:
institution, department, field/topics, coauthor overlap, degree institution.

Reject on any of these signals:
- Publication topics span unrelated fields (medicine + finance, materials science + finance) → **profile contamination**, see pitfalls
- Career timeline is internally inconsistent (publications predating the bachelor's degree)
- Institution never appears in any affiliation record
- **Institution only appears in the past, never as the most recent one on record.** Roster institutions here are read off official, current faculty pages — the roster claim is "this is where they are *now*", not "this is somewhere they have ever been". An author whose most recent recorded affiliation is elsewhere has very likely moved on; a return to a former institution years later does happen but is uncommon, so treat this as requiring confirmation rather than as a pass. Score at `matched_on_current_institution_verified` only when the target institution is the author's own most recent one (or in `last_known_institutions`); anything where it is merely somewhere in history is `matched_on_historical_institution_only` and always goes to manual review, never auto-accepted.

**Merging two OpenAlex entities into one person.** A common, benign cause of an apparent duplicate: a professor's affiliation was updated and OpenAlex built a new author entity for it instead of editing the old one. Before merging any two records, require both:
1. A timeline link — one record's most-recent institution appears somewhere in the other's affiliation history.
2. An exact match on fixed identity fields — full name (every token), and identical ORCID whenever both records carry one.

The timeline link alone is not sufficient (two different people at the same institution satisfy it trivially); it is the fixed-field check that actually discriminates. Require this for every pair when more than two records are involved — one mismatching pair blocks the whole group from merging.

For common surnames, an unconstrained name search is worthless. Always add institution and field.

## 2. Degree fields

| Field | Accept from | Never infer from |
|---|---|---|
| Degree institution | ORCID, dissertation record, CV, official bio | Coauthor affiliations |
| Degree year | ORCID, dissertation record, CV, placement page | First publication year (systematically too late) |
| Advisor | Dissertation record, CV, department placement page | Frequent coauthorship (correlated but not equivalent) |

An advisor inference from coauthorship alone must be labelled as inference, with the evidence stated.

## 3. Position and title

Record the **exact title string**, not a normalised version. These distinctions are decision-critical and are erased by paraphrase:

- `Adjunct` / `Visiting` / `Professor of Practice` / `Professor of Professional Practice` / `Research Assistant Professor` → typically **cannot serve as primary doctoral supervisor**. Flag prominently.
- `Associate Professor (without tenure)` → different risk profile from a tenured associate.
- `Emeritus` → retired; supervision usually not possible.

Also record administrative load (dean, department head, programme director, editor). Multiple concurrent roles materially reduce supervision availability.

## 4. Recent output

Before applying any rule about recent publications:

1. **Strip placeholder rows.** Titles like `近三年`, `无`, `N/A`, `—`, or any title under ~6 characters with no Latin letters are artifacts, not papers. They will otherwise satisfy year-based tests and corrupt scoring.
2. **Require at least one item dated within the last 3 years.** A list of career-defining classics is not evidence of current activity.
3. **Distinguish published from working paper.** Verify via Crossref or the journal site. A long-standing working paper that has not converted is itself a signal.

## 5. Co-authorship

**Accept a link only when the same paper can be matched on both sides** — matching title, or matching DOI, or matching OpenAlex work ID.

**Never accept surname matching alone.** On any roster containing Chinese, Korean, or Indian names, surname matching produces overwhelming false positives. Observed real examples: `Hong` matched from the string "Hong Kong"; `Mitchell` matched to a different person entirely; `Zhan` matched inside `Aizhan`.

Weight = number of distinct co-authored works. Count renamed versions of the same paper once (check for a shared SSRN/DOI identifier).

Special cases:
- **Mass-collaboration papers** (hundreds of authors, e.g. replication or "many analysts" projects) do not represent a working relationship. Exclude, or mark separately.
- **Textbook and edited-volume chapters** are not research collaboration. Note separately.
- **Op-eds and commentary** are not research collaboration.

## 6. Age and career-stage estimation

Two different quantities are needed and must not be conflated:

- **Actual age** → drives retirement risk, i.e. whether a multi-year student can finish under this supervisor
- **Years since PhD** → drives seniority and output-rate expectations

Estimate actual age with this hierarchy, always recording which tier was used:

| Tier | Basis | Formula | Note |
|---|---|---|---|
| 1 | Published birth year | `now − birth` | Most reliable |
| 2 | Bachelor's year | `now − bachelor + 22` | **Unaffected by industry gaps** — prefer this |
| 3 | PhD year | `now − phd + 29` | **Systematically underestimates** anyone with a pre- or post-PhD industry career |

**The industry-gap trap.** Someone who spent a decade in industry may have a short post-PhD record but be near retirement age. Detect it:

```
implied_gap = estimated_age − 29 − (now − phd_year)
if implied_gap >= 5 and estimated_age >= 50: flag
```

When flagged, state explicitly that a short academic record does **not** mean a young researcher, and that retirement risk must be judged on actual age.

Retirement risk depends on the institution's rules — many Asian universities have a mandatory retirement age (commonly 60–65) where US institutions have none. Record the institution's policy rather than applying one threshold everywhere.

## 7. Scoring

Only score records with **all** scoring inputs present. Partial records get no score and are sorted into a separate tier — a partially scored record ranks misleadingly.

Sort into three tiers, recording tier membership:

1. Complete → scored, ordered by score
2. Researched, missing an input → after tier 1, original order preserved
3. Not researched → last

Bonus rules that depend on publication counts must run **after** placeholder stripping and **after** the recency gate. Otherwise a row containing three decades-old classics scores as if it were highly active — an error that occurs reliably if the gate is omitted.

Weights are domain-specific; keep them in one place and document them alongside the data so the ranking is reproducible.
