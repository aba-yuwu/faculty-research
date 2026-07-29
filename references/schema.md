# Schema

A recommended layout. Adapt names to the domain, but keep the structural properties.

> This is the **target schema for the full toolchain** (identity + papers → scoring →
> network graph → later stages). The identity-resolution stage currently implemented
> (`resolve_v2.py` / `batch_enrich.py`) produces a richer intermediate record — match method,
> reliability score and reasons, per-paper institution/link/coauthors, contamination flags —
> documented in those scripts' own docstrings and in `verification-rules.md`. Map from that
> intermediate record into this roster schema once scoring/ranking stages are built.

## Roster columns

| Group | Fields | Notes |
|---|---|---|
| Identity | `rank`, `name`, `institution`, `department`, `profile_url`, `orcid`, `openalex_id` | `rank` changes on re-sort — never key anything by it. `orcid`/`openalex_id` are the stable keys. |
| Research | `research_summary`, `paper1_title/authors/venue_year/url/note` ×3 | Keep venue and year in one parseable string, e.g. `Journal of Finance (2025)`. |
| Assessment | `focus_score`, `direction_fit`, `effort_score`, `admin_level`, `assessment_note` | `assessment_note` should record *evidence and its source*, not just a conclusion. |
| Credentials | `phd_institution`, `phd_year`, `years_since_phd`, `bachelor_year` | Numeric columns must hold numbers only. Put caveats in the note column. |
| Age | `age_evidence`, `estimated_age`, `age_tier`, `pipeline_risk` | `age_tier` records which estimation tier was used. |
| Status | `marker`, `recent_move`, `network_id` | `marker` is the category **value**; visuals derive from it. |
| Scoring | `total_score`, `score_tier`, `bonus_flag`, `bonus_reason` | `bonus_reason` states which rule fired and why. |

**Numeric columns hold numbers only.** A cell reading `about 36 (inferred from start year)` breaks every downstream computation. Put the number in the column and the caveat in a note.

**Every score needs a stated reason.** `bonus_reason` should name the rule that fired, so a later reviewer can re-derive it.

## Network graph JSON

```json
{
  "nodes": [
    {"id": 1, "name": "...", "institution": "...", "topics": [...],
     "flags": {"green": true}, "score": 0.95, "papers": [...]}
  ],
  "edges": [[source_index, target_index, "type", weight]],
  "board": {"byPartners": [...], "byPapers": [...], "full": [...]}
}
```

**Edge indices are positional** (`id − 1`). Any renumbering must rewrite both `nodes[].id` and every edge index in the same operation, then verify by resolving several edges back to names. `sync_network.py` does this with a verification pass.

Edge types:
- `coauthor` — verified shared publication; `weight` = number of distinct works
- `mentor` — documented supervision or committee membership
- `possible` — inferred association (shared programme, research lineage). Render distinctly so inference is never mistaken for evidence.

**Line width should use a square-root or log scale.** Linear width lets one heavy edge (15+ shared papers) visually swamp the graph while the difference between 1 and 2 shared papers stays invisible. `1.4 + 2.6*sqrt(w-1)` works well for weights in the 1–20 range.
