# Data sources

Priority order, with what each can and cannot answer.

## Contents
1. ORCID — degree years
2. OpenAlex — output and affiliation history
3. Crossref — publication status
4. Semantic Scholar — fallback disambiguation
5. Dissertation & repository sources
6. Field-specific sources
7. Institutional pages
8. Personal sites and CVs
9. Blocked sources — do not circumvent
10. Ethics and rate limits

---

## 1. ORCID Public API — best source for degree years

`https://pub.orcid.org/v3.0/{ORCID_ID}/educations` with header `Accept: application/json`

No key required. Returns `organization`, `role-title`, `start-date`, `end-date`.

**This is the single best source for PhD and bachelor years**, which institutional pages almost never publish. Coverage is uneven — strong for scientists and younger scholars, weaker for senior business-school faculty — but authoritative when present because the researcher entered it themselves.

Find an iD: `https://pub.orcid.org/v3.0/expanded-search/?q=family-name:X+AND+given-names:Y`

## 2. OpenAlex API — best source for output and affiliation history

```
https://api.openalex.org/authors?filter=display_name.search:NAME
https://api.openalex.org/works?filter=author.id:AUTHOR_ID&per-page=200
```

No key required. Append `?mailto=you@example.com` for the polite pool.

Uniquely useful fields:
- `affiliations[]` — institutions **with year ranges** → yields academic start year, which age and tenure reasoning both need
- `counts_by_year` — output and citations per year → reveals slowdowns a static publication list hides
- `last_known_institutions` — catches moves that official pages lag on
- `authorships[]` on works carry author IDs → enables **ID-based co-authorship matching** instead of fragile name matching

## 3. Crossref API

`https://api.crossref.org/works/{DOI}` or `?query.bibliographic=TITLE`

Confirms whether an item is genuinely published versus still a working paper — a distinction that materially changes an assessment and that personal pages often blur.

## 4. Semantic Scholar API

`https://api.semanticscholar.org/graph/v1/author/search?query=NAME`

Free tier without key. Good fallback when OpenAlex disambiguation is poor. Provides `hIndex`, `paperCount`, `citationCount`.

## 5. Dissertation & repository sources

- **NDLTD** (`search.ndltd.org`) — global theses union catalogue
- Institutional repositories (MIT DSpace, LSE Theses Online, university libraries)
- ProQuest Dissertations via library access

A dissertation record often yields **year + institution + advisor** at once — three fields from one lookup.

## 6. Field-specific sources

- **RePEc / IDEAS** — economics and finance author profiles, working papers
- **NBER / CEPR** working paper series — affiliation and dating
- **SSRN** author pages — common in finance and accounting; includes working papers absent elsewhere
- **arXiv API** (`export.arxiv.org/api/query`) — where AI/ML-adjacent work often appears first

## 7. Institutional pages

Reliable for: current title, administrative roles, teaching, contact.
Unreliable for: degree years (usually absent), affiliation after a move (lag of a year or more is common), publication lists (often years stale).

**Always cross-check against OpenAlex `last_known_institutions`.**

## 8. Personal sites and CVs

Richest single source when it exists. A CV PDF typically yields degree years, full employment timeline, publication status, awards, editorial roles, and **student supervision records with placement outcomes**. That last item is often the most decision-relevant fact available anywhere and appears in no database.

## 9. Blocked sources — do not circumvent

These commonly block automated access:

| Source | Behaviour |
|---|---|
| Google Scholar | Blocks automated access outright |
| Dropbox-hosted CVs | Blocks automated fetch |
| Some university discovery portals | robots-disallowed |
| Some faculty directories | robots-disallowed, inconsistently across subpages of one domain |

**Record the gap; ask the user to paste the content.** Do not rotate user agents, route around rate limits, or otherwise work around a block. It is both wrong and, for any project intended as a portfolio piece, a liability rather than an asset. The API-first path yields better structured data anyway.

When blocked, tell the user exactly what to open and what to copy — "open the CV link on their homepage and paste the Education section". This turns a dead end into a 30-second task.

## 10. Ethics and rate limits

- Identify yourself via `mailto` or a contactable User-Agent where the API asks.
- Respect published limits with backoff. OpenAlex polite pool allows ~10 req/s.
- Cache locally. Re-running a roster must not re-hit every endpoint.
- Collect only professionally relevant, publicly published information.
