---
name: faculty-research
description: Build and maintain a systematically verified database of academic faculty for PhD advisor selection, hiring, or collaboration mapping. Use this skill whenever the user is researching a list of professors/researchers, building an advisor shortlist, verifying academic credentials (PhD year, institution, current position), scoring or ranking faculty, mapping co-authorship networks, or maintaining a spreadsheet of academics that needs periodic updating. Also use it when the user mentions PhD applications, 套磁, advisor selection, faculty screening, or asks to check whether a professor is still active/still at a given school. Trigger even when the user frames it as a simple lookup ("what's this professor's background") if there is an existing list or spreadsheet in play, because the verification rules and known-pitfall checks in this skill prevent errors that plain web search reliably produces.
---

# Faculty Research

A verification-first workflow for building faculty databases. Optimized for the failure modes that actually occur: stale institutional pages, contaminated author profiles, name collisions, and identifier drift across versions of the same dataset.

Full version history lives in `CHANGELOG.md`, not here — this file and the notebook stay focused on current behavior.

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

### 7. (Optional) Grade journal quality and pick representative papers

If the user supplies a JCR journal list, run `journal_ranking.py` on
`batch_enrich.py`'s output to grade each professor's recent journal record
and select up to 3 representative papers. This is a separate, optional pass
— it never runs implicitly, since it requires data (the JCR list) the user
must provide themselves. See `references/journal-ranking-design.md` for the
full decision tree; the short version:

- Judges quality over a broader recent window, picks representative papers
  from a narrower, more current one (both configurable).
- Applies an ESCI percentile penalty and a UTD24 override before judging.
- Matches each paper's venue to the JCR list through four layers (exact
  ISSN → exact full-name → exact abbreviation → fuzzy), and reports match
  provenance — never silently drops an unmatched paper into the best or
  worst bucket.
- Runs a research-direction signal with three independent branches — common
  crossover (e.g. finance + info systems) is exempted; a real but small
  secondary field (e.g. finance + psychology) needs a meaningfully high
  share of output before it's worth a note; an essentially implausible
  combination (e.g. finance + oncology) blocks tier/recommendation outright
  past one paper, with a single paper treated as classification noise and
  excluded rather than either accepted or blocking. See
  `references/journal-ranking-design.md` §8 for the full family/exception
  table behind this.
- Labels any relevance-to-interests note as keyword-based, not semantic.

### 8. Feeding human review back in

Every stage that can't auto-resolve identity (ambiguous candidates, contamination
risk, historical-institution-only, field mismatch) writes a `enrich_status` that
is never silently treated as "ok" — but a human confirming the right answer needs
a way to get that answer back into the pipeline, not just read it. `merge_to_excel.py`
adds a "人工核实结果" column for exactly this: fill in an OpenAlex author ID (a
human decided, by whatever means — the OpenAlex website, a school homepage, a
Semantic Scholar search — this specific ID is the right person), the literal text
`ok` (the single candidate already listed is correct), or `skip` (confirmed not
findable, stop flagging it). Re-upload the filled-in sheet and run
`apply_manual_review.py` against it: it re-fetches the confirmed person's full
profile the same way `batch_enrich.py` does for an automatic match, so a
manually-confirmed record is indistinguishable in shape from one afterward — it
flows through `confidence.py` / `journal_ranking.py` / `merge_to_excel.py`
identically on the next pass, no special-casing needed downstream.

### 9. (Optional) Shortlist advisors from the scored roster

Once `confidence.py` (and optionally `journal_ranking.py`) has run, `advisor_recommend.py`
turns the result into three lists, kept deliberately separate: **待人工核实身份** for
records whose identity itself isn't trustworthy yet (low confidence, contamination risk, or
an internally-inconsistent research profile) — pulled out before any fit judgment, never
mixed into either list below; **不推荐** for identity-verified records whose research simply
doesn't fit (zero overlap between the advisor's recent papers and the applicant's stated
interests, or no recent output); and a ranked **推荐排名** table with a highlighted Top-N for
everyone else. Direction fit is matched against each paper's OpenAlex topic/subfield/field
labels, not just title text, so on-topic papers whose titles don't spell out the field name
still register. See `references/advisor-recommendation-design.md` for the full gate logic,
the score formula, why identity and fit are never conflated, and its final section for what
is deliberately **not** built yet (a web intake form, daily automated re-checking).

## Scripts

Run with `python scripts/<name>.py --help` for usage. All are standalone and dependency-light (`requests`, `openpyxl`).

| Script | Purpose |
|---|---|
| `resolve_v2.py` | **Core identity resolver.** Institution-ID filtering + recency check + field tie-break + clean-profile heuristic + contamination detection + split-entity merge criteria. Everything else calls into this. |
| `batch_enrich.py` | Runs `resolve_v2` across an entire roster in one pass, with a field/window-aware cache; reports unresolved or flagged names instead of guessing |
| `journal_ranking.py` | **Optional add-on.** Grades Window-A journal output against a user-supplied JCR list (ESCI-adjusted percentile + UTD24 override), then picks up to 3 representative papers per professor from Window B. Needs its own JCR xlsx — see `references/journal-ranking-design.md` |
| `confidence.py` | Deterministic, auditable scoring of how much to trust each match, with stated reasons |
| `merge_to_excel.py` | Writes results into a copy of the original spreadsheet (never the original) plus a paper-level "论文明细" detail sheet, and a "代表作推荐" sheet if `journal_ranking.py` was run |
| `openalex_links.py` | One-click browser URLs for every row that needs manual verification |
| `apply_manual_review.py` | Reads a human's identity-review decisions back from the "人工核实结果" column `merge_to_excel.py` adds, re-fetches the confirmed person's full profile, and writes an updated `enriched.json` so manually-confirmed records flow through `confidence.py`/`journal_ranking.py`/`merge_to_excel.py` identically to automatic matches |
| `advisor_recommend.py` | **Optional add-on.** Combines `confidence.py`/`journal_ranking.py` output into 3 separate lists: 待人工核实身份 (identity gate), 不推荐 (direction/output fit gate), and a ranked, reasoned Top-N shortlist. See `references/advisor-recommendation-design.md` |
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
- `references/journal-ranking-design.md` — tier decision tree, ESCI penalty, UTD24 override, the 4-layer journal-name matching strategy, and the research-direction mix note, all used by `journal_ranking.py`
- `references/advisor-recommendation-design.md` — exclusion gates, weighted score formula, and reason-string philosophy for `advisor_recommend.py`, plus what is deliberately not built yet

## Reporting to the user

Report **what changed and why**, not just what was done. Specifically:

- When a finding contradicts an earlier entry, say so explicitly and state which source won.
- Separate *verified* from *inferred* in the prose, not only in the file.
- When a search yields nothing, say what was tried. Silent gaps are worse than reported ones.
- Surface findings that change a decision even if the user did not ask — a non-tenure-track title, an institutional move, or a supervision record with placement outcomes is often more decision-relevant than any score.
