# Examples

## `demo_roster_100.xlsx`

A **fully synthetic** 100-row roster for trying the pipeline end to end without any real
research subjects' data. Names are randomly generated (never real professors); institutions
are drawn from the abbreviation seed list already in `assets/institution_aliases.json`
(HKU, NUS, NTU, HKUST, CUHK, PolyU, UCB, LSE, ...), so running this sample also demonstrates
the abbreviation → canonical-name resolution feature.

Sheet name: `roster_demo`. Columns: `序号` (id), `院系` (department), `机构` (institution),
`姓名` (name) — matching what `batch_enrich.py --sheet roster_demo` expects by default.

A handful of names deliberately repeat with a different institution attached, to demonstrate
that the pipeline matches on **name + institution together**, not name alone (see
`references/pitfalls.md`).

Because the names are synthetic, most rows will resolve as `not_found` or `ambiguous`
against the real OpenAlex database — that's expected and fine for a structural demo. To see
`ok` / `possible_move` / `needs_review_contaminated` results, run the pipeline against a real
roster of your own.

## Adding your own example run

If you want to showcase a real run's *output* here, use a roster of consenting collaborators
or clearly fictional entries — not third parties' data pulled without their knowledge for
this purpose. Redact or omit `mailto` from any screenshot before committing it.
