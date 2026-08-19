# Advisor recommendation design (advisor_recommend.py)

Turns a scored roster into an applicant-facing shortlist. Independent of
identity resolution and journal grading, in the same sense
`journal_ranking.py` is independent of `resolve_v2.py` — this module only
*combines* signals those two already computed and already explained; it does
not re-derive trust itself, and (as of this revision) it computes its own
direction-fit signal rather than reusing `journal_ranking.py`'s coarser one.

## Contents
1. Why three lists, not two
2. 待人工核实身份 — the identity gate
3. 不推荐 — the fit gate
4. 推荐排名 — the score
5. Direction fit in detail — why not keyword-in-title
6. Known limitations
7. Roadmap — what is *not* built yet

---

## 1. Why three lists, not two

An earlier draft of this module used two lists (不推荐 / 推荐排名) and folded
low identity-confidence records into the "不推荐" list alongside genuine
research-fit mismatches. That conflates two different questions:

- **"Is this record even the right person?"** — a data-quality question this
  pipeline can answer from `confidence.py`'s output, independent of what the
  applicant is looking for.
- **"Does this person's research fit what the applicant wants?"** — a
  fit question that only makes sense to ask once the identity question has
  already been answered "yes."

Putting an unverified record in "不推荐" implies a fit judgment this pipeline
never actually made — the record might have looked like a perfect direction
match and still ended up unverified. So identity-uncertain records get a
third list, **待人工核实身份**, and are excluded from both other lists
entirely: nothing about them is scored, ranked, or judged for fit, because
the pipeline isn't confident enough about *who* they are to say anything
trustworthy about *whether they fit*.

## 2. 待人工核实身份 — the identity gate

Any one of the following routes a record here instead of into the fit
pipeline:

| Trigger | Source |
|---|---|
| `reliability.level` is `低` or `不可用` | `confidence.py` |
| `profile_contamination_risk` in `reliability.flags` | `confidence.py` |
| `journal_ranking.tier == "contaminated"` | `journal_ranking.py` |

The third trigger deserves explanation, since it's easy to mistake for a
research-fit signal: `journal_ranking.py`'s `contaminated` tier fires when a
single OpenAlex ID's own recent papers span an implausible combination of
fields (e.g. finance + oncology on the same profile). That is not "this
person's research doesn't fit the applicant" — it's "this OpenAlex ID may
have absorbed a different same-name person's work," the same identity-mixup
concern `confidence.py`'s `profile_contamination_risk` flag exists for. Both
belong in the identity list, not the fit list. (See the bundled example:
Oscar Qin has finance AND cancer-biomarker papers under one ID — routed to
待人工核实身份, not 不推荐, because the problem is *which person this ID
actually is*, not a direction mismatch.)

Confirming identity is a separate manual step — the same
`apply_manual_review.py` loop the rest of the pipeline already uses. Once
confirmed, re-run this script on the corrected data; there is no separate
"un-flag" mechanism inside `advisor_recommend.py` itself.

## 3. 不推荐 — the fit gate

For everyone who passes the identity gate, exactly two conditions route a
record to 不推荐 instead of the ranked list:

- **Zero output.** No papers at all in the pipeline's fetch window — nothing
  to judge fit from.
- **Zero direction fit.** Every paper's OpenAlex topic/subfield/field labels
  (see §5) and title text miss every one of the applicant's stated interest
  keywords. This is the case the applicant described directly: a professor
  whose recent work is agricultural economics gets excluded for a corporate-
  finance applicant, even if their identity is perfectly verified and their
  journal record is excellent — journal quality never overrides a direction
  mismatch, because a highly-published agricultural economist is still not
  useful to a corporate-finance applicant.

Both reasons are computed, never inferred from a tier someone else assigned
for a different purpose (this revision deliberately stopped reusing
`journal_ranking.py`'s `not_recommended` tier here, which mixes a quality
signal — mostly non-SCI output — with its *own*, coarser relevance check;
using it as a fit gate would have made the exclusion reason harder to
attribute to one specific cause).

## 4. 推荐排名 — the score

Everyone who passes both gates gets a 0–100 score:

```
score = 0.5 × direction_fit        (this module's own topic-based score, §5)
      + 0.3 × journal_tier_score   (top=100 / good=70 / default=45 /
                                     no journal_ranking data=50 neutral)
      + 0.2 × intensity_score      (paper count in the fetch window,
                                     linearly scaled 0→100 at 6+ papers)
```

**Why direction fit is weighted highest (0.5).** This is the applicant's
stated primary criterion — "根据论文搜索结果和申请者的方向是否有偏差...综合
构建" — so it outweighs journal tier and output volume combined would need to
disagree strongly to overturn a fit difference. **Why journal tier (0.3)
still outweighs intensity (0.2):** two verified, on-topic candidates with the
same fit score should not tie just because one happens to have more papers —
a smaller number of well-placed papers is stronger evidence of the person
being worth an application than a larger number of low-tier ones.

## 5. Direction fit in detail — why not keyword-in-title

The straightforward approach — check whether an interest keyword like
"corporate finance" appears in a paper's title — misses most on-topic
papers, because researchers rarely restate their sub-field in every title. A
paper titled *"Leverage Dynamics and Payout Smoothing in U.S. Public Firms"*
is squarely corporate finance but contains none of the words "corporate
finance."

Instead, `direction_fit()` matches each interest keyword against the
**topic / subfield / field labels OpenAlex's own topic classifier already
assigned that paper** (`fetch_openalex.py`'s `topics_detail`, added
alongside — not replacing — the existing flat `topics` list other scripts
already depend on). OpenAlex topics come from a curated taxonomy of roughly
4,500 topics grouped into ~250 subfields grouped into 26 fields — matching
against those labels catches papers whose classification says "Capital
Structure and Firm Performance" even when the title never says so. A match
is scored by which level it hit:

| Level | Weight | What it means |
|---|---|---|
| `topic` | 1.0 | Exact concept-level hit — the paper's specific OpenAlex topic contains the keyword |
| `subfield` | 0.7 | The paper's broader sub-discipline label contains the keyword |
| `field` | 0.35 | Only the broad discipline matches (e.g. both are "Economics, Econometrics and Finance") — weak on its own |
| `title_fallback` | 0.5 | No `topics_detail` on this work (older cached record) — falls back to matching the raw title text, the same coarse method `journal_ranking.py`'s `relevance_score()` uses |

A professor's fit score is the average of their per-paper best-level scores
across every paper in the fetch window (0 for papers matching nothing).

**This is still keyword/substring matching, not semantic matching** — a
paper whose OpenAlex labels are topically adjacent but don't literally
contain the keyword scores 0, same limitation `journal_ranking.py`'s
`relevance_score()` already documents. Structured labels reduce, but do not
eliminate, this: they catch title-wording variation, not conceptual
adjacency the applicant would recognize as related but the keyword list
didn't name. See §6.

## 6. Known limitations

- **Interest keyword breadth matters a lot.** In the bundled example
  (`examples/sample_scored.json`, run with `--interests "corporate finance"
  "capital structure" "mergers and acquisitions"`), David Zhang (macro-
  financial linkages), Grace Huang (household finance), Jack Ma-alt (market
  microstructure), Peter Song (insurance economics), and Queenie Tan
  (banking and credit markets) all score 0 fit and land in 不推荐 — none of
  their topic/subfield/field labels literally contain any of the three
  supplied keywords, even though a human reader might consider some of them
  loosely finance-adjacent. This is expected given substring matching, not a
  bug: a narrow interest list produces narrow (sometimes over-eager)
  exclusion. Supplying a broader, more representative keyword list (e.g.
  adding "capital markets", "firm valuation", "payout policy") is the
  intended way to widen the match, not a change to the matching logic
  itself.
- **No semantic or embedding-based matching**, by design — see §5. A keyword
  that doesn't appear in any of a paper's topic/subfield/field labels or
  title never scores above 0, however conceptually related a human would
  judge it.
- **`intensity_score` is volume, not impact** — six short notes score the
  same as six top-journal papers; `journal_tier_score` is what's meant to
  capture quality, deliberately kept as a separate weighted term rather than
  folded into intensity.
- **Weights (0.5 / 0.3 / 0.2) are a reasoned starting point, not a tuned
  formula** — see the same caveat in `journal-ranking-design.md`. Nothing
  here has been validated against real admission/advising outcomes.

## 7. Roadmap — what is *not* built yet

This module produces a ranked shortlist from a roster the user already ran
through the earlier pipeline stages by hand. Two capabilities discussed
early in this project's design are **not implemented**:

- **A standalone web form for intake.** Today, input is a JSON/xlsx file the
  user prepares and a script they run with `--interests` on the command
  line — there is no page a user opens to submit a roster or research
  interests. Building one means a real frontend + backend, independent of
  whatever Claude Skill packaging wraps these scripts.
- **Daily automated re-checking.** The idea: re-query OpenAlex for each
  non-excluded professor on a schedule, detect new publications, and
  automatically re-run this script (re-score, re-rank, re-gate) when new
  data appears, notifying the user if the shortlist changes. This needs a
  persistent, schedulable execution environment (a server-side cron job, or
  a hosted agent runtime with scheduled-task support) — a Claude Skill by
  itself is a passive instruction package that only runs when an agent
  session loads it and acts on it; nothing in a `.skill` file can wake
  itself up on a timer.

Both are realistic next steps, but deliberately out of scope for this
module, which stays focused on "given data the earlier pipeline stages
already produced, decide who belongs on the shortlist and say why."
