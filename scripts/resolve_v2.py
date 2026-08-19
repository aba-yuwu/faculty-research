#!/usr/bin/env python3
"""Precise author resolution: institution ID filtering + field constraint + name variants.

String-matching an institution abbreviation ("NUS") against OpenAlex full names
("National University of Singapore") fails silently and makes every row ambiguous.
This module resolves the institution to an OpenAlex ID first, then filters on it.
"""
import json, os, re, time, requests

BASE = "https://api.openalex.org"

# OpenAlex made API keys mandatory for all requests starting Feb 13, 2026 (the old
# mailto-based "polite pool" is retired). Without a key you get ~100 free demo
# credits/day, then every request fails — and no amount of waiting fixes that,
# since it isn't a per-second rate limit, it's a missing credential. Set once by
# each script's main() after parsing --api-key, read automatically by _get() —
# a module-level credential rather than threading a new parameter through the
# dozens of functions that already pass `mailto` around, which would be a much
# larger, more error-prone change for the same effect. Get a free key at
# https://openalex.org/settings/api (an OpenAlex account, ~30 seconds).
API_KEY = None

# Alias table lives on disk so that mappings learned on one run persist to the next,
# and so that a roster using unfamiliar abbreviations teaches the skill rather than
# requiring every user to edit source. Layered lookup:
#   1. local alias file  2. OpenAlex acronym/alternative-name fields  3. plain search
def _find_alias_path():
    """Locate the alias file across layouts (skill dir, flat dir, cwd)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", "assets", "institution_aliases.json"),
              os.path.join(here, "assets", "institution_aliases.json"),
              os.path.join(os.getcwd(), "assets", "institution_aliases.json"),
              os.path.join(here, "institution_aliases.json")):
        if os.path.exists(p):
            return os.path.abspath(p)
    # none exist yet: prefer a writable location next to the script
    return os.path.abspath(os.path.join(here, "assets", "institution_aliases.json"))


_ALIAS_PATH = _find_alias_path()


def _load_aliases():
    try:
        d = json.load(open(_ALIAS_PATH, encoding="utf-8"))
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except Exception:
        return {}


def _save_alias(key, oa_id, display):
    """Persist a newly learned abbreviation so later runs (and other users) benefit.

    resolve_institution() only ever reaches this function when it did NOT already
    have a usable openalex_id cached for `key` (a cached id short-circuits before
    getting here) — so there is nothing to protect from being overwritten. Seed
    entries in the alias file start as {"learned": false, no openalex_id}
    specifically so this call can complete them.
    """
    try:
        d = json.load(open(_ALIAS_PATH, encoding="utf-8"))
    except Exception:
        d = {}
    d[key] = {"openalex_id": oa_id, "display_name": display, "learned": True}
    try:
        os.makedirs(os.path.dirname(_ALIAS_PATH), exist_ok=True)
        json.dump(d, open(_ALIAS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass


ALIASES = _load_aliases()
_inst_cache, _sess = {}, requests.Session()

# ---------------------------------------------------------------------------
# Institution identity
#
# Institution names are unique, so once an abbreviation has been expanded the
# comparison should be exact rather than similarity-based. Fuzzy overlap produces
# false positives on shared words: "Hong Kong University of Science and Technology"
# and "University of Science and Technology of China" share three of five tokens.
#
# Abbreviations are almost always the initials of the significant words, which gives
# an independent way to confirm that an expansion is the right one.
# ---------------------------------------------------------------------------
_INST_STOP = {"of", "the", "and", "at", "for", "in", "de", "la", "des", "du"}


def norm_inst(name):
    """Lowercase, drop punctuation and leading 'the', collapse whitespace."""
    n = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"^the ", "", n)


def initials(full_name):
    """First letters of the significant words: 'Hong Kong University of Science and
    Technology' -> 'hkust'."""
    words = [w for w in norm_inst(full_name).split() if w not in _INST_STOP]
    return "".join(w[0] for w in words if w)


def initials_match(abbrev, full_name):
    """Does an abbreviation look like the initials of this full name?"""
    a = re.sub(r"[^a-z]", "", str(abbrev or "").lower())
    if not a:
        return False
    ini = initials(full_name)
    if a == ini:
        return True
    # tolerate abbreviations that drop a trailing qualifier: HKU vs HKUST-style cases
    return len(a) >= 3 and ini.startswith(a)


def same_institution(roster_inst, record_inst):
    """Identity test after expansion.

    Exact match first, then containment (handles a leading 'The' and sub-units whose
    name embeds the parent). Finally the abbreviation itself, since OpenAlex sometimes
    stores departments as e.g. 'HKUST Business School'.
    """
    raw = str(roster_inst or "").strip()
    a = norm_inst((ALIASES.get(raw) or {}).get("display_name") or raw)
    b = norm_inst(record_inst)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    abbr = re.sub(r"[^a-z]", "", raw.lower())
    return len(abbr) >= 3 and abbr in b.replace(" ", "")




def _get(path, mailto=None, max_attempts=4, **params):
    """GET with a short retry/backoff for rate limits and transient errors.

    Callers mostly wrap _get() in try/except: continue (skip this search
    attempt rather than crash the whole batch) — which means a single
    unretried 429 or transient 5xx would silently drop a legitimate search
    attempt and could turn a resolvable person into a false "not_found" with
    no indication anything went wrong. Retrying here, once, centrally, is
    cheaper than reasoning about that at every call site.

    max_attempts is reduced by callers that already saw one full-retry
    failure earlier in the same find_author() call — see _find_author_inner's
    `degraded` flag. A single person's lookup can make up to ~8-10 of these
    calls; if OpenAlex is having a bad few minutes, retrying every single one
    of them for the full 4 attempts (1.5+3+6+12=22.5s of pure backoff sleep,
    per call) turns one degraded person into several minutes of wall-clock
    time for no added chance of success — the first failure already showed
    the problem isn't a one-off blip.
    """
    if mailto:
        params["mailto"] = mailto
    if API_KEY:
        params["api_key"] = API_KEY
    last_exc = None
    for attempt in range(max_attempts):
        try:
            r = _sess.get(f"{BASE}/{path}", params=params, timeout=45)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < max_attempts - 1:
                    time.sleep(1.5 * (2 ** attempt))
                continue
            r.raise_for_status()
            time.sleep(0.12)
            return r.json()
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(1.5 * (2 ** attempt))
    raise last_exc or RuntimeError(f"OpenAlex request failed after retries: {path}")


def resolve_institution(name, mailto=None):
    """Roster institution string -> (OpenAlex institution id, canonical name).

    Handles abbreviations generically: OpenAlex institution records carry
    `display_name_acronyms` and `display_name_alternatives`, so an unknown
    abbreviation can usually be resolved without a hand-maintained table.
    Successful resolutions are written back to the alias file.
    """
    if not name:
        return None, None
    key = str(name).strip()
    if key in _inst_cache:
        return _inst_cache[key]

    # layer 1: local alias file
    hit = ALIASES.get(key)
    query = key
    if hit:
        if hit.get("openalex_id"):
            out = (hit["openalex_id"], hit.get("display_name"))
            _inst_cache[key] = out
            return out
        query = hit.get("display_name") or key

    def _search(q):
        try:
            return (_get("institutions", mailto, **{"search": q, "per-page": 10}).get("results") or [])
        except Exception:
            return []

    res = _search(query)
    chosen = None
    if res:
        kl = key.lower()
        # layer 2a: the institution's own registered acronym
        for r in res:
            names = [str(x).lower() for x in (r.get("display_name_acronyms") or [])]
            names += [str(x).lower() for x in (r.get("display_name_alternatives") or [])]
            if kl in names:
                chosen = r
                break
        # layer 2b: the abbreviation matches the initials of the full name
        if chosen is None:
            for r in res:
                if initials_match(key, r.get("display_name")):
                    chosen = r
                    break
        # layer 2c: exact name equality
        if chosen is None:
            for r in res:
                if norm_inst(r.get("display_name")) == norm_inst(query):
                    chosen = r
                    break
        chosen = chosen or res[0]

    if not chosen:
        _inst_cache[key] = (None, None)
        return None, None
    oa_id = _short_id(chosen)
    if not oa_id:
        _inst_cache[key] = (None, None)
        return None, None
    out = (oa_id, chosen.get("display_name"))
    _inst_cache[key] = out
    _save_alias(key, oa_id, chosen.get("display_name"))
    return out


# Western given names commonly adopted by scholars of Chinese/Korean heritage.
# Rosters often record "Ka Yan Boris Lee" while publications use "Ka Yan Lee",
# so the adopted name must be dropped to find the real publication record.
_ADOPTED = set("""alex alan amy andy angela annie anthony ben betty bill bob boris brian
bruce carol cathy charlie cherry chris cindy claire coco daisy dan daniel david eddie
eden elaine ellen emily eric eva fiona frank gary george grace helen henry ivy jack
jacky james jane janet jason jeff jenny jerry jessica jimmy joe john johnny joyce judy
julia julie karen kate kathy keith kelly ken kenny kevin kitty lambert larry laura
leo lily linda lionel lisa louis lucy luke mandy marco mark martin mary matt max may
michael michelle mike nancy nick nicole olivia oscar patrick paul peter philip rachel
ray raymond rebecca richard rick robert roger ronald rose roy ruby sam samuel sandy
sarah sean shirley simon simba sophia stanley stella steve steven sunny susan terry
thomas tiffany tim tina toby tom tony tracy vicky victor vincent vivian wendy william
willy winnie yvonne""".split())


def name_variants(raw):
    """Produce ordered name variants, most likely first.

    Handles three roster conventions at once:
      * titles and CJK characters mixed in           -> stripped
      * surname written in ALL CAPS                  -> used to fix word order
      * an adopted Western given name inserted       -> dropped, since publications
        typically carry only the romanised given name
    """
    n = re.sub(r"\b(Prof|Professor|Dr|Assoc|Asst|Associate|Assistant|Mr|Ms|Mrs)\.?\b", " ",
               raw, flags=re.I)
    n = re.sub(r"[（(].*?[)）]", " ", n)
    n = "".join(ch for ch in n if not ("\u4e00" <= ch <= "\u9fff"))
    n = re.sub(r"[^A-Za-z\-'\s]", " ", n)
    toks = [t for t in n.split() if len(t) > 1]
    if not toks:
        return []

    # a single ALL-CAPS token (2+ letters) is almost always the surname
    caps = [t for t in toks if t.isupper() and len(t) > 1]
    surname = caps[0] if len(caps) == 1 else None
    given = [t for t in toks if t is not surname] if surname else []

    out = []

    def add(*parts):
        v = " ".join(p for p in parts if p).strip()
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)

    if surname:
        core = [g for g in given if g.lower() not in _ADOPTED]
        add(*core, surname)                       # Ka Yan Lee      <- usually correct
        add(surname, *core)                       # Lee Ka Yan
        if core != given:
            add(*given, surname)                  # Ka Yan Boris Lee
    else:
        add(*toks)
        if len(toks) >= 2:
            add(*toks[::-1])
            add(toks[-1], toks[0])
            core = [t for t in toks if t.lower() not in _ADOPTED]
            if core != toks and core:
                add(*core)
                add(*core[::-1])
    return out


FIELD_HINTS = {
    "finance": ["finance", "financial economics", "asset pricing", "corporate finance",
                "capital market", "investment", "banking"],
    "accounting": ["accounting", "auditing", "disclosure", "financial reporting"],
    "economics": ["economics", "econometrics", "macroeconomics"],
    "is": ["information systems", "information technology", "e-commerce", "platform"],
    "om": ["operations management", "supply chain", "logistics"],
}


def _tokens(n):
    n = re.sub(r"[^A-Za-z\-\s]", " ", str(n or "")).replace("-", " ")
    return [t.lower() for t in n.split() if len(t) > 1]


def name_compatible(query, candidate):
    """Reject fuzzy matches that share only a surname.

    OpenAlex `display_name.search` is token-based and fuzzy: querying
    "Ka Yan Lee" also returns "Ka Wing Lee", "Ka Po Lee", "Ka Lok Lee" and so on.
    Those are different people. Require that no given name conflicts: every given
    token of the shorter name must appear in the longer one (an initial counts as
    a match for a full token beginning with it).
    """
    q, c = _tokens(query), _tokens(candidate)
    if not q or not c:
        return False
    if q[-1] != c[-1]:                      # surnames must agree
        return False
    qg, cg = set(q[:-1]), set(c[:-1])
    if not qg or not cg:
        return bool(qg or cg) is False or qg == cg
    short, long_ = (qg, cg) if len(qg) <= len(cg) else (cg, qg)
    for t in short:
        if t in long_:
            continue
        if len(t) == 1 and any(x.startswith(t) for x in long_):
            continue
        if any(len(x) == 1 and t.startswith(x) for x in long_):
            continue
        return False                        # a given name conflicts -> different person
    return True


def _affil_ids(author):
    """Every institution id appearing anywhere in an author record."""
    ids = set()
    for x in (author.get("affiliations") or []):
        v = _short_id((x or {}).get("institution"))
        if v:
            ids.add(v)
    for x in (author.get("last_known_institutions") or []):
        v = _short_id(x)
        if v:
            ids.add(v)
    return ids


def verify_institution(author, inst_id):
    """Confirm the API filter actually held.

    OpenAlex silently ignores filter keys it does not recognise, returning an
    unfiltered result set that looks legitimate. Every candidate must therefore be
    re-checked against the record itself before it is trusted.

    This only asks "does inst_id appear ANYWHERE in this author's history" — a
    coarse pre-filter to drop junk the API filter let through, not a claim about
    current employment. See institution_match_level() for the recency-aware check
    used to decide trust level.
    """
    return bool(inst_id) and inst_id in _affil_ids(author)


def _affil_year_map(author):
    """institution id -> most recent year this author is recorded there."""
    out = {}
    for x in (author.get("affiliations") or []):
        sid = _short_id((x or {}).get("institution"))
        if not sid:
            continue
        years = [y for y in (x.get("years") or []) if isinstance(y, int)]
        if years:
            out[sid] = max(out.get(sid, 0), max(years))
    return out


def institution_match_level(author, inst_id):
    """Is inst_id this author's CURRENT institution, or just something in their past?

    Roster institutions here are read off official faculty pages — i.e. they are a
    *current* affiliation. An OpenAlex author record instead lists every institution
    ever seen across the author's whole career, so "inst_id appears somewhere" says
    nothing about today: someone who moved on eight years ago still carries the old
    institution forever, and OpenAlex's own author-disambiguation is unreliable
    enough on common names that unrelated people's institutions end up on one ID.
    Recency is the right test, not mere presence.

    Returns "current" | "historical" | "none".
    """
    if not inst_id:
        return "none"
    last_known_ids = {_short_id(i) for i in (author.get("last_known_institutions") or [])}
    last_known_ids.discard(None)
    if inst_id in last_known_ids:
        return "current"
    year_map = _affil_year_map(author)
    if inst_id not in year_map:
        return "none"
    latest_year = max(year_map.values())
    # Tolerance of 1 year is ONLY safe for a simple, two-institution "just moved"
    # profile — the scenario the tolerance was actually written for: author moves
    # from A to B, and a paper still shows A's affiliation string for a year that,
    # in OpenAlex's data, slightly post-dates the real move. That reasoning breaks
    # down for a SCATTERED profile with several unrelated institutions: inst_id's
    # own year can land "within 1 year" of some OTHER, unrelated institution's
    # latest year purely by coincidence, with no real transition connecting them —
    # and a scattered multi-institution profile is itself a red flag for exactly
    # the kind of merged/contaminated OpenAlex ID this whole check exists to catch
    # (see pitfalls.md), so it should get LESS benefit of the doubt, not the same.
    #
    # Real case that exposed this: an author with affiliations at 5 unrelated
    # institutions across 2012-2024 (USTC, this roster's target institution for
    # one single year, three other unrelated Chinese institutions) had the target
    # institution's one lone year treated as "current" purely because a totally
    # different institution's most recent year happened to be 1 year later —
    # institution_match_level said "current" for a profile whose own topics showed
    # no connection to the roster's expected field at all, and the record was
    # auto-accepted with no manual-review flag as a result.
    if len(year_map) > 2:
        return "current" if year_map[inst_id] == latest_year else "historical"
    return "current" if year_map[inst_id] >= latest_year - 1 else "historical"


def _short_id(a):
    """OpenAlex ids are URLs; some records carry a null id. Never assume."""
    v = (a or {}).get("id")
    return v.rsplit("/", 1)[-1] if isinstance(v, str) and v else None


def _full(author, mailto):
    """List endpoints sometimes omit topic fields; fetch the full record when needed."""
    if author.get("topics") or author.get("x_concepts") or author.get("concepts"):
        return author
    sid = _short_id(author)
    if not sid:
        return author
    try:
        return _get(f"authors/{sid}", mailto)
    except Exception:
        return author


def field_score(author, field, mailto=None):
    """Overlap between an author's OpenAlex topics and an expected field."""
    if not field:
        return 0
    a = _full(author, mailto)
    hints = FIELD_HINTS.get(field.lower(), [field.lower()])
    blob = " ".join(t.get("display_name", "") for t in (a.get("topics") or [])).lower()
    blob += " " + " ".join(x.get("display_name", "") for x in (a.get("x_concepts") or [])).lower()
    blob += " " + " ".join(str(c.get("display_name", "")) for c in (a.get("concepts") or [])).lower()
    return sum(1 for h in hints if h in blob)


def _current_institution_names(a, cap_fallback=True):
    """The institution(s) this author is CURRENTLY known for — same source the
    candidate listing shows the user (see _fmt's "last_known" field): OpenAlex's
    own last_known_institutions, falling back to the affiliations list if
    that's empty (which it frequently is).

    cap_fallback=True (the display convention) caps the fallback at the first 3
    entries for readability. Counting how many institutions a candidate has
    must NOT use that cap: if it did, a genuinely messy profile could never
    register more than 3 institutions via the fallback path, and the "noisy"
    side of _clean_single_institution_pick's threshold (>3) would be
    unreachable whenever last_known_institutions happens to be empty — which
    is common. Pass cap_fallback=False when the result feeds a count.
    """
    last = a.get("last_known_institutions") or []
    if last:
        return [x.get("display_name") for x in last if x.get("display_name")]
    affils = (a.get("affiliations") or [])[:3] if cap_fallback else (a.get("affiliations") or [])
    return [(x.get("institution") or {}).get("display_name") for x in affils
            if (x.get("institution") or {}).get("display_name")]


def _clean_single_institution_pick(work_pool, field, mailto):
    """See the call site in _find_author_inner for the reasoning. Returns the
    single clean candidate to pick, or None if the pool doesn't match this
    pattern (more than one clean candidate, no noisy ones to contrast against,
    or the clean candidate's own topics look scattered rather than
    concentrated).

    "Concentrated in the research field" is checked via topic-domain diversity
    (reusing _contamination_risk) rather than a literal keyword hit against
    FIELD_HINTS: a clean candidate's actual topic wording frequently doesn't
    contain any FIELD_HINTS phrase verbatim (field_score()==0 for everyone in
    the pool is common), so a keyword-hit requirement would defeat the
    heuristic on exactly the cases it exists for. A coherent, non-scattered
    topic set is the more reliable signal that these publications belong to
    one real, focused researcher.

    n_inst() counts CURRENT/recent institutions (_current_institution_names,
    uncapped), not the author's full career-long affiliation history
    (_affil_ids): almost everyone has 2+ institutions across a PhD + postdoc +
    current job, so counting the whole history would fail this heuristic for
    nearly any real, uncontaminated professor. What actually distinguishes a
    clean profile from a contaminated one is how many institutions they are
    CURRENTLY listed at.
    """
    def n_inst(a):
        return len(set(_current_institution_names(a, cap_fallback=False)))
    clean = [a for a in work_pool if n_inst(a) <= 1]
    noisy = [a for a in work_pool if n_inst(a) > 3]
    if len(clean) != 1 or not noisy or len(clean) + len(noisy) != len(work_pool):
        return None
    cand = clean[0]
    risk, _ = _contamination_risk(cand, mailto)
    return None if risk else cand


def _find_author_inner(name, institution, mailto=None, field=None, min_works=0):
    """Return (candidates, how). Institution is verified per record, not assumed."""
    inst_id, inst_name = resolve_institution(institution, mailto)
    variants = name_variants(name)
    seen_ids, pooled, rejected = set(), [], 0
    attempted, failed = 0, 0   # track API-call failures separately from genuine
                                # zero-result searches — see the final return path
                                # below for why this distinction matters.
    last_error = None
    degraded = False   # set True after the first full-retry-exhaustion failure
                        # in this call; every subsequent _get() call for THIS
                        # person then uses max_attempts=1 (no backoff sleep at
                        # all) instead of repeating the full 4-attempt/~10s
                        # backoff on every one of the up to ~10 calls one
                        # find_author() invocation can make — a person whose
                        # search hits a genuinely bad network patch used to
                        # cost minutes; now it costs one ~10s failure plus a
                        # handful of near-instant ones.

    if inst_id:
        for variant in variants:
            def _try_filter(filt):
                nonlocal attempted, failed, degraded, last_error, rejected
                attempted += 1
                try:
                    d = _get("authors", mailto, max_attempts=(1 if degraded else 4),
                             **{"filter": filt, "per-page": 25})
                except Exception as e:
                    failed += 1
                    degraded = True
                    last_error = f"{type(e).__name__}: {e}"
                    return False
                results = d.get("results", [])
                for a in results:
                    sid = _short_id(a)
                    if not sid or sid in seen_ids:
                        continue
                    if not verify_institution(a, inst_id):
                        rejected += 1          # filter was ignored by the API
                        continue
                    if not name_compatible(variant, a.get("display_name")):
                        rejected += 1          # fuzzy search matched a different person
                        continue
                    if (a.get("works_count") or 0) < min_works:
                        continue
                    seen_ids.add(sid); pooled.append(a)
                return bool(results)

            # 只优先查 affiliations.institution.id——返回的作者对象本身就带着
            # last_known_institutions 这个字段（不是filter决定返回哪些字段，
            # 只决定筛选哪些记录），institution_match_level() 完全可以从这一次
            # 查询的结果里直接算出"是不是当前机构"，不需要为了拿到这同一份数据
            # 再单独发一次 last_known_institutions.id 过滤查询。只有这次查询
            # 一无所获时，才补一次 last_known_institutions.id 兜底——极少数情况下
            # OpenAlex的"最新机构"字段可能比论文层面统计出的affiliations历史更新，
            # 两者不完全同步，这个兜底避免那种边界情况下漏掉正确候选人。这样常见
            # 情况下机构搜索这一步的查询量能砍掉接近一半。
            got_any = _try_filter(f"display_name.search:{variant},affiliations.institution.id:{inst_id}")
            if not got_any:
                _try_filter(f"display_name.search:{variant},last_known_institutions.id:{inst_id}")

        if pooled:
            # Roster institutions come from official faculty pages, i.e. they are
            # CURRENT affiliations. Prefer candidates whose most recent recorded
            # affiliation is this institution over ones where it only appears
            # somewhere in career history — the latter is common noise for authors
            # who moved on, or whose OpenAlex ID has absorbed an unrelated person
            # who once passed through the same institution.
            current = [a for a in pooled if institution_match_level(a, inst_id) == "current"]
            work_pool = current or pooled
            hist_tag = "" if current else "_historical_institution_only"

            if len(work_pool) == 1:
                candidate = work_pool[0]
                # 机构+姓名收窄到了唯一候选人，不代表这就一定是对的人——姓名
                # 匹配本身有结构性局限：中文姓名"姓在前/名在前"顺序不统一，
                # 就算两种词序都试过，也没法排除"两个不同的人姓名恰好互换"
                # 这种巧合（参见 pitfalls.md #19 的真实案例）。如果填了FIELD，
                # 这是一个和姓名/机构完全独立的信号，值得在"唯一候选人"这一步
                # 就核对一下，而不是等到有多个候选人时才用它筛选。完全不沾边
                # 就直接停下来交给人工核实，不再继续尝试其余的候选人筛选/
                # 兜底搜索逻辑——唯一候选人本身就可能是匹配环节出错的结果，
                # 越往下走越可能在错误的基础上做更多加工。
                if field and field_score(candidate, field, mailto) == 0:
                    topics_seen = ", ".join(t.get("display_name", "")
                                            for t in (candidate.get("topics") or [])[:5])
                    method = (f"field_mismatch_needs_review (expected field={field}, "
                             f"candidate topics: {topics_seen or '无可用主题数据'})")
                    return _fmt(work_pool, inst_name, inst_id, mailto=mailto), method
                method = "matched_on_current_institution_verified" if current \
                    else "matched_on_historical_institution_only"
                return _fmt(work_pool, inst_name, inst_id, mailto=mailto), method

            if field:
                scored = [(field_score(x, field, mailto), x) for x in work_pool]
                best = max(sc for sc, _ in scored)
                if best > 0:
                    work_pool = [x for sc, x in scored if sc == best]
            if len(work_pool) == 1:
                method = "matched_on_current_institution_and_field" if current \
                    else "matched_on_historical_institution_only"
                return _fmt(work_pool, inst_name, inst_id, mailto=mailto), method

            # Heuristic: a clean, single-institution profile vs. several
            # noisy, many-institution ones in the same pool. A real person whose
            # OpenAlex record is uncontaminated typically has a short, coherent
            # affiliation list; an ID that has absorbed unrelated same-name
            # people accumulates institutions that don't belong to them. If
            # exactly one candidate has 1 institution on record while every
            # other candidate in the pool has more than 3, AND that clean
            # candidate's own topics look coherent (not scattered across
            # unrelated fields), treat it as the match rather than leaving the
            # whole group ambiguous — the messy candidates are very unlikely to
            # be the person the roster is describing. Note this does NOT
            # require `field` to be set: _clean_single_institution_pick judges
            # "concentrated" via topic-domain coherence (_contamination_risk),
            # not a FIELD_HINTS keyword hit, so it works even when no expected
            # field was given.
            if len(work_pool) > 1:
                picked = _clean_single_institution_pick(work_pool, field, mailto)
                if picked is not None:
                    method = "matched_on_current_institution_clean_profile_heuristic" + hist_tag
                    return _fmt([picked], inst_name, inst_id, mailto=mailto), method

            # Second-pass narrowing: exclude candidates whose OWN topic profile
            # shows the hard-science-vs-quant-social contamination pattern
            # (_contamination_risk) — a candidate whose papers span e.g. both
            # Physics and Business, or Medicine and Finance, is very unlikely
            # to be the single roster professor being searched for, regardless
            # of whether _clean_single_institution_pick's stricter "1 vs 3+
            # institutions" pattern also happened to apply. If exactly one
            # candidate survives this exclusion, pick it — this directly
            # reduces how often a 2-candidate tie has to go to manual review
            # when one of the two is a plausible real match and the other is
            # an obviously-contaminated OpenAlex entity.
            if len(work_pool) > 1:
                risk_flags = [(x, _contamination_risk(x, mailto)[0]) for x in work_pool]
                non_risky = [x for x, risk in risk_flags if not risk]
                if 0 < len(non_risky) < len(work_pool) and len(non_risky) == 1:
                    method = "matched_on_current_institution_excluding_contaminated_candidates" + hist_tag
                    return _fmt(non_risky, inst_name, inst_id, mailto=mailto), method
                work_pool = non_risky or work_pool   # still narrow the pool for
                                                       # the merge-check below,
                                                       # even if not down to 1

            # Merge only when EVERY pair in the pool looks like one person split
            # across two OpenAlex entities: a split-entity timeline link (each
            # record's most-recent institution appears in the other's affiliation
            # history — the signature of OpenAlex creating a fresh entity when an
            # affiliation was updated rather than editing one in place) PLUS an
            # exact match on fixed identity fields (full name, and ORCID when
            # present). Topic overlap alone is checked too, but only as an extra
            # sanity net — it is not sufficient by itself, since it can also
            # coincidentally line up for two different people in the same field.
            names_ok = all(name_compatible(work_pool[0].get("display_name"),
                                           x.get("display_name")) for x in work_pool[1:])
            if (names_ok and _split_entity_pool(work_pool)
                    and _looks_like_same_person(work_pool, mailto)):
                work_pool = sorted(work_pool, key=lambda a: -(a.get("works_count") or 0))
                return [_merge(work_pool, inst_name, mailto=mailto)], "merged_duplicate_records" + hist_tag
            return _fmt(work_pool, inst_name, inst_id, mailto=mailto), "ambiguous_same_institution" + hist_tag

    for variant in variants:
        attempted += 1
        try:
            d = _get("authors", mailto, max_attempts=(1 if degraded else 4),
                     **{"filter": f"display_name.search:{variant}", "per-page": 25})
        except Exception as e:
            failed += 1
            degraded = True
            last_error = f"{type(e).__name__}: {e}"
            continue
        res = [a for a in d.get("results", [])
               if _short_id(a) and name_compatible(variant, a.get("display_name"))]
        if res:
            return _fmt(res, inst_name), "name_only_unverified"

    # A "not_found" that's actually "every single API call for this person
    # raised an exception" is indistinguishable from a genuine zero-result
    # search unless flagged separately — and the two need completely
    # different responses: "not_found" means go verify manually / this
    # person likely isn't well-indexed; "api_error" means re-run the batch
    # (the cache will skip everyone who succeeded) because this person's
    # result is not trustworthy, not because they don't exist.
    if attempted > 0 and failed == attempted:
        return [], f"api_error: {last_error}"
    return [], "not_found"


def find_author(name, institution, mailto=None, field=None, min_works=0):
    """Wraps _find_author_inner to add one more check that no single return path
    inside it can cover on its own: whether the resolved OpenAlex entity's own
    topics span clearly unrelated fields (see pitfalls.md #4/#13). Institution
    and recency checks only ever compare BETWEEN candidates; a single candidate
    that is itself a polluted OpenAlex entity (absorbing a different real
    person's work under one ID) sails straight through every earlier check
    because there is no second candidate to compare it against.
    """
    cands, how = _find_author_inner(name, institution, mailto, field, min_works)
    if cands and not how.startswith("name_only") and how != "not_found":
        if any(c.get("contamination_risk") for c in cands):
            how = how + "_profile_contamination_risk"
    return cands, how


def _topic_set(author, mailto):
    a = _full(author, mailto)
    out = set()
    for key in ("topics", "x_concepts", "concepts"):
        for t in (a.get(key) or []):
            n = (t or {}).get("display_name")
            if n:
                out.add(n.lower())
    return out


def _most_recent_inst_ids(author):
    """Institution ids at this author's own most recent recorded affiliation year,
    plus anything OpenAlex itself already calls 'last known'."""
    ids = {_short_id(i) for i in (author.get("last_known_institutions") or [])}
    ids.discard(None)
    year_map = _affil_year_map(author)
    if year_map:
        latest = max(year_map.values())
        ids |= {i for i, y in year_map.items() if y >= latest - 1}
    return ids


def _cross_recency_link(a, b):
    """Is this the fingerprint of one person split into two OpenAlex entities?

    The common cause of a real duplicate is: a professor's institution gets
    updated, and OpenAlex creates a NEW author entity for the new affiliation
    rather than editing the old one in place. The two entities then chain
    end-to-end: entity A's most-recent institution is exactly where entity B's
    affiliation history stops (or vice versa). Plain topic overlap cannot tell
    this apart from two different people who simply work in the same field —
    this checks the institution timeline itself lines up instead.
    """
    a_recent, b_recent = _most_recent_inst_ids(a), _most_recent_inst_ids(b)
    a_hist, b_hist = _affil_ids(a), _affil_ids(b)
    return bool(a_recent & b_hist) or bool(b_recent & a_hist)


def _norm_name_exact(name):
    """Token-set identity, stricter than name_compatible(): every token must
    agree, not just surname-plus-initials compatibility. Used as a gate right
    before merging, where a false positive silently doubles someone's output."""
    return tuple(sorted(_tokens(name)))


def _identity_fields_match(a, b):
    """Fixed-field check required on top of a timeline link before two OpenAlex
    entities are trusted as the same person: full name token set must match
    exactly, and if both records carry an ORCID, the ORCIDs must agree. Coarse
    signals like institution recency or topic overlap can coincidentally line up
    for two different people who share a surname; this is the closest identity
    check available from bare author-search records.
    """
    if _norm_name_exact(a.get("display_name")) != _norm_name_exact(b.get("display_name")):
        return False
    oa, ob = a.get("orcid"), b.get("orcid")
    if oa and ob and oa != ob:
        return False
    return True


def _split_entity_pool(records):
    """True only if EVERY pair in the pool looks like the same person recorded
    as two entities: a cross-recency timeline link AND matching fixed identity
    fields for that pair. One mismatching pair fails the whole pool — this
    never merges "most of" a group, since a partial merge is exactly as unsafe
    as a wrong one.
    """
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if not (_cross_recency_link(records[i], records[j])
                    and _identity_fields_match(records[i], records[j])):
                return False
    return True


def _looks_like_same_person(records, mailto, min_overlap=0.15):
    """Duplicate entities share research topics; different people usually do not."""
    sets = [_topic_set(r, mailto) for r in records]
    base = sets[0]
    if not base:
        return False
    for other in sets[1:]:
        if not other:
            return False
        inter = len(base & other)
        union = len(base | other) or 1
        if inter / union < min_overlap:
            return False
    return True


# Domains that legitimately co-occur with a non-medical field for one real
# person are common (e.g. CS + Math, Economics + Business); a MEDICAL domain
# sharing an ID with a clearly non-medical one is a much stronger contamination
# signal than domain count alone, since it rarely reflects one person's actual
# combined research interests.
_MEDICAL_DOMAINS = {"Medicine", "Health Professions", "Nursing", "Dentistry",
                    "Veterinary", "Biochemistry, Genetics and Molecular Biology"}

# Broader version of the same idea, generalized beyond medicine specifically:
# "hard", lab/bench/clinical sciences on one side, "quant social" fields
# (business/finance/econ/social science) on the other. A field name landing
# on BOTH sides for one author is a much stronger signal than raw domain
# count — see _contamination_risk. Verified against OpenAlex's own 26-field
# taxonomy (Domain -> Field -> Subfield -> Topic; docs.openalex.org), plus
# the older level-0 concept-tree names the API still returns.
#
# Deliberately NOT included on either side — and this matters as much as
# what IS included: Computer Science, Mathematics, Engineering, Environmental
# Science, Psychology. These legitimately bridge both sides in real,
# unremarkable careers (fintech, quantitative finance, computational social
# science, health economics, operations research, engineering management) —
# pairing one of these with either side alone must NOT read as contamination,
# or every quant-finance or health-economics professor gets a false flag.
_HARD_SCIENCE_FIELDS = {
    # new (2024+) field-level names
    "Medicine", "Health Professions", "Nursing", "Dentistry", "Veterinary",
    "Biochemistry, Genetics and Molecular Biology", "Immunology and Microbiology",
    "Neuroscience", "Pharmacology, Toxicology and Pharmaceutics",
    "Agricultural and Biological Sciences", "Physics and Astronomy", "Chemistry",
    "Chemical Engineering", "Materials Science", "Earth and Planetary Sciences",
    "Energy",
    # legacy level-0 concept-tree names (x_concepts)
    "Biology", "Physics", "Geology", "Geography",
}
_SOCIAL_QUANT_FIELDS = {
    # new (2024+) field-level names
    "Business, Management and Accounting", "Economics, Econometrics and Finance",
    "Decision Sciences",
    # legacy level-0 concept-tree names (x_concepts)
    "Business", "Economics", "Political science", "Sociology",
}


def _topic_domains_and_fields(a, mailto, min_concept_score=0.35):
    """One _full() fetch, returning (domains, fields) — the coarse 4-value
    domain level and the more granular 26-value field level of OpenAlex's
    topic hierarchy, plus the legacy level-0 concept-tree names for both.
    Splitting these into two return values (rather than one merged set)
    matters: mixing domain-level and field-level names into one set inflates
    a naive len(...)>=3 count purely because each topic contributes both a
    domain name AND a field name, not because the author actually spans more
    distinct areas. Computing both from a single _full() call (rather than
    two separate helper functions each calling _full() independently) avoids
    fetching the same author's full record twice.
    """
    full = _full(a, mailto)
    domains, fields = set(), set()
    for t in (full.get("topics") or []):
        d = (t.get("domain") or {}).get("display_name")
        if d:
            domains.add(d)
        f = (t.get("field") or {}).get("display_name")
        if f:
            fields.add(f)
    for c in (full.get("x_concepts") or []):
        if (c.get("level") == 0) and (c.get("score") or 0) >= min_concept_score:
            d = c.get("display_name")
            if d:
                domains.add(d)
                fields.add(d)
    return domains, fields


def _topic_domains(a, mailto, min_concept_score=0.35):
    """Level-0 ('domain') classification of this author's own aggregate topics.
    See _topic_domains_and_fields() — kept as a thin wrapper since several
    callers only need the domain set."""
    return _topic_domains_and_fields(a, mailto, min_concept_score)[0]


def _contamination_risk(a, mailto):
    """(risk: bool, domains seen) for a single already-resolved OpenAlex entity."""
    domains, fields = _topic_domains_and_fields(a, mailto)
    if not domains and not fields:
        return False, domains
    if (domains & _MEDICAL_DOMAINS) and (domains - _MEDICAL_DOMAINS):
        return True, domains
    if (fields & _HARD_SCIENCE_FIELDS) and (fields & _SOCIAL_QUANT_FIELDS):
        return True, domains | fields
    return len(domains) >= 3, domains


def _merge(records, inst_name, mailto=None):
    """Combine duplicate author entities into one, keeping every id for traceability."""
    primary = records[0]
    out = _fmt([primary], inst_name, mailto=mailto)[0]
    out["works"] = sum(r.get("works_count") or 0 for r in records)
    out["cited_by"] = sum(r.get("cited_by_count") or 0 for r in records)
    out["merged_ids"] = [_short_id(r) for r in records]
    out["merged_names"] = [r.get("display_name") for r in records]
    out["merge_note"] = (f"{len(records)} OpenAlex records were merged as one person: for every "
                         f"pair, one record's most-recent institution appears in the other's "
                         f"affiliation history (consistent with OpenAlex creating a new entity "
                         f"when the affiliation was updated, rather than editing one in place), "
                         f"and full name (+ ORCID, where present) matched exactly. Counts summed. "
                         f"Still worth a spot check if the names differ substantially.")
    return out


def _fmt(res, inst_name, inst_id=None, mailto=None):
    out = []
    for a in res:
        if not _short_id(a):
            continue
        risk, domains = _contamination_risk(a, mailto) if mailto else (None, set())
        out.append({
            "id": _short_id(a),
            "name": a.get("display_name"),
            "works": a.get("works_count"),
            "cited_by": a.get("cited_by_count"),
            "match_level": institution_match_level(a, inst_id) if inst_id else None,
            "last_known": ([i.get("display_name") for i in (a.get("last_known_institutions") or [])]
                           or [(x.get("institution") or {}).get("display_name")
                               for x in (a.get("affiliations") or [])[:3]]),
            "topics": [t.get("display_name") for t in (a.get("topics") or [])[:5]],
            "contamination_risk": risk,
            "contamination_domains": sorted(domains) if domains else [],
            "resolved_institution": inst_name,
        })
    return out
