---
name: faculty-research
description: Build and maintain a systematically verified database of academic faculty for PhD advisor selection, hiring, or collaboration mapping. Use this skill whenever the user is researching a list of professors/researchers, building an advisor shortlist, verifying academic credentials (PhD year, institution, current position), scoring or ranking faculty, mapping co-authorship networks, or maintaining a spreadsheet of academics that needs periodic updating. Also use it when the user mentions PhD applications, 套磁, advisor selection, faculty screening, or asks to check whether a professor is still active/still at a given school. Trigger even when the user frames it as a simple lookup ("what's this professor's background") if there is an existing list or spreadsheet in play, because the verification rules and known-pitfall checks in this skill prevent errors that plain web search reliably produces.
---

# Faculty Research

A verification-first workflow for building faculty databases. Optimized for the failure modes that actually occur: stale institutional pages, contaminated author profiles, name collisions, and identifier drift across versions of the same dataset.

## Core principle

**Never fill a field you could not verify.** An empty cell is recoverable; a fabricated PhD year silently corrupts every downstream ranking and may send someone to contact the wrong person. When a field cannot be verified, write an explicit marker (e.g. `待核实 / UNVERIFIED`) plus a one-line note on *what was tried and why it failed*. That note is what lets the user close the gap themselves.

## Workflow

### 1. Establish identity before researching anything

Name matching is the single largest error source. Before any lookup:

- Get an unambiguous handle: an OpenAlex author ID (via `resolve_v2.find_author`, which
  resolves the institution to an ID first and filters on it — never a plain name search), an
  ORCID iD, or `full name + institution + department` as a last resort.
- For common surnames (Wang, Chen, Li, Zhang, Huang, Kim, Singh, Nguyen…), a bare name search
  is worthless. Always constrain by institution and field, and prefer `reverse_lookup.py`
  (institution+field → author pool → match the name inside it) over a name-first search.
- A resolved match is only as good as its *recency*: the roster institution means "current,"
  so require the author's most-recent affiliation to match, not merely a historical one, and
  never trust a single candidate without also checking it isn't itself internally
  contaminated (see §3).
- Record the resolved identifier in the dataset so later runs do not re-resolve.

### 2. Prefer structured APIs over web pages

Read `references/data-sources.md` before your first lookup. Summary of priority order:

1. **ORCID Public API** — education entries with degree years. The single best source for PhD/bachelor year.
2. **OpenAlex API** — works, coauthors, and *affiliation history with years* (gives academic start year).
3. **Crossref** — authoritative journal/DOI metadata for a known paper.
4. **Institutional repository / dissertation databases** — thesis year and institution.
5. **Official faculty page** — current title, admin roles, teaching. Good for *now*, unreliable for *history*.
6. **Personal website / CV PDF** — richest source when it exists, but often behind robots restrictions.

**Do not attempt to circumvent robots.txt, paywalls, or rate limits.** If a source blocks automated access, record it as a known gap and ask the user to paste the content. This is both the correct call and, in practice, faster than fighting the block. `references/data-sources.md` lists which sources are commonly blocked.

### 3. Verify before writing

Every field written must pass the checks in `references/verification-rules.md`. The non-obvious ones:

- **Recency**: a "recent publications" field must contain at least one item from the last few years (the window is configurable, not a fixed "3 years"), and placeholder rows must be excluded before any rule is applied. This applies to *identity matching* too: a roster institution means "where they are now," so a candidate's institution match must be their *most recent* recorded affiliation, not merely one they've ever had — see `institution_match_level()` in `resolve_v2.py`.
- **Co-authorship**: only accept a link when the *same paper title* can be matched on both sides. Surname matching alone produces overwhelming false positives.
- **Never merge two OpenAlex records on topic overlap alone.** Topic overlap between two different candidate IDs can happen coincidentally for two different people in the same field. A merge requires BOTH: (1) a timeline link — one record's most-recent institution appears in the other's affiliation history, consistent with OpenAlex having rebuilt a new entity when an affiliation was updated — AND (2) an exact match on fixed identity fields (full name, and ORCID when both records carry one). Topic overlap is checked too, but only as an additional sanity net. For common names, prefer `reverse_lookup.py`: narrow to the institution and field first, then find the name inside that small pool.
- **A single candidate is not automatically trustworthy.** Institution and recency checks only ever compare *between* candidates; a lone OpenAlex ID that has itself absorbed a different same-name person's work (spanning clearly unrelated topic domains) sails through every cross-candidate check because there is no second candidate to compare it against. This needs its own check — see `_contamination_risk()` in `resolve_v2.py` — and is never auto-accepted even as the sole match.
- **Age**: estimate from bachelor year where available, not PhD year — industry gaps make PhD-based estimates systematically too young. See the three-tier hierarchy in `references/verification-rules.md`.
- **Validation strictness**: verify with a tool at least as strict as whatever will consume the output. A lenient checker agreeing with a strict one most of the time is what makes the disagreements dangerous.

### 4. Screen uniformly before researching deeply

Two passes, not one. A **uniform shallow pass over everyone** makes the roster comparable;
a **deep pass on the shortlist** answers the questions that actually drive a decision.

Doing only deep passes, in whatever order the roster happens to be in, produces a ranking
that partly measures *how much attention each person received* rather than how good they are.
Run `batch_enrich.py` across the full roster first.

Note which scoring inputs are **coarse**. If a field enters the formula as a threshold
(e.g. "within N years of PhD" as a binary), an approximation from job title or career start
year is sufficient — chasing an exact value is effort spent on precision the formula discards.

### 5. Score and rank only complete records

Partial records must not receive a score — they will rank misleadingly. Sort into tiers:

1. Complete → scored, ordered by score
2. Researched but missing a scoring input → after tier 1, original order preserved
3. Not yet researched → last

Record which tier each row is in so the user can see what a rank actually means.

### 6. Keep identifiers stable across versions

The most damaging class of bug in this workflow: the dataset gets re-sorted, and anything keyed by row position or old rank silently attaches to the wrong person. See `references/pitfalls.md`.

Rules:
- Key every lookup table, colour map, and cross-file reference by **name or stable ID**, never by rank or row number.
- When re-ranking, remap *all* dependent artifacts in the same operation and verify by spot-checking names on both sides.
- Store category markers (priority, risk flags) in a **column**, not in cell formatting, so they travel with the row when sorted.

## Scripts

Run with `python scripts/<name>.py --help` for usage. All are standalone and dependency-light (`requests`, `openpyxl`).

| Script | Purpose |
|---|---|
| `resolve_v2.py` | **Core identity resolver.** Institution-ID filtering + recency check + field tie-break + clean-profile heuristic + contamination detection + split-entity merge criteria. Everything else calls into this. |
| `batch_enrich.py` | Runs `resolve_v2` across an entire roster in one pass, with a field/since-aware cache; reports unresolved or flagged names instead of guessing |
| `confidence.py` | Deterministic, auditable scoring of how much to trust each match, with stated reasons |
| `merge_to_excel.py` | Writes results into a copy of the original spreadsheet (never the original) plus a paper-level "论文明细" detail sheet |
| `openalex_links.py` | One-click browser URLs for every row that needs manual verification |
| `reverse_lookup.py` | Institution+field → author pool, then match the name — the reliable route for common names |
| `resolve_identity.py` | Single-person lookup: `resolve_v2` + an independent ORCID cross-check |
| `fetch_openalex.py` | Low-level OpenAlex client: author profile, works (with per-paper institution/link/coauthors), affiliation timeline |
| `fetch_orcid.py` | ORCID iD → education history (degree, institution, years) |
| `scan_coauthors.py` | Title-level co-authorship detection across a roster; emits confidence tiers |
| `estimate_age.py` | Three-tier age estimation with evidence provenance and gap detection |
| `score_roster.py` | Tiered scoring with configurable weights and recency-gated bonus rules |
| `sync_network.py` | Re-map node IDs and edge indices after a re-rank; includes verification pass |
| `audit_dataset.py` | Consistency checks: link/institution mismatch, placeholder rows, orphan markers |

Run `audit_dataset.py` after every batch. It catches most of the pitfalls automatically.

## Reference files

- `references/data-sources.md` — API endpoints, auth, rate limits, what each source can and cannot answer, blocked-source list
- `references/verification-rules.md` — field-by-field acceptance criteria, age hierarchy, co-authorship matching, scoring rules
- `references/pitfalls.md` — catalogue of real failure modes with detection and fix for each
- `references/schema.md` — recommended column layout and network-graph JSON format

## Reporting to the user

Report **what changed and why**, not just what was done. Specifically:

- When a finding contradicts an earlier entry, say so explicitly and state which source won.
- Separate *verified* from *inferred* in the prose, not only in the file.
- When a search yields nothing, say what was tried. Silent gaps are worse than reported ones.
- Surface findings that change a decision even if the user did not ask — a non-tenure-track title, an institutional move, or a supervision record with placement outcomes is often more decision-relevant than any score.
