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

*Observed:* two separate roster members had profiles merged with medical researchers of the same name. A third, single-candidate case ("Luo Jiang") showed a cybersecurity paper, a medical-imaging radiomics paper, and a CAD/mesh paper all under one OpenAlex ID with institutions listing USTC, NTU, and a medical college simultaneously — a clean single-candidate match by every earlier check, since there was no second candidate for those checks to compare it against.

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
