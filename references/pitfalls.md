# Pitfalls

Each entry: what goes wrong, how it presents, how to detect it, how to fix it. All of these were observed in production on a 261-person roster.

## Contents
1. Identifier drift after re-ranking
2. Formatting-based markers lost on sort
3. Stale colour left behind on re-sort
4. Contaminated author profiles
5. Placeholder rows satisfying data rules
6. Surname-based co-authorship false positives
7. Stale institutional pages and encyclopedia entries
8. Systematically wrong link columns
9. Industry gaps distorting age estimates
10. Prestige-journal lists mistaken for current activity
11. Supervision records from a previous institution
12. Validating with a more permissive tool than the target environment
13. Lifetime affiliation history mistaken for current employment (see body)
14. Silent API failures indistinguishable from genuine zero-result searches
15. Substring keyword matching across unrelated category names
16. Retry backoff repeated for every call in a degraded batch, and ambiguous ties left unresolved when a cheap signal could break them
17. Vote-based "primary field" is fragile with few papers, and a blocking check was the wrong response to a false positive
18. A single ratio threshold conflated "implausible" with "uncommon" — they need independent trigger rules, not one shared bar
19. Reversed Chinese name order silently defeated identity matching, with the wrong candidate auto-accepted at high confidence
20. A retry/cooldown mechanism can't fix a missing credential — OpenAlex made API keys mandatory in Feb 2026
21. Three independent institution-matching implementations all silently relabeled "couldn't verify" as "confirmed mismatch"
22. Two separate cache files, only one backed up — and a redundant institution-search query that doubled the credit cost for no benefit
23. An unguarded float() on a raw spreadsheet cell crashed the entire run on the first malformed JIF percentile
24. Switching to real-time output streaming silently broke a script that relied on stdout redirection to produce its file
25. Adding a header without a matching placeholder value silently shifted eleven columns of data for every row
26. Trimming a header list without updating the values that fill it left the row-writer completely out of sync with its own headers

---

## 1. Identifier drift after re-ranking

**What happens.** The dataset carries more than one numbering scheme — an original intake order, a current rank, and IDs used by a companion artifact such as a network graph. After a re-rank, code that keys on "rank" attaches data to the wrong person.

**How it presents.** Silent. Entries look plausible because they land on *some* real person.

**Detection.** After any operation keyed by rank, print the resolved name alongside the ID and check it against the intended target. Cross-check two numbering columns for agreement.

**Fix.** Key everything by name or stable ID. When ranks must change, remap all dependent artifacts in one operation and verify by spot-checking names on both endpoints of several relationships.

*Observed:* co-authorship edges were added using an intake-order number where the graph used a different scheme; two edges connected entirely unrelated people. Also, a hard-coded birth year keyed by old rank landed on a different person after a re-sort, showing a 49-year-old as 79.

## 2. Formatting-based markers lost on sort

**What happens.** Categories are encoded as cell fill colour. Spreadsheet sorting moves values but leaves formatting attached to row positions.

**Fix.** Store the marker as a **value in a column**. Drive the visual with conditional formatting keyed to that column. Then sorting is safe.

## 3. Stale colour left behind on re-sort

**What happens.** Re-applying colours to the correct rows without first clearing the old ones leaves both — the correct set plus orphans at the old positions.

**Detection.** Count coloured rows; compare against the count of marked rows. Any excess is orphaned.

**Fix.** Always reset all rows to default first, then apply.

## 4. Contaminated author profiles

**What happens.** Author profiles merge same-name researchers from unrelated fields.

**How it presents.** A finance professor's profile contains cardiology or materials-science papers; citation counts and recency signals are inflated.

**Detection.** `resolve_v2._contamination_risk()` pulls the author's own aggregate `topics`/`x_concepts` and looks at their level-0 domain classification (e.g. "Medicine", "Computer Science", "Engineering"). A domain from the medical/health cluster co-occurring with a clearly non-medical one, or three or more distinct domains at once, is flagged automatically — no need to eyeball the topic list by hand. `find_author()` appends a `_profile_contamination_risk` suffix to `match_method` whenever this fires, and `batch_enrich.py` routes it to `needs_review_contaminated` even when it was otherwise the single, current-institution-verified candidate — this check runs on ANY resolved entity, including ones where no second candidate ever existed to compare against, which is exactly when the earlier institution/recency checks have nothing to catch it with.

**Fix.** Never trust a single-candidate "current institution verified" result as final on its own — this contamination check runs after that, and only the combination of both passing is auto-accepted. Filter to in-field work before computing any metric on a flagged record. Note the contamination so a later run does not re-trust it.

*Observed:* two separate roster members had profiles merged with medical researchers of the same name. A third, single-candidate case ("Wei Zhang") showed a cybersecurity paper, a medical-imaging radiomics paper, and a CAD/mesh paper all under one OpenAlex ID with institutions listing USTC, NTU, and a medical college simultaneously — a clean single-candidate match by every earlier check, since there was no second candidate for those checks to compare it against.

## 5. Placeholder rows satisfying data rules

**What happens.** A cell holds template text rather than data — a title field reading "recent three years", a venue field reading "working paper (2023)". A year-based rule reads the 2023 and treats the row as a current publication.

**Detection.** Flag titles that are empty, match a stop-list, or are very short with no Latin characters.

**Fix.** Strip placeholders *before* any rule runs. Preserve the original text in a note so the deletion is auditable.

*Observed:* a senior professor with no publications in five years received the top-tier activity bonus because a placeholder row contained a recent-looking year.

## 6. Surname-based co-authorship false positives

Covered in `verification-rules.md`. The headline: never match on surname alone. Real false positives observed include a surname matched from a city name, and a surname matched as a substring of a different given name.

## 7. Stale institutional pages and encyclopedia entries

**What happens.** A professor takes leave or moves; some pages update and others do not. Encyclopedia entries in particular can freeze a temporary position as if it were current.

**Detection.** Compare the encyclopedia/aggregator claim against (a) the person's own site, (b) the institution's current directory, (c) OpenAlex `last_known_institutions`. Check page copyright dates and contact addresses.

**Fix.** Weight the person's own CV highest, then the institution's own directory. Encyclopedia entries are the weakest source for current affiliation.

*Observed:* an encyclopedia entry listed a two-year academic leave as the current position and the actual employer as "previously". The person's own CV showed continuous employment at the supposedly-former institution throughout.

## 8. Systematically wrong link columns

**What happens.** A profile-link column is populated by a process that misaligns — an offset paste, a bad join — and links point at other people, often clustered in one institution's rows.

**Detection.** Compare the URL's domain against the recorded institution for every row. Report every mismatch. Exclude legitimate personal domains (`sites.google.com`, `github.io`, personal sites) from the mismatch list.

**Fix.** Re-source from an authoritative roster. Flag each corrected row.

*Observed:* 20 of 261 links pointed to unrelated people at other institutions, nearly all concentrated in one university's rows.

## 9. Industry gaps distorting age estimates

Covered in `verification-rules.md` §6. Detect with the `implied_gap` check and prefer bachelor-year-based estimation.

## 10. Prestige-journal lists mistaken for current activity

**What happens.** A publication list full of top-tier venues creates an impression of high activity even when every entry is old.

**Detection.** Always extract the **year** alongside the venue. Sort by year, not prestige. Check `counts_by_year` from OpenAlex for the actual trajectory.

**Fix.** Gate any activity assessment on recency before considering venue quality.

*Observed:* an assessment was reversed twice on the same person — first judged inactive from a stale institutional page, then judged active from a list of prestigious but old papers — before the year distribution was checked directly.

## 11. Supervision records from a previous institution

**What happens.** A CV lists doctoral students supervised and their placements. This is strong evidence — but if the person recently moved, those students graduated elsewhere.

**Why it matters.** Placement outcomes reflect the *previous* institution's brand plus the individual's ability, and cannot be separated from outside. The new institution may have a different programme, network, and placement record.

**Fix.** Record supervision history with the institution and years where it occurred. When there has been a recent move, state that the record predates it and recommend confirming current supervision status.

## 12. Validating with a more permissive tool than the target environment

**What happens.** Output is checked with a tool that tolerates malformed input, so a defect that the real consumer rejects passes verification.

**How it presents.** "It worked when I checked it" followed by a hard failure on the user's machine.

**Detection.** Validate against a schema or the strictest available parser, not against whichever renderer is convenient. Where a spec exists, check against the spec.

**Fix.** Choose verification tools that are *stricter* than the target environment, never more lenient. When only a lenient tool is available, say so rather than reporting the check as passed.

*Observed:* a generated document rendered correctly through a permissive office suite and was reported as verified. The target word processor refused to open it — an invalid attribute value produced by a type error in the generating script. Schema validation caught it immediately once applied.

**The general form of this failure appears throughout faculty research**, not only in file generation:

| Lenient check | Strict check that would have caught it |
|---|---|
| Institutional page shows no recent output → "inactive" | Author API shows current working papers |
| Publication list is full of top venues → "active" | Extract the **years**; the newest may be a decade old |
| Renderer opens the file → "valid" | Schema validation against the spec |
| Name matches → "same person" | Institution, field and coauthor overlap all match |

In every case the cheap check agrees with the expensive one most of the time, which is exactly what makes the disagreements dangerous — they are rare, silent, and load-bearing.

## 13. Lifetime affiliation history mistaken for current employment

**What happens.** An author's OpenAlex record lists every institution ever seen across their whole career. Checking "does the roster institution appear anywhere in this list" treats a stop from a decade ago the same as today's job.

**How it presents.** Two failure directions on the same bug: (a) several genuinely different people, sharing a common name, each having passed through the target institution at some point, all pass the institution filter and pile into one ambiguous group even though only one of them is actually there now; (b) a single real candidate is accepted with high confidence even though their most recent recorded affiliation is a different institution — the roster institution was correct years ago, not now.

**Detection.** Compare against the author's *most recent* recorded affiliation (by year, or OpenAlex's own `last_known_institutions`), not the full history set. Rank ambiguous candidates by how recent their evidence is, not only by paper count.

**Fix.** `institution_match_level()` classifies each candidate as `current` (target institution is the most recent one on record, or in `last_known_institutions`) vs `historical` (appears only earlier). Only `current` is auto-accepted; `historical` always routes to manual review (`possible_move` status) since the person may well have moved on since the roster page was written.

For deciding whether two *different* OpenAlex entities are actually one person split by a re-indexing artifact (the institution most likely one they moved to, and the OpenAlex entity was rebuilt rather than edited in place): check whether one record's most-recent institution appears anywhere in the other record's affiliation history (`_cross_recency_link`), and require this for **every pair** in the candidate group. This link alone is necessary but not sufficient — two different people at the same institution will also satisfy it. The actual gate is an exact match on fixed identity fields on top of it: full name (every token, not just surname-plus-initials compatibility) and, when both records carry one, an identical ORCID (`_identity_fields_match`). Topic overlap is kept as one more sanity check but is never sufficient by itself. One mismatching pair fails the merge for the whole group — no partial merges.

*Observed:* a roster row read "HKU"; three different OpenAlex identities all had "University of Hong Kong" somewhere in their affiliation history (one from over a decade ago, one current, one from a brief stint years back) and all three passed a history-based filter, forcing manual disambiguation that a recency check resolves automatically.

## 14. Silent API failures indistinguishable from genuine zero-result searches

**What happens.** Every OpenAlex request inside `find_author()` was wrapped in a bare `try/except Exception: continue`. If a request failed (timeout, transient 5xx, rate limit exhausted after the built-in retry/backoff) the loop just moved to the next name variant with no record of *why*. If every variant failed the same way, the function returned `[], "not_found"` — identical to the return value for "OpenAlex genuinely has zero authors matching this name."

**How it presents.** A batch run shows a NOT_FOUND rate that's higher than it should be for real professors with common, unambiguous names, with no way to tell from the output which NOT_FOUND rows are real ("this person may not be well-indexed, go verify manually") and which are actually "the API had a bad few minutes for this person specifically, re-running would likely find them."

**Detection.** Count attempted vs. failed API calls per person. If 100% of a person's calls raised an exception (as opposed to succeeding and returning zero matching results), that's a fundamentally different situation from a genuine empty search.

**Fix.** Track `attempted`/`failed`/`last_error` through `_find_author_inner()`. When every attempt failed, return `[], f"api_error: {last_error}"` instead of `"not_found"`. `batch_enrich.py` gives this its own `enrich_status` (`"api_error"`, distinct from `"not_found"`), prints a dedicated "re-run this" list at the end (these rows are never written to the cache, so simply re-running the batch retries exactly these people without re-processing everyone who already succeeded), and `confidence.py`'s `METHOD_BASE` table scores it the same as `not_found` (untrustworthy) while keeping the reason distinguishable in the stated rationale.

*Observed:* a real ~261-person roster run showed several genuinely-real, unambiguously-named professors (e.g. a person searchable by a distinctive, uncommon full name) coming back NOT_FOUND with 0 candidates — implausible for OpenAlex's ~90M+ author index unless something was silently swallowing the actual cause.

## 15. Substring keyword matching across unrelated category names

**What happens.** `journal_ranking.py`'s cross-domain contamination check (§8 of `journal-ranking-design.md`) buckets JCR's 254 categories into 7 coarse domains via keyword matching. Plain `keyword in category_string` substring matching does not respect word boundaries or field-name structure, so a keyword can match *inside* an unrelated word, or the wrong keyword can win when a category name legitimately contains terms from two different buckets.

**How it presents.** Concrete cases caught by auditing the full 254-category list against expected buckets: `"GEOCHEMISTRY & GEOPHYSICS"` (earth science) was bucketed as biology/chemistry because `"CHEMISTRY"` matched the middle of the word with no boundary check; `"COMPUTER SCIENCE, SOFTWARE ENGINEERING"` was bucketed as physics/engineering because the broad `"ENGINEERING"` keyword matched before the more specific `"COMPUTER SCIENCE"` keyword got a chance; `"PHYSICS, ATOMIC, MOLECULAR & CHEMICAL"` was bucketed as biology because `"MOLECULAR"` — intended to catch molecular-biology categories — also matches inside a physics category name. Any of these could make a genuinely single-field professor's papers look like they span unrelated domains, triggering a false contamination warning.

**Detection.** Dump every category the JCR file actually contains through the bucketing function and manually audit the assignments — the false positives are usually obvious once listed side by side (a category whose bucket doesn't match what its name plainly says).

**Fix.** Two changes: (1) require a word boundary immediately *before* a keyword match (`re.search(r"(?:^|[^A-Z])KEYWORD", cat)`, not `KEYWORD in cat`) — this alone fixes the GEOCHEMISTRY case, since there's no boundary before "CHEMISTRY" inside "GEOCHEMISTRY". (2) JCR categories consistently follow a "MAIN FIELD, SUBFIELD" naming convention; check the part before the first comma against all buckets *first*, falling back to the full string only if the prefix matches nothing. This is what correctly sends "COMPUTER SCIENCE, SOFTWARE ENGINEERING" to the computer-science bucket and "PHYSICS, MATHEMATICAL" to the physics bucket, without needing to hand-tune which bucket's keyword list is checked first.

*Observed:* a real run flagged 5 professors with contamination warnings, several spanning 4-5 domains simultaneously — implausibly high both in count and in spread. Re-auditing the bucket assignments against the actual 254-category list surfaced the keyword-collision bugs above as at least a partial (and for some of the flagged professors, likely the entire) explanation, rather than all 5 being genuine OpenAlex identity contamination.

**Follow-up (found while investigating an unrelated user question about a specific professor's evidence citations):** the opposite failure mode — a keyword too NARROW rather than too broad — also happened. `"MEDICIN"` was chosen to catch `"MEDICINE"`/`"MEDICINAL"` but doesn't match `"MEDICAL"` (a different word root: MEDIC-**IN** vs MEDIC-**AL**), so `"MEDICAL INFORMATICS"` and `"MEDICAL LABORATORY TECHNOLOGY"` fell through to `None` (unbucketed) despite obviously being medical categories. Fixed by adding `"MEDICAL"` as an explicit keyword alongside `"MEDICIN"`. One side effect worth noting rather than hiding: `"MEDICAL ETHICS"` — previously landed in 人文 via the `"ETHICS"` keyword (a defensible call noted when this bucket assignment was first reviewed) — now matches `"MEDICAL"` first (医学/临床 is checked earlier in the bucket list) and moved buckets. Left as-is rather than special-cased back, since medical ethics is genuinely debatable either way and this isn't a clear error the way the GEOCHEMISTRY-style collisions were — but flagged here in case a future audit disagrees.

## 16. Retry backoff repeated for every call in a degraded batch, and ambiguous ties left unresolved when a cheap signal could break them

**What happens.** Two related inefficiencies, both fixable with information already available at the point of the slowdown:

1. `_get()`'s retry/backoff (4 attempts, exponential 1.5/3/6s) runs at full strength for every single OpenAlex call `find_author()` makes for one person (up to ~8-10 calls: institution-filtered search × 2 filter types × up to 4 name variants, plus fallback name-only search). If OpenAlex has a bad few minutes, EVERY one of those calls independently pays the full backoff before failing — the first failure already proves the problem isn't a one-off blip, but nothing acts on that information.
2. `ambiguous_same_institution` (2+ candidates tied at the same institution, `_clean_single_institution_pick`'s stricter "1 clean vs 3+ noisy" pattern doesn't apply) always routes to manual review, even when `_contamination_risk()` — already computed for every candidate via `_fmt()` — shows one candidate has an implausible topic mix and the other doesn't. That's a real, already-computed signal going unused.

**How it presents.** (1) A single person's lookup can visibly stall for a minute or more in the batch log with no progress, then resolve to `api_error`. (2) The `AMBIGUOUS` count in a batch run's summary is higher than necessary — some fraction of those ties have one obviously-contaminated candidate and one plausible one, and a human reviewing them would reach the same conclusion `_contamination_risk()` already reached, just slower.

**Fix.**
1. `_get()` takes a `max_attempts` parameter. `_find_author_inner()` tracks a `degraded` flag, set True after the first full-retry-exhaustion failure in that person's lookup; every subsequent call for the same person then uses `max_attempts=1` (no backoff sleep). Also removed a real (if smaller) waste present even in the non-degraded path: the original code slept after the *last* retry attempt too, even though no further attempt would ever follow it.
2. Extended `_contamination_risk()` beyond the medicine-specific check with an explicit, field-level "implausible pair" list: `_HARD_SCIENCE_FIELDS` (Medicine, Physics and Astronomy, Chemistry, Biochemistry/Genetics/Molecular Biology, etc.) vs `_SOCIAL_QUANT_FIELDS` (Business/Management/Accounting, Economics/Econometrics/Finance, etc.), checked against OpenAlex's own 26-field topic level (`topic.field.display_name` — verified against OpenAlex's published taxonomy, docs.openalex.org), not the coarser 4-value domain level a naive check would reach for first. Computer Science, Mathematics, Engineering, Environmental Science, and Psychology are deliberately on NEITHER list — they legitimately bridge both sides in ordinary careers (fintech, quant finance, computational social science, health economics) and must not trigger a false flag. In `_find_author_inner`, after `_clean_single_institution_pick` fails to apply, candidates are narrowed by excluding any with `contamination_risk=True`; if exactly one survives, it's picked (`matched_on_current_institution_excluding_contaminated_candidates`) instead of falling through to manual review. Two equally-clean (or equally-risky) candidates still correctly fall through to `ambiguous_same_institution` — this only resolves the case where the signal actually discriminates between the tied candidates.

A subtlety worth keeping in mind when extending either check further: domain-level and field-level names must be counted in *separate* sets, never merged into one. An earlier version of this fix mixed them together and broke the existing `len(domains) >= 3` fallback — merging inflates the count for everyone, since each topic contributes both a domain name and a field name, not because the author actually spans more distinct areas. A test candidate with legitimate Finance + Computer Science topics was flagged as contaminated purely from this inflation before the sets were split apart and verified against constructed test cases (clean finance-only, finance+physics, finance+CS, biology+finance, medicine+finance, and a pure-economics "health economics" profile that must NOT be flagged).

*Observed:* a real batch run showed a single request taking close to two minutes before returning `api_error`; the same run's ambiguous list included several two-candidate ties. Testing against a mocked two-candidate scenario (one Finance-only, one Finance+Medicine) confirmed the resolvable case is now picked automatically, while a mocked two-candidate scenario where both are equally clean (Finance vs Business, neither showing contamination) correctly still routes to manual review rather than guessing between them.

## 17. Vote-based "primary field" is fragile with few papers, and a blocking check was the wrong response to a false positive

**What happens.** Two compounding design mistakes in `journal_ranking.py`'s domain-mix check, both surfaced by the same real feedback:

1. **The check blocked recommendations entirely.** An earlier version treated any detected domain mixing as "possible identity contamination" and skipped `pick_representative_papers()` outright when it fired. But mixing a finance professor's output with information-systems or statistics journals is completely ordinary — not a sign a different person's work got merged in — and blocking recommendations for that case is a straightforward false-positive cost with no corresponding benefit.
2. **"Primary field" was decided by raw paper count**, with no floor on sample size and no tolerance for single-paper noise. With only 2-3 JCR-matched papers, calling either bucket "primary" is arbitrary. And even with more papers, if a professor happens to have published slightly more papers in an off-field journal in the specific window being checked than in their actual field (a real, unremarkable possibility — a multi-year window can catch an unusual publication mix by chance), pure vote-counting mislabels the professor's ACTUAL field as the anomaly.

**How it presents.** A finance professor with a couple of stats/IS papers gets flagged and loses their recommendations. Separately, a professor whose window happens to have (say) 3 papers in a tangential field and 2 in their real field gets that real field treated as the "deviation," inverting the intended signal.

**Fix.** Reframed the whole check from "possible identity contamination, block recommendations" to "research-direction note, informational only" (see `references/journal-ranking-design.md` §8 for the full current design) with several supporting rules:
- `pick_representative_papers()` is now always called, unconditionally — the mix note is attached alongside the result, never gates it.
- `BRIDGE_BUCKETS` (currently just 计算机/数学/统计) is excluded from the off-field count entirely, regardless of ratio.
- `MIN_WINDOW_A_PAPERS_FOR_MIX_CHECK = 4`: below this many matched papers, skip the check rather than force an answer from too little data.
- `MIN_BUCKET_PAPERS_TO_COUNT = 2`: a single paper in an off-primary bucket doesn't count toward the ratio — more likely JCR misclassification noise (see #15) than a real second research direction.
- **Primary field is anchored to the user's own `--field-major` input when it matches one of the buckets present**, falling back to vote-by-paper-count only when `--field-major` isn't given or doesn't map onto anything in this professor's window. This directly fixes the "off-field papers happen to outnumber real-field papers in this window" case — the user's prior knowledge of the roster is a steadier signal than a per-window vote.
- Institution-count leniency (raise the ratio bar from 50% to 65% when `len(affiliation_institutions) <= 3`) is retained from the previous iteration.
- The note's `examples` field now lists every qualifying paper per off-field bucket (not just one), and `merge_to_excel.py` renders those titles directly into the Excel cell — so a reader can judge "is this really a shift, or just a misclassified paper" without opening the raw JSON.

*Observed:* constructed test cases confirmed each rule independently — 2 papers total (below the sample floor) never flags regardless of split; a single off-field paper among several real-field ones never counts; finance+statistics at 50% never flags (bridge exemption) even at high ratios; and specifically, a case with 3 medicine papers and 2 finance papers, with `--field-major "Business, Finance"` supplied, correctly anchors "商科/经济/管理" as primary and flags the medicine papers as the deviation (60% off-field) — where vote-counting alone would have picked medicine as primary and found nothing to flag. Recommendations were confirmed present (non-empty) in every one of these cases, including the ones that do produce a note.

## 18. A single ratio threshold conflated "implausible" with "uncommon" — they need independent trigger rules, not one shared bar

**What happens.** #17's fix (bridge exemption + a single 50%/65% ratio bar) was a real improvement but still treated every kind of off-primary mixing the same way: one ratio threshold, one outcome shape (note vs. nothing). That conflates two very different situations. "Finance professor with a couple of information-systems papers" and "finance professor with several oncology papers" are not the same kind of evidence, and treating them with the same bar under-reacts to the second case and (if the bar is tuned down to catch it) over-reacts to the first.

**How it presents.** With one shared threshold, there's no way to say "even ONE or TWO papers in an impossible field is worth flagging" without ALSO flagging routine bridge-field crossover at the same low bar — the two needs pull the threshold in opposite directions and neither gets served well by a single number.

**Fix.** Replaced the single ratio check with three independent branches, keyed off a per-pair relationship (`bucket_relationship()` — see `references/journal-ranking-design.md` §8 for the full family-default + exception table, covering 17 domain buckets grouped into 5 families: 商科/硬科学/量化/人文社科/地球环境):

- **❌ reject** (e.g. 商科 × 医学): a *count* rule, not a ratio — more than 1 paper blocks the professor's tier/recommendations entirely (with a stated reason); exactly 1 paper is treated as noise and that bucket is excluded from downstream processing rather than either accepted or blocking.
- **🟡 rare** (e.g. 商科 × 心理学 — a real but small crossover field): a ratio rule with a low bar (30%), because a real secondary interest legitimately shows up as a meaningful minority of output, not just 1-2 stray papers.
- **✅ bridge** (e.g. 商科 × 计算机科学): a ratio rule with a high bar (50%), because ordinary crossover careers can plausibly have HALF their output in the bridge field without that being remarkable.

All three respect an institution-count modifier (`rec["affiliation_institutions"]`, the full career-affiliation history, not current employer): at ≤4 institutions, a rare/bridge ratio above its bar produces an informational note; above 4 institutions, the same ratio produces a block instead — a career spanning many institutions combined with a high off-field ratio reads as less consistent with "one person, one coherent research trajectory" than the same ratio in a short career. Priority order is reject > rare > bridge; only the first branch that produces any result (note or block) is reported.

Splitting the check this way also surfaced that the family-default table itself needed the buckets to be finer than #17's 7 coarse groups — 商科/心理学 (real, established) and 商科/物理 (essentially nonexistent) were both stuck in one "社会科学/心理/教育/法律" bucket under the old scheme and couldn't be told apart. Split into 17 buckets across 5 families specifically so pairs like these could get different relationship judgments.

Architecturally, the exclusion outcome (reject-branch, exactly 1 paper) has to be resolved BEFORE tier classification and representative-paper picking, not after — it changes what "this professor's papers" means for both. `classify_professor()` was simplified back to a pure decision tree with no domain-mix awareness of its own; `main()` now calls `resolve_domain_signal()` once, applies any exclusion to both window A and window B, and only then calls the tier/pick functions. This depends on window B always being a subset of window A's papers (`--window-b-since >= --window-a-since`) — `main()` now validates this at startup and exits with an explanation if violated, rather than silently producing an inconsistent exclusion.

*Observed:* constructed test cases confirmed each branch independently — 2 reject-relationship papers blocks entirely; exactly 1 excludes that bucket and still evaluates the remaining rare/bridge signal afterward (confirmed a case with 1 reject-paper AND a high bridge-ratio correctly falls through to flag the bridge branch, with the block_reason correctly reflecting the bridge trigger rather than stale reject-branch text); a rare-relationship pair at 40% flags as a note at ≤4 institutions and as a block at >4; a bridge-relationship pair at 60% shows the same note/block split at the same institution-count boundary. All 22 specific relationship pairs from the design discussion (neuroeconomics=bridge, agricultural economics=rare, physics×law=reject, etc.) were verified against the actual `bucket_relationship()` implementation, and all 254 real JCR categories were re-verified against the new 17-bucket keyword table, including every category that previously triggered a bug under the old 7-bucket scheme (§15/§17).

## 19. Reversed Chinese name order silently defeated identity matching, with the wrong candidate auto-accepted at high confidence

**What happens.** Two independent bugs compounded into the worst possible outcome — not a flagged ambiguity, but a *confident, wrong, auto-accepted* match — for a roster name whose word order differs from OpenAlex's stored `display_name` order for the correct candidate:

1. **`institution_match_level()`'s ±1-year recency tolerance was fooled by an unrelated institution.** The tolerance was written for a simple, two-institution "just moved" profile: author moves from A to B, and a paper can still carry A's affiliation string for a year that (in OpenAlex's data) slightly post-dates the real move. The implementation instead compared the target institution's own latest year against `max()` of *every* institution in the author's whole history — for a scattered profile with several unrelated institutions, the target institution's one lone year can land "within 1 year" of some completely different, unrelated institution's latest year purely by coincidence, with no real transition connecting them. A scattered multi-institution profile is itself a signal this whole check exists to catch (a merged/contaminated OpenAlex ID), so it should get *less* benefit of the doubt from the tolerance, not the same amount as a clean two-institution profile.
2. **`name_matches()` re-derived "surname" from the raw, un-reordered roster string using a blind "last token = surname" fallback, independent of which search variant actually found the candidate.** `name_variants()` already generates both word orders as separate search queries specifically to handle Chinese-name order ambiguity, and the sibling check `name_compatible(variant, candidate)` correctly re-checks compatibility once per variant — so as long as *some* variant's word order matches the candidate's own `display_name` order, `name_compatible` passes correctly. But `name_matches(name, candidate)` used the fixed original roster string every time, regardless of which variant was being evaluated. When the roster lists "Wei Zhang" (Chinese surname-first order) and the correct candidate's OpenAlex `display_name` is "Zhang Wei" (Western given-name-first order — the same two tokens, reversed), `name_matches` computed surname="zhang" for the roster (blindly taking the last token) and surname="wei" for the candidate, concluded they disagreed, and rejected the correct candidate outright — while a *different, wrong* person whose `display_name` happened to already be "Wei Zhang" (matching the roster's raw token order) sailed through this check untouched.

**How it presents.** With the correct candidate rejected by bug 2 before it's even pooled, and the wrong candidate's institution recency incorrectly upgraded to "current" by bug 1, `_find_author_inner`'s candidate pool narrows to exactly one candidate — the wrong one — and returns `matched_on_current_institution_verified`, the *highest*-confidence match method. No ambiguity is ever flagged; nothing in the output looks different from a genuinely correct high-confidence match. The roster's professor gets a completely different real person's papers, topics, and (downstream) journal-quality tier and representative-paper recommendations, all reported with full confidence.

**Detection.** This one wasn't caught by internal testing — it required a user manually cross-checking a specific record against OpenAlex's own website (searching the roster name with an institution filter) and noticing the papers shown there had nothing in common with what the pipeline reported. A dedicated diagnostic script (querying the exact ID directly, then replaying the institution-filtered search the code performs, then a name-only unrestricted search) pinned down exactly which step in the pipeline dropped the correct candidate and which step promoted the wrong one.

**Fix.**
1. `institution_match_level()`: the ±1-year tolerance now only applies when the author has 2 or fewer institutions on record (`len(year_map) <= 2` — a genuine simple-transition profile); with 3+, the target institution's year must exactly equal the author's own overall latest year to count as "current."
2. `name_matches()` was removed entirely — both its call site in `_find_author_inner` and the function definition itself (`_split_name()`, only ever called by `name_matches()`, was also dead code afterward and removed) — since `name_compatible(variant, candidate)`, checked immediately after in the same loop, already provides equivalent protection *correctly*, because it's evaluated once per generated name variant rather than once against a single fixed string.

*Observed:* reproduced bug 1 exactly using the real author record from the diagnostic (5 scattered institutions, target institution's lone year 1 short of an unrelated institution's latest year) — `institution_match_level` returned `"current"` before the fix, `"historical"` after. Reproduced bug 2 directly — `name_matches("Assoc Prof Wei Zhang", "Zhang Wei")` returned `False` while `name_compatible("Zhang Wei", "Zhang Wei")` (the variant that actually found this candidate) returned `True`, confirming the redundant check was the one rejecting a correct match its sibling check already accepted. A full end-to-end reconstruction using all three real candidate records from the diagnostic (the wrong 5-institution profile, the correct finance professor, and a third unrelated materials-science homonym) confirmed that before both fixes, `find_author()` returned the wrong candidate alone with `matched_on_current_institution_verified`; after both fixes, it returns the correct candidate alone with the same high-confidence method. A separate regression case (searching "Ka Yan Lee" against a same-surname-different-given-name "Ka Wing Lee") confirmed `name_compatible` alone still correctly rejects genuine surname-only collisions after `name_matches` was removed — the fix didn't weaken that protection, it only removed the order-blind duplicate of it.

**Follow-up: fixing bugs 1 and 2 does not remove the underlying structural risk.** Even with both fixes, name+institution matching for Chinese names has an irreducible blind spot: trying both word orders (`name_variants()`) tells you nothing about which token is *actually* the surname, so if two genuinely different real people happen to have their surname/given-name compose the same two tokens in reversed order (not the same person recorded twice — two different people whose names are literal anagrams of each other), both could legitimately pass `name_compatible` under different variants. A "unique candidate" from institution+name matching is therefore not, on its own, sufficient grounds for full confidence — it can mean "matching worked" just as easily as "matching picked the wrong same-two-tokens person."

Added a second, independent check specifically for the case where institution+name narrows to exactly one candidate: if `--field` is configured, that single candidate's OpenAlex topics are checked against `FIELD_HINTS` for zero overlap *before* returning a confident match — not just when there were multiple candidates to disambiguate between (the pre-existing `field_score` narrowing only ever ran in that case, and therefore never got a chance to catch this exact failure, since institution+name had already wrongly narrowed to one). A hard zero-overlap match now returns a distinct `field_mismatch_needs_review` status instead of continuing toward any other resolution path — deliberately not treated as "ambiguous, try to narrow further," since the single-candidate framing that produced it may itself be untrustworthy; it goes straight to manual review with the mismatched topics shown alongside it, the same as `needs_review_contaminated`.

*Observed:* constructed a single-candidate case with topics entirely unrelated to `field="finance"` (face recognition / medical imaging) — confirmed `find_author()` now returns `field_mismatch_needs_review` with the candidate's actual topics included in the reason string, rather than silently returning `matched_on_current_institution_verified`. Confirmed the check does NOT fire when `field` isn't configured (no regression for callers that don't use this parameter) and does NOT fire when the single candidate's topics genuinely do overlap with the configured field. Ran the new status through the full `batch_enrich.py` → `confidence.py` → `merge_to_excel.py` chain: routes to `enrich_status="needs_review_field_mismatch"` (never silently merged into "ok"), scores as untrustworthy (base score 5, same tier as `not_found`), and the roster-sheet summary now reports a dedicated count alongside the existing contamination count.

## 20. A retry/cooldown mechanism can't fix a missing credential — OpenAlex made API keys mandatory in Feb 2026

**What happens.** OpenAlex retired its `mailto`-based "polite pool" and made API keys mandatory for all requests starting February 13, 2026 (announced Feb 4, effective Feb 13; see the official changelog and blog post). Without a key, a caller gets roughly 100 free demo credits per day; every request after that fails. This project's identity-resolution code — written before this change — only ever sent `mailto`, never an `api_key`, so any real batch run exhausts the demo allowance within the first 10-20 people (each person's lookup can issue 5-15+ calls: institution resolution, multiple name-variant × filter combinations, profile fetch, works fetch) and then fails for essentially everyone after that.

**How it presents.** A batch run shows a clean run for the first several dozen people, then `api_error` on every subsequent person, in a sustained streak — not occasional, not recoverable by waiting. The specific exception text matters here: `_get()`'s retry logic distinguishes an HTTP 429/5xx response (retried with backoff) from a raw connection failure (`requests.exceptions.RequestException`, also retried but captured as `last_exc`); when every attempt gets a 429/5xx and none raises a connection-level exception, `last_exc` stays `None` and the generic `RuntimeError("OpenAlex request failed after retries")` fires — which is exactly the message a credit-exhausted, no-API-key caller would see, since the server is responding, just refusing the request.

**Why the existing cooldown mechanism (see #16, and the later cross-person circuit breaker) can't fix this.** Both were built on the assumption that a failure streak is a *rate* problem — too many requests per second, or a transient server-side hiccup — that resolves itself given enough wall-clock time. A missing/absent API key is not that kind of problem: the daily demo allowance doesn't refill on a 30-second, 60-second, or even 5-minute timescale (the circuit breaker's cooldown cap), so extending the cooldown indefinitely would still never recover mid-run. This was directly observed: a user reported the circuit breaker's cooldown growing to 60s, then 120s, with `api_error` resuming immediately after every cooldown — proof the backoff assumption itself was wrong for this failure mode, not that the backoff parameters needed tuning.

**Fix.** Added a module-level `API_KEY` to `resolve_v2.py` and `fetch_openalex.py` (each has its own independent `_get()`), read automatically and included as the `api_key` query parameter whenever set — chosen over threading a new parameter through the dozens of functions that already pass `mailto` around, which already existed at every relevant call site and would have needed touching individually for the same effect, a much larger and more error-prone change. Every script that hits the OpenAlex API (`batch_enrich.py`, `merge_to_excel.py`, `openalex_links.py`, `resolve_identity.py`, `reverse_lookup.py`, `apply_manual_review.py`, `fetch_openalex.py`'s own CLI) got a `--api-key` argument that sets this at the start of `main()`. The notebook's config cell gained an `API_KEY` field (placed above `EMAIL`, since it's now the credential that actually determines whether requests succeed) with a loud warning printed if left blank, and every `cmd = [...]` construction that already passed `--mailto EMAIL` now also passes `--api-key API_KEY`.

*Observed:* confirmed via OpenAlex's own changelog (`help.openalex.org`, entries for Feb 4 and Feb 13, 2026) and blog post that the mandatory-key change is real and dated correctly relative to this project's training-data cutoff (Jan 2026) — this is a genuine post-cutoff breaking change, not a pre-existing detail that was simply missed. Verified end-to-end with mocked requests that `api_key` is correctly included in outgoing request parameters from both `resolve_v2._get()` and `fetch_openalex._get()` independently, and that `batch_enrich.py --api-key VALUE` correctly sets the module-level credential on both modules it imports. Extracted the exact scripts from the delivered notebook file and re-ran the same check against them directly (not just the on-disk copies) to confirm the notebook's `%%writefile` cells and `cmd = [...]` constructions actually carry the fix, not just the underlying script files.

## 21. Three independent institution-matching implementations all silently relabeled "couldn't verify" as "confirmed mismatch"

**What happens.** Once #20's API-key requirement started causing real credit exhaustion mid-run, a downstream symptom surfaced that looked, at first glance, unrelated: a large batch of professors who were correctly identity-matched (`enrich_status == "ok"`) got flagged as having a mismatched institution — e.g. roster institution "NUS" against OpenAlex's own recorded "National University of Singapore," which is obviously the same place. This project has THREE independent places that compare a roster institution abbreviation against OpenAlex's expanded institution name, and all three had a version of the same underlying flaw: when the abbreviation can't be expanded (no cached alias, and — now — no working network/credit to resolve one fresh), each implementation fell back to a raw substring comparison between the un-expanded abbreviation and the full name. "NUS" is not a substring of "national university of singapore" and never will be, so this fallback doesn't degrade gracefully into a weaker-but-still-useful check — it degrades into a check that is *always* wrong for a pure-initialism abbreviation, indistinguishable from a genuine mismatch.

**The three sites, each slightly different:**
1. **The notebook's own inline preview cell** (a `Counter`/status-summary cell right after `batch_enrich.py` runs) — the crudest of the three: `roster_institution.split()[0].lower() in openalex_name.lower()`, with no attempt at abbreviation resolution at all, not even a network attempt. Always wrong for a bare acronym.
2. **`merge_to_excel.py`'s `_institution_mismatch()`** — does properly attempt `resolve_v2.resolve_institution()` first (alias file, then network), but when that call raised an exception (credits exhausted) or returned nothing, the function fell through to the same raw-substring fallback and returned a plain boolean — collapsing "couldn't verify" into the same `True` (mismatch) result as a genuine confirmed difference.
3. **`confidence.py`'s `_inst_agrees()` / the `resolve_v2.same_institution()` it calls** — never attempts a live network resolution at all (this script is deliberately designed to be pure computation over already-fetched data); it only checks the local alias table, and when the abbreviation isn't in it, `same_institution()` itself falls back to the same substring approach, again returning a plain boolean that collapsed the two cases.

**How it presents.** A real run showed 66 people — all with `enrich_status == "ok"`, meaning identity resolution had already succeeded — flagged with an institution-mismatch warning, phrased in a way ("少见，建议抽查" / "机构与名单不一致") that reads as a genuine data-quality concern worth manually checking one by one. In `confidence.py`'s case, this also silently cost each of these 66 people 15 confidence points and an `institution_mismatch` flag, potentially demoting an otherwise-solid match into a "needs manual review" tier for no real reason.

**Fix.** All three now distinguish "confirmed mismatch" from "couldn't verify," and no longer treat the latter as the former:
- `merge_to_excel.py`'s `_institution_mismatch()` now returns `"match"` / `"mismatch"` / `"unknown"` instead of a boolean; only `"mismatch"` triggers the `⚠ 需核实` flag and counts toward `n_moved`, and `"unknown"` gets its own distinct, much softer note in the same column.
- `confidence.py`'s `_inst_agrees()` now checks whether the roster abbreviation actually had a cached alias expansion *before* trusting a "no match" verdict from `same_institution()`; if there was no expansion to compare against, it returns `None` (unknown) with only a small -2 point deduction and a message stating plainly that this doesn't mean a real mismatch, instead of the previous -15 and an alarming flag.
- The notebook's inline preview cell now imports `resolve_v2` directly and reuses the exact same alias-aware resolution `merge_to_excel.py` uses (including setting the module-level `API_KEY` explicitly, since this is an in-process call rather than a subprocess with its own argument parsing), splitting its output into a "confirmed mismatch" list and a separate, clearly-labeled "couldn't verify" count.

*Observed:* reproduced the exact false-positive with "NUS" / "National University of Singapore" in isolation for `merge_to_excel.py`'s and `confidence.py`'s functions before the fix (both returned a mismatch signal despite this obviously being the same institution), confirmed the fix distinguishes the two cases correctly in isolation for each of the three implementations independently, and confirmed a genuine mismatch (roster says one institution, OpenAlex-record says an unrelated one, alias resolution succeeds) still correctly reports as a real mismatch in all three — the fix narrows what counts as a confirmed mismatch, it doesn't suppress real ones. Extracted the actual notebook cell content and ran it directly (not a hand-written equivalent) to confirm the delivered notebook, not just the underlying script files, carries the fix.

## 22. Two separate cache files, only one backed up — and a redundant institution-search query that doubled the credit cost for no benefit

**What happens, part one: the missing second cache file.** This project maintains two entirely separate on-disk caches: `.openalex_cache.json` (keyed by `name|institution|field|since`, holding each *person's* full enrichment result once successfully resolved) and `assets/institution_aliases.json` (keyed by the raw roster institution string, holding each *abbreviation's* resolved OpenAlex ID and canonical name — "NUS" → "National University of Singapore"). A user who ran out of API credits mid-batch, then backed up and re-uploaded `.openalex_cache.json` into a fresh Colab session to continue, found that people who had *already been successfully identity-matched* (their person-level cache entry present and correct) still showed up as "institution mismatch" — because the institution-alias cache is a different file that was never backed up or restored, and a fresh session's copy only has the small hardcoded seed list (a dozen or so common HK/Singapore institutions), not whatever else got resolved and learned during the original run. The institution-mismatch check genuinely needs a fresh network/credit-consuming resolution for any abbreviation not in that specific file — no amount of the person-level cache being present compensates for it.

**What happens, part two: a redundant query baked into every single person's lookup.** Independent of the above, `_find_author_inner()`'s institution-filtered search always issued TWO separate OpenAlex queries per name variant — one filtered by `affiliations.institution.id` (the person's full career affiliation history) and one filtered by `last_known_institutions.id` (their current institution specifically) — even though the full author object OpenAlex returns from either query already carries its own `last_known_institutions` field. The second query's only real purpose, computing `institution_match_level()`, can be computed entirely from the first query's results; the second query almost never adds a candidate the first one didn't already surface (a real API credit budget is the wrong place to pay for that overlap on every single person, every single variant).

**Fix.**
1. Made the institution-alias cache part of the same backup/restore workflow as the person-level cache: the notebook's download step now also downloads `assets/institution_aliases.json` alongside `.openalex_cache.json` and `enriched.json`, and a new optional step right after the seed alias file gets written lets a user upload both files to resume a prior session — explicitly documented as "these two files are both required, backing up only one still leaves the institution check unable to verify anything new."
2. `_find_author_inner()`'s institution search now tries only `affiliations.institution.id` per variant by default, falling back to the `last_known_institutions.id` filter *only if the first query returned zero results* for that variant — preserving the (rare but real) case where OpenAlex's "last known" field is fresher than what's reflected in the affiliations history, while cutting the common-case query count for this stage roughly in half.

*Observed:* confirmed against the user's actual uploaded `enriched.json`/`. openalex_cache.json` pair that Prof. A's record already had a correct, complete `effective_institutions: ["National University of Singapore"]` from a successful prior match — the person-level data was never the problem, confirming the diagnosis was specifically the missing alias file rather than anything wrong with identity resolution itself. Verified the query reduction with mocked requests: a successful single-candidate lookup across 2 name variants dropped from up to 4 institution-search calls to 2 (no fallback needed), while a constructed edge case (candidate only findable via `last_known_institutions.id`, not `affiliations.institution.id`) confirmed the fallback still fires and finds them — the optimization narrows redundant querying without losing any candidate the old two-query-always approach would have found. Re-ran the full existing regression suite (api_error, not_found, the Zhang Wei reversed-name-order case, same-surname-different-person rejection) against the modified code to confirm none of it regressed; caught and fixed a real `nonlocal` scoping bug introduced during the refactor (a variable referenced inside the new nested helper function wasn't declared `nonlocal`, causing an `UnboundLocalError`) via that same regression pass, before it ever reached delivery.

## 23. An unguarded float() on a raw spreadsheet cell crashed the entire run on the first malformed JIF percentile

**What happens.** `load_jcr()` read the "JIF百分位" and "影响因子JIF" columns straight from openpyxl with no type validation, storing whatever the cell contained verbatim. Most cells are numeric as expected, but some rows in the real JCR file have an empty string (`''` — not `None`, not `NaN`, an actual zero-length string) in this column, a real spreadsheet data-quality artifact rather than anything this project's code produced. `effective_percentile()`'s fallback path (used when a journal has no parseable per-category detail, i.e. `学科类别 == "Multiple"` with no usable breakdown) called `float(pct)` directly on this value — `float('')` raises `ValueError`, crashing the entire batch run the moment `journal_ranking.py` encountered the first paper published in one of these journals, with a traceback that gives no indication which journal or which professor triggered it.

**How it presents.** `journal_ranking.py` crashes outright partway through `main()` — not a per-person failure that gets logged and skipped (unlike the `api_error`/`not_found` handling elsewhere in this project), a hard stop that produces no `ranked.json` at all, for the whole batch, regardless of how many other people would have processed fine. The traceback bottoms out in `effective_percentile`, three frames deep from the top-level annotation loop, giving no direct clue that the root cause is a single malformed cell in the user-supplied JCR spreadsheet rather than a logic bug.

**Fix.** Added `_to_float()` — a coercion helper that returns `None` on ANY failure (empty string, non-numeric text, `None` itself) instead of raising — and applied it at the point `load_jcr()` first reads `jif_percentile` and `jif` from the raw spreadsheet, rather than defensively re-checking at every downstream site that consumes those fields. `_parse_category_detail()`'s own percentile derivation was already safe (it only ever computes from regex-captured, guaranteed-numeric rank/total groups; a non-matching row is silently skipped rather than partially parsed), so this fix is scoped to the two top-level columns that were read as raw, unvalidated cell values.

*Observed:* reproduced the exact crash with a constructed JCR row (empty-string JIF百分位, no per-category detail, forcing the vulnerable fallback path) before the fix, confirmed it no longer raises and instead correctly falls through to a `None` percentile after the fix — which itself correctly falls through further to the "default" (④) tier rather than being silently miscounted as a strong or weak signal either way. Loaded the full real 22,643-row JCR file post-fix and counted 2,306 rows with a `None` percentile and no per-category detail — confirming this wasn't a rare, hard-to-hit edge case; roughly 1 in 10 rows in the real spreadsheet had this exact shape, making the crash effectively inevitable for any roster large enough to touch a reasonable spread of journals.

## 24. Switching to real-time output streaming silently broke a script that relied on stdout redirection to produce its file

**What happens.** `openalex_links.py` was designed around shell-style stdout redirection: it only ever `print()`s its markdown report, with the documented usage being `python openalex_links.py --roster enriched.json > 待人工确认.md`. Every other script this notebook runs writes its own output file directly via an explicit `--out` argument, so when the notebook's various `subprocess.run(...)` calls were converted to a shared `run_streaming()` helper (to fix a much earlier problem — output being buffered until the whole process exited, making a multi-hour batch run look hung), `openalex_links.py` was converted the same way as everything else. But `run_streaming()` only prints each line live and discards it — nothing captures the accumulated text into a file, and `openalex_links.py` has no `--out` flag to fall back on. The cell that runs it silently stopped producing "待人工确认.md" the moment this conversion happened; the very next cell, which tries to `files.download("待人工确认.md")`, then fails with `FileNotFoundError`.

**How it presents.** No error at the point of failure — the streaming cell runs, prints its markdown-formatted report to the screen exactly as expected, and exits cleanly. The failure only surfaces one cell later, at the download step, with a traceback that gives no hint the actual cause is upstream. A user seeing this would reasonably suspect the download step itself is broken, when the real issue is that the file it's trying to download was never written in the first place.

**Fix.** Added an optional `save_to` parameter to the shared `run_streaming()` helper: when given a file path, it accumulates the streamed lines (which it's already iterating over to print) into a list and writes them to that path once the subprocess exits, in addition to — not instead of — the existing live-printing behavior. Every other `run_streaming()` call site is unaffected (the parameter defaults to `None`, and every other script it invokes already writes its own file via `--out`); only the `openalex_links.py` cell was updated to pass `save_to="待人工确认.md"`, restoring the file it's supposed to produce.

*Observed:* extracted the actual notebook cells (the updated `run_streaming` definition and the updated `openalex_links.py` invocation) and ran them directly against a constructed `enriched.json` with one ambiguous record — confirmed `待人工确认.md` is now created with the correct markdown content, matching what streams to the screen. Audited every other `run_streaming()` call site in the notebook (7 others) and confirmed all of them already pass `--out` to the script itself rather than depending on stdout capture — `openalex_links.py` was the only one exposed to this regression, not a systemic pattern across the notebook.

## 25. Adding a header without a matching placeholder value silently shifted eleven columns of data for every row

**What happens.** `merge_to_excel.py`'s roster sheet is built from two parallel lists that must stay the same length and in the same order: `NEW_COLS` (the header titles) and `vals` (the per-row values, zipped against those headers positionally). When the "人工核实结果" input column (see pitfalls.md #22's backfill workflow) was added, it was added to `NEW_COLS` — but the corresponding `vals` list, which is built separately by hand as a literal list of expressions, was never given a matching placeholder entry. From that column onward, every single value in `vals` landed one position earlier than the header it was actually written under: `OA_合并记录说明`'s column showed the confidence score, `OA_可信度分`'s column showed the confidence level string, and so on through all eleven columns from `OA_合并记录说明` to `JR_代表作预览` — the final column, `JR_代表作预览`, ended up with nothing at all, its rightful content having been absorbed one column early by `JR_代表作数`.

**How it presents.** No error, no warning — `merge_to_excel.py` runs cleanly and reports success, because Python doesn't care that a list has the right length for the wrong reason (it's just shorter by one, and `zip`/positional assignment silently accepts that). The spreadsheet opens fine and every cell has *some* plausible-looking value in it — a column apparently showing "3" instead of a research-direction note doesn't obviously look broken at a glance; it takes comparing what a column's *header* promises against what's actually in it to notice the mismatch. This shipped in every Excel this pipeline produced from the point "人工核实结果" was added until a user reviewing their actual results asked why the JR_研究方向偏移提示 column showed a bare number — at which point checking column-by-column against a controlled test row made the eleven-column shift immediately obvious.

**Fix.** Added the missing placeholder (an empty string, since this column is never populated by the script — it exists for the user to fill in) into `vals` at the exact position matching where "人工核实结果" sits in `NEW_COLS`.

*Observed:* ran a genuine end-to-end pipeline (`batch_enrich.py` → `journal_ranking.py` → `confidence.py` → `merge_to_excel.py`, with realistic mocked OpenAlex responses producing one fully-successful "ok" record) and printed every one of the resulting 27 script-written columns' header alongside its actual value for the single data row — confirmed each column now holds content of the semantically correct type and shape (e.g. `JR_学术分档` holds a short tier label like "①高质量期刊作者", not a paragraph of reasoning text; `OA_可信度分` holds a plain integer, not a level string; `人工核实结果` is empty, as an input-only column should be). This is the kind of bug an isolated unit test on one function can miss entirely — `_institution_mismatch()`, `_inst_agrees()`, and every other individually-tested piece of logic throughout this project's fixes were each correct on their own; the break was purely in how two independently-maintained lists were kept in sync with each other, which only a full, real, output-inspecting integration run — not a function-level test — was positioned to catch.

## 26. Trimming a header list without updating the values that fill it left the row-writer completely out of sync with its own headers

**What happens.** A follow-on to #25's lesson about `NEW_COLS`/`vals` needing to stay in sync — this time in the opposite direction. When the roster sheet's column set was substantially trimmed down (per a user request to cut unused columns down to a specific short list: academic start year, recent paper list, topics, citation/publication counts including a new "recent citations" metric, a simplified 3-state research-direction-deviation label, representative papers flattened into 15 columns, and a 1-4 confidence rating), `NEW_COLS` — the header list — was updated to the new, much shorter structure. The `vals` list inside `_write_roster_sheet()` that actually populates each row, however, was left completely untouched: still 21+ entries built from the *old* column set (match method, institution timeliness, ORCID, current institution, last-publication year, the old confidence score/level/action/reasoning quartet, the old tier label and long-form domain-mix note, a raw representative-paper count and a single concatenated preview string) — none of which corresponded to what the new, trimmed headers actually promised.

**How it presents.** Unlike #25 (a one-column shift that at least kept every value landing under *some* semantically-adjacent header), this would have been an outright structural mismatch — the new headers ask for things (a recent-citations sum, a 1-4 rating, fifteen separate representative-paper fields) that never existed anywhere in the old `vals` list at all, while the old list's many now-irrelevant fields (ORCID, institution timeliness, the old four-column confidence breakdown) would have landed under whatever new header happened to occupy that position. This is a more severe version of the same underlying failure mode as #25: two lists that must be positionally parallel, maintained by hand in two different places, with nothing structural forcing them to change together.

**Fix.** Rewrote `_write_roster_sheet()`'s `vals` construction from scratch to match the trimmed `NEW_COLS` exactly, and added the new computed fields it now requires: `_recent_citations()` (sums OpenAlex's per-year `counts_by_year` citation counts for years at or after `--window-a-since` — a new CLI argument this script didn't previously need — distinct from the historical-total `cited_by_count` already shown elsewhere), `_confidence_1_to_4()` (a direct relabeling of the existing 高/中/低/不可用 four-tier confidence level, 1=best per the user's request), `_domain_deviation_label()` (collapses `resolve_domain_signal()`'s richer internal state down to exactly the three labels requested: 未偏离/研究领域较细/交叉学科研究), and `_rep_paper_columns()` (flattens up to 3 representative papers, sorted newest-year-first, into 15 columns — title/coauthors/year/venue/JCR discipline rank — padding with blanks when fewer than 3 exist). Also implemented the previously-unfulfilled plan (left as a bare comment, never actually written) to append explanatory notes for all of these onto the end of the original workbook's "颜色图例" sheet, if present, so a reader encountering an unfamiliar column doesn't have to go find the source code to understand what it means.

*Observed:* ran a genuine end-to-end pipeline with two representative papers (one from 2023 with a coauthor, one from 2024 without) and non-trivial per-year citation data, then printed every one of the resulting 27 columns' header alongside its value — confirmed 近年被引数 correctly summed to the expected total, the representative papers appeared in the correct newest-first order (2024 paper in the "代表作1" slot, 2023 paper in "代表作2", the unused "代表作3" slot correctly blank), the coauthor field was correctly extracted only for the paper that had one, and the discipline-rank field was correctly formatted as "rank/total". Also tested against a workbook containing a real "颜色图例" sheet with pre-existing content, confirming the new notes append after the existing rows rather than overwriting them.
