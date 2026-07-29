# faculty-research

An agent skill + Colab pipeline for building a **verified** database of academic faculty —
built for PhD advisor screening, but the identity-resolution core generalizes to academic
hiring, collaboration mapping, or any task that starts with "find this person's real,
current OpenAlex/ORCID record and don't guess."

This is the first module of a larger PhD-application toolchain (advisor list → paper data →
graduation-year inference → gap analysis → outreach templates → application tracking).
It was built first, deliberately, because **identity resolution is the error source that
silently corrupts everything downstream** — a wrong OpenAlex match doesn't fail loudly, it
just quietly hands you someone else's publication record.

## Why this exists

Naive approaches to "find this professor's papers" fail in specific, repeatable, *silent*
ways — the output looks plausible right up until you check it against the person's actual
Google Scholar page. This skill encodes the countermeasures for each failure mode, and the
`references/pitfalls.md` catalogue is a running log of real ones caught during development,
not a hypothetical list:

- A single OpenAlex author ID absorbed a **different real person's papers** — one candidate's
  publication list spanned cybersecurity, medical radiomics, and mesh generation under one ID,
  with three unrelated institutions listed as "current." Passed every check that only compares
  *between* candidates, because there was only ever one candidate to compare.
- **Institution matching by "ever affiliated" instead of "currently affiliated"** produced
  false ambiguity: three different people who each passed through the same institution at some
  point (one of them a decade ago) all matched a roster row that meant "current faculty."
- A duplicate-detection heuristic merged two different people who shared a surname and an
  institution, because it only checked topic overlap — not whether their affiliation timelines
  actually chained together, and not whether their names matched exactly.
- An institution abbreviation ("HKU") never resolved to its canonical OpenAlex name because a
  single inverted boolean in the alias-caching logic silently discarded every successful
  resolution for pre-seeded entries — so the acronym-to-full-name lookup this project literally
  exists to solve was quietly failing to save its own answers to disk.
- A pagination parameter passed as a Python keyword (`per_page=`) is not the same string OpenAlex's
  API expects (`per-page`) — the request never errored, it just silently fell back to the API's
  default page size, truncating results for any professor with more than 25 papers in the window.

None of these throw an exception. Every one of them produces a clean-looking row in the
output spreadsheet that is simply wrong. The project's core engineering bet is that
**verification discipline — building the checks that catch these before they reach a human —
is what makes a scraped academic dataset trustworthy**, not query volume or a bigger model.

## What it actually does

Given a roster (name + institution, one row per professor) and a research field, the
pipeline:

1. Resolves each name+institution to a single OpenAlex author ID — never by name alone, never
   by "an institution appears somewhere in their history," and never by merging two IDs on
   weak evidence (see `resolve_v2.py`, the core of the project).
2. Flags, rather than silently accepts, every case where the evidence is genuinely
   ambiguous, historical-only, or shows signs that the underlying OpenAlex identity itself
   is contaminated — these get routed to a "needs manual review" bucket instead of being
   guessed at.
3. Pulls each person's recent output, career-start year, and full publication-level detail
   (title, the institution they were affiliated with *on that specific paper*, a link, and
   coauthors) — not just their current profile.
4. Scores its own confidence in each match, with the specific reasons stated, so a reviewer
   can see *why* a row was trusted without re-deriving it.
5. Writes everything back into a copy of the original roster spreadsheet plus a paper-level
   detail sheet, without ever touching the original file.

## Design principles

1. **An empty or flagged cell beats a guessed one.** Every ambiguous or unverifiable match
   gets an explicit status (`ambiguous`, `possible_move`, `needs_review_contaminated`, ...)
   and a stated reason, never a silent best-effort guess.
2. **Structured APIs before web pages.** OpenAlex for affiliation timelines, works, and
   co-authorship by ID; ORCID as an independent cross-check. Better data *and* no scraping.
3. **Recency beats mere presence.** A roster institution means "where they are *now*" —
   matching requires the author's *most recent* recorded affiliation, not just any
   affiliation they've ever had.
4. **A single "candidate" is not automatically trustworthy.** Cross-candidate checks
   (institution match, merge criteria) can't catch a single OpenAlex ID that is itself
   internally contaminated — that needs its own, separate check.
5. **Never circumvent access controls.** Blocked sources are recorded as gaps and handed
   back to the user as a short copy-paste task, not routed around.
6. **Report contradictions loudly.** When a finding overturns an earlier one — a person's
   own alias file, an OpenAlex identity flagged as contaminated — say so and state which
   source won.

## Layout

```
faculty-research/
├── SKILL.md
├── references/
│   ├── data-sources.md         API priority, capabilities, blocked-source list
│   ├── verification-rules.md   Field acceptance criteria, merge criteria, scoring
│   ├── pitfalls.md             Failure catalogue with detection and fix, from real runs
│   └── schema.md               Target roster/graph schema for the full toolchain
├── assets/
│   └── institution_aliases.json   Learned abbreviation→OpenAlex-ID cache, grows over time
└── scripts/
    ├── resolve_v2.py            Core identity resolver — institution ID + recency + field
    │                            tie-break + contamination detection + split-entity merge
    ├── batch_enrich.py          Runs resolve_v2 across an entire roster, with caching
    ├── merge_to_excel.py        Writes results into a copy of the original spreadsheet,
    │                            plus a paper-level detail sheet
    ├── confidence.py            Deterministic, auditable confidence scoring with reasons
    ├── openalex_links.py        One-click verification URLs for every row needing review
    ├── reverse_lookup.py        Institution+field → author pool, then match the name —
    │                            the reliable route for common names
    ├── fetch_openalex.py        Low-level OpenAlex client: author profile, works, coauthors
    ├── resolve_identity.py      Single-person lookup: OpenAlex + independent ORCID cross-check
    ├── fetch_orcid.py           ORCID → education history with degree years
    ├── scan_coauthors.py        Title/DOI-level co-authorship, confidence-tiered
    ├── estimate_age.py          Three-tier age estimation + industry-gap detection
    ├── score_roster.py          Tiered scoring, placeholder stripping, recency gate
    ├── sync_network.py          Node/edge ID remapping with endpoint verification
    └── audit_dataset.py         Consistency checks — run after every batch
```

`resolve_v2.py` is the load-bearing file (830+ lines and the most heavily revised in the
project — every failure mode above lives here). Everything else either calls it, feeds it,
or formats its output.

## Quick start

**Primary workflow (recommended):** open the companion Colab notebook, upload your roster
xlsx, fill in your email + research field + start year in the config cell, and run top to
bottom. It writes all scripts to the Colab runtime, runs the pipeline, and downloads a
completed spreadsheet plus a "needs manual review" report.

**Scripting / CLI, for a single person or a custom pipeline:**

```bash
python scripts/resolve_identity.py --name "Jane Doe" --institution "Yale" --mailto you@x.com
python scripts/fetch_openalex.py --name "Jane Doe" --institution Yale --field finance --mailto you@x.com
python scripts/batch_enrich.py roster.xlsx --sheet Sheet1 --mailto you@x.com \
    --field finance --since 2022 --out enriched.json
python scripts/confidence.py enriched.json --out enriched_scored.json
python scripts/merge_to_excel.py roster.xlsx enriched_scored.json --sheet Sheet1 \
    --mailto you@x.com --out result.xlsx
python scripts/openalex_links.py --roster enriched.json > 待人工确认.md   # all non-ok rows
python scripts/reverse_lookup.py --institution HKUST --field finance --name "Yingying Li"
```

Dependencies: `requests`, `openpyxl`. No API keys required for ORCID or OpenAlex.

## Scope and limits

- Match confidence is **stated, not assumed** — every row carries a `match_method` and a
  scored `reliability` block with reasons. A "current institution verified" match is strong
  evidence, not a guarantee; spot-checking flagged rows is still the user's job.
- Co-authorship and affiliation history reflect only what OpenAlex indexes. Absence of an
  edge or affiliation is weak evidence, not proof of absence.
- Contamination detection catches *topic-domain* diversity within one OpenAlex ID; it cannot
  catch contamination that happens to stay within one coherent field.
- Google Scholar, some university portals, and some file hosts block automated access. The
  skill treats these as user-assisted steps rather than obstacles to route around.
- This module covers identity resolution and paper-level data collection. Graduation-year
  inference, fit/gap scoring, and outreach-material generation are later stages of the same
  project and are not yet part of this skill.

## Project status and roadmap

Built as the foundation of a full PhD-application toolchain: advisor list acquisition →
**paper data + identity resolution (this module)** → graduation-year / seniority inference →
personal-fit gap analysis → 套磁信 and application-material templates → outreach tracking →
writing-sample scoring → recommendation-letter templates → offer/decision tracking. Each
later stage depends on this one producing a roster that is actually correct, which is the
reason it was built, hardened, and re-hardened first.
