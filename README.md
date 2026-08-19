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
├── CHANGELOG.md                Full version history — kept out of the notebook itself so
│                                the notebook stays focused on runnable cells, not narrative
├── references/
│   ├── data-sources.md         API priority, capabilities, blocked-source list
│   ├── verification-rules.md   Field acceptance criteria, merge criteria, scoring
│   ├── pitfalls.md             Failure catalogue with detection and fix, from real runs
│   ├── journal-ranking-design.md   Tier rules, matching layers, and the research-direction
│   │                                signal used by journal_ranking.py
│   └── schema.md               Target roster/graph schema for the full toolchain
├── assets/
│   └── institution_aliases.json   Learned abbreviation→OpenAlex-ID cache, grows over time
└── scripts/
    ├── resolve_v2.py            Core identity resolver — institution ID + recency + field
    │                            tie-break + contamination detection + split-entity merge
    ├── batch_enrich.py          Runs resolve_v2 across an entire roster, with caching
    ├── journal_ranking.py       Optional add-on: JCR-based journal quality tiering +
    │                            up to 3 representative papers per professor (needs a
    │                            user-supplied JCR xlsx — see "Journal ranking" below)
    ├── merge_to_excel.py        Writes results into a copy of the original spreadsheet,
    │                            plus a paper-level detail sheet (and a representative-
    │                            papers sheet, if journal_ranking.py was run)
    ├── advisor_recommend.py     Optional add-on: turns a scored (+ optionally journal-
    │                            ranked) roster into 3 lists — needs-identity-review,
    │                            not-recommended (direction/output), and a ranked,
    │                            reasoned Top-N shortlist — see "Advisor shortlist" below
    ├── confidence.py            Deterministic, auditable confidence scoring with reasons
    ├── openalex_links.py        One-click verification URLs for every row needing review
    ├── apply_manual_review.py   Reads identity decisions a human wrote into the "人工核实
    │                            结果" column back in, re-fetches the confirmed person's
    │                            full profile so the record flows through the rest of the
    │                            pipeline exactly like an automatic match afterward
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
xlsx, fill in your email + **API key** + research field + start year in the config
cell, and run top to bottom. It writes all scripts to the Colab runtime, runs the
pipeline, and downloads a completed spreadsheet plus a "needs manual review" report.

> **API key required.** OpenAlex made API keys mandatory for all requests starting
> Feb 13, 2026 — the old `mailto`-only "polite pool" is retired. Without a key you get
> ~100 free demo requests/day, then every call fails (and no amount of retrying or
> waiting fixes that — see `references/pitfalls.md` #20). Get a free key at
> https://openalex.org/settings/api (an OpenAlex account, ~30 seconds) and pass it as
> `--api-key` to every script below (or `mailto`/API_KEY in the notebook's config cell).

**Scripting / CLI, for a single person or a custom pipeline:**

```bash
python scripts/resolve_identity.py --name "Jane Doe" --institution "Yale" \
    --mailto you@x.com --api-key YOUR_KEY
python scripts/fetch_openalex.py --name "Jane Doe" --institution Yale --field finance \
    --mailto you@x.com --api-key YOUR_KEY
python scripts/batch_enrich.py roster.xlsx --sheet Sheet1 --mailto you@x.com \
    --api-key YOUR_KEY --field finance --window-a-since 2020 --out enriched.json
python scripts/journal_ranking.py enriched.json --jcr your_jcr_list.xlsx --out ranked.json \
    --window-a-since 2020 --window-b-since 2023 --interests "asset pricing" "ESG"
python scripts/confidence.py ranked.json --out ranked_scored.json
python scripts/merge_to_excel.py roster.xlsx ranked_scored.json --sheet Sheet1 \
    --mailto you@x.com --api-key YOUR_KEY --out result.xlsx
python scripts/openalex_links.py --roster enriched.json > 待人工确认.md   # all non-ok rows
# ...open result.xlsx, verify identities however you like (OpenAlex site, a school
# homepage, Semantic Scholar), write an OpenAlex ID / "ok" / "skip" into the
# "人工核实结果" column, re-upload, then feed those decisions back in:
python scripts/apply_manual_review.py result_reviewed.xlsx ranked.json --sheet Sheet1 \
    --mailto you@x.com --api-key YOUR_KEY --out enriched_reviewed.json
# re-run confidence.py / journal_ranking.py / merge_to_excel.py on enriched_reviewed.json
python scripts/reverse_lookup.py --institution HKUST --field finance --name "Yingying Li" \
    --mailto you@x.com --api-key YOUR_KEY
```

Dependencies: `requests`, `openpyxl`. No API keys required for ORCID or OpenAlex.

## Journal ranking (optional add-on)

`journal_ranking.py` grades a professor's window-A journal papers against a
**JCR journal list you supply yourself** (JCR data is licensed — this repo
never bundles it, ships no derived database, and `.gitignore` excludes any
local JCR cache file so one never gets committed by accident). Given that
list, it:

- classifies each professor into one of four tiers (①high-quality-journal
  author / ②solid output / ③not recommended / ④default) using JCR
  percentile, an ESCI -25 percentile penalty, and a UTD24 override for
  business/econ journals (UTD24 itself is public academic knowledge, shipped
  as a constant in the script — not derived from your JCR file);
- matches each paper's venue against your JCR list through four layers, in
  order: exact ISSN → exact normalized full name → exact normalized journal
  abbreviation (the JCR sheet's own abbreviation column, which is typically
  100% populated and collision-free) → token/character fuzzy matching as a
  last resort. Unmatched papers are always reported as "unmatched," never
  silently treated as best or worst;
- picks up to 3 representative papers per professor per the tier's rule
  (sorted by JCR standing — UTD24 override, then category rank, then
  percentile — never by raw impact factor, which isn't comparable across
  fields), including recent SSRN-indexed working papers where relevant, and
  a keyword-based (not semantic) relevance note against your stated research
  interests;
- checks each professor's window-A output against a research-direction
  signal with three independent branches (see
  `references/journal-ranking-design.md` §8): ordinary interdisciplinary
  crossover (e.g. finance + information systems) is exempted outright; a
  small but real secondary field (e.g. finance + psychology) needs a
  meaningfully high share of output before it's worth a note; and a
  combination that's essentially implausible for one real scholar (e.g.
  finance + oncology) blocks tier classification and representative-paper
  recommendation outright once more than one such paper appears (a single
  one is treated as JCR misclassification noise and excluded rather than
  either accepted or blocking). A career spanning many institutions
  (`affiliation_institutions`, the full history, not current employer)
  makes the two milder branches stricter, not more lenient.

See `references/journal-ranking-design.md` for the tier/matching/mix-note
rules this implementation follows in more detail.

## Advisor shortlist (optional add-on)

`advisor_recommend.py` takes a scored roster (`confidence.py`'s output,
optionally further processed by `journal_ranking.py`) and turns it into
**three** lists, kept deliberately separate:

1. **待人工核实身份** — records whose identity itself isn't trustworthy yet
   (low confidence, contamination risk, or an internally inconsistent
   research profile). Pulled out entirely before any fit judgment is made —
   this pipeline won't say whether an unverified record "fits," only that it
   needs a human to confirm who it is first.
2. **不推荐** — identity is fine, but the research doesn't fit: zero overlap
   between the advisor's recent papers and the applicant's stated interests
   (e.g. applicant wants corporate finance, advisor's recent work is
   agricultural economics), or no recent output to judge at all.
3. **推荐排名** — everyone else, ranked by 50% direction fit + 30% journal
   tier + 20% output intensity, Top-N highlighted.

Direction fit is computed against each paper's OpenAlex-assigned topic /
subfield / field labels (not just title text), so a paper titled without any
of the applicant's exact keywords can still register a match if OpenAlex
classified it into a matching topic. See
`references/advisor-recommendation-design.md` for the full gate logic, the
score formula, why identity checks and fit checks are kept in separate
lists, honestly-stated limitations, and a roadmap section covering what is
*not* built yet (a standalone web intake form, daily automated re-checking
against OpenAlex). A runnable example lives in `examples/`
(`sample_scored.json` in, `advisors_example.xlsx` out).

```bash
python scripts/advisor_recommend.py examples/sample_scored.json \
    --interests "corporate finance" "capital structure" "mergers and acquisitions" \
    --out examples/advisors_example.xlsx --top-n 10
```

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
**paper data + identity resolution + advisor shortlisting (this module)** →
graduation-year / seniority inference → personal-fit gap analysis → 套磁信 and
application-material templates → outreach tracking → writing-sample scoring →
recommendation-letter templates → offer/decision tracking. Each later stage depends on
this one producing a roster that is actually correct, which is the reason it was built,
hardened, and re-hardened first.

**Currently implemented:** identity resolution, verification, confidence scoring, optional
journal-quality tiering, and — as of `advisor_recommend.py` — turning that data into a
not-recommended list and a ranked, reasoned shortlist. All of it runs as scripts a user
invokes by hand (directly, or via the companion Colab notebook).

**Explicitly not yet built**, so this isn't overstated elsewhere in the repo:
- A standalone web form for submitting a roster / research interests — today's input is a
  file the user prepares, not a page they open.
- Daily automated re-checking of OpenAlex for new publications, with automatic re-ranking
  and a notification when the shortlist changes. This needs a persistent, schedulable
  execution environment, which a Claude Skill by itself does not provide — a skill is a
  passive instruction package an agent session loads and acts on, not something that runs
  unattended on a timer. See `references/advisor-recommendation-design.md` §7 for the full
  reasoning.
