# Journal ranking design (journal_ranking.py)

Grades a professor's recent journal output against a user-supplied JCR list
and picks up to 3 representative papers. Independent of `resolve_v2.py` —
identity resolution and journal grading are separate concerns; this module
only consumes the `works` list `batch_enrich.py` already fetched.

## Contents
1. Two time windows
2. Tier decision tree
3. ESCI percentile penalty
4. UTD24 override
5. Journal name matching
6. Relevance scoring
7. 代表作排序依据（priority_tier）
8. 研究方向信号：不成立 / 少见 / 桥梁三档独立规则
9. Data-handling rule for the JCR file itself

---

## 1. Two time windows

- **Window A** (`--window-a-since`, default 2020): used only to *judge*
  output quality — how good has this person's journal record been recently.
- **Window B** (`--window-b-since`, default 2023): the actual candidate pool
  representative papers are picked from. Narrower and more recent, because a
  "representative paper" for a PhD application should be current work.

`batch_enrich.py` fetches from Window A onward (the earlier cutoff), which is
a superset of Window B — `journal_ranking.py` re-slices the same list rather
than triggering a second OpenAlex call.

## 2. Tier decision tree

Mutually exclusive, evaluated in order, first hit wins:

| # | Condition (over Window A journal papers) | Tier | Pick rule (over Window B) |
|---|---|---|---|
| ① | ≥1 paper at/above `--top-percentile` %ile of its category, OR hits UTD24 | `top` | SSRN working papers first, else journal papers by impact factor desc |
| ② | Q2+ paper ratio > `--q2-ratio` | `good` | Q2+ journal papers + SSRN, sorted by relevance to stated interests |
| ③ | non-SCI ratio > `--non-sci-ratio` AND relevance to stated interests is zero | `not_recommended` | none — no papers picked |
| ④ | everything else | `default` | journal papers by impact factor desc, padded with SSRN if <3 |

If no interests were supplied, relevance can't be judged, so ③ never fires —
falls through to ④ instead of guessing "low relevance."

"Q2+" and "top percentile" both use the paper's **effective percentile**
(see §3), not the raw JCR value — an ESCI journal doesn't get to count as Q1
just because its raw JIF quartile says so.

## 3. ESCI percentile penalty

JCR indexes journals under SCIE / SSCI (equivalent rigor) or ESCI (a much
lower bar, but the sheet still assigns it ordinary quartiles). Rule: an ESCI
journal's percentile is reduced by 25 points before any tier judgment or
sorting — roughly one quartile band — and clamped at 0, never excluded
outright. SCIE/SSCI and downgraded-ESCI papers are then sorted together, not
kept in separate buckets.

A journal that spans multiple JCR categories (`学科类别 == "Multiple"`) has
one percentile *per category*, parsed from the `各学科分区详情` cell. When a
`--field-major` hint is given and matches one of the journal's categories,
that category's percentile is used; otherwise the highest-percentile
category is used (the generous default).

## 4. UTD24 override

For business/econ-adjacent categories, a paper in a UTD24 journal is treated
as tier-① regardless of what its raw JCR percentile computes to — the list
is a stronger, hand-curated quality signal than a mechanical percentile cutoff
for those 24 journals specifically. The list is public academic knowledge
(not derived from the user's JCR file) and is a hardcoded constant in
`journal_ranking.py`; verify it against UTD's own page before relying on it,
as it occasionally sees small revisions.

## 5. Journal name matching

OpenAlex gives a paper's venue as a natural-casing display name; JCR lists
journals in full caps and separately carries an abbreviation column. Four
layers, in order, first hit wins:

1. **ISSN** — when the paper carries an ISSN (`fetch_openalex.py`'s
   `works()` supplies `venue_issn`), matched against JCR's `ISSN`/`eISSN`
   columns (normalized: digits and the trailing check-digit `X` only,
   hyphens/spaces stripped). A formal identifier, immune to the
   display-name ambiguity below — checked first when available.
2. **Exact, normalized full name** — both sides upper-cased, punctuation
   stripped, whitespace collapsed, compared for equality.
3. **Exact, normalized abbreviation** — same normalization, matched against
   JCR's own `期刊缩写` column. Checked against the full 2026 JCR extract
   this project ships against: 100% populated, zero collisions across 22,643
   rows, so an abbreviation hit is treated as high-confidence, same as a
   full-name hit (no fuzzy-matching caveats needed for this layer).
4. **Fuzzy fallback** — token-Jaccard prefilter (≥0.5) then
   `difflib.SequenceMatcher` ratio, combined score must be ≥0.85. Used only
   when the first three layers miss.

**Why the fuzzy threshold is NOT loosened to catch truncated names.** A real
case surfaced during testing: OpenAlex returns the venue as "Angewandte
Chemie" while JCR lists it as "ANGEWANDTE CHEMIE-INTERNATIONAL EDITION" —
correct match, but scores only 0.55 (jaccard 0.50, ratio 0.61), well under
the 0.85 threshold. Tempting to lower the threshold — except a genuinely
*wrong* match, "Journal of Marketing" vs "Journal of Marketing Research"
(different journals), scores 0.77 on the same formula, *higher* than the
correct-but-truncated Angewandte case. No jaccard/ratio/token-subset
threshold can separate these safely from real JCR data — short journal-name
pairs that differ only by a trailing qualifier ("...and Economics",
"...Research", "-International Edition") are common, and some of those
qualifiers denote a genuinely different journal while others don't. ISSN
matching (layer 1) is the correct fix for the truncated-name case instead of
gambling on text similarity; the fuzzy layer stays conservative on purpose.

Unmatched papers are always reported as `unmatched` and excluded from
percentile-based judgments — never silently treated as best or worst. Every
match result records which layer produced it (`matched_by`), so hit-rate per
layer is easy to audit and the fuzzy threshold can be tuned against real data.

## 6. Relevance scoring

The user's research interests are 1–3 free-text keywords/phrases, not a
fixed taxonomy, so relevance is **keyword/phrase overlap** (normalized
substring match against the paper's title + OpenAlex topics), not semantic
matching — there's no free, reliable semantic-similarity service available
here. Any relevance note shown to the user says explicitly "based on keyword
matching, for reference only," so it isn't mistaken for a real judgment of
topical fit.

## 7. 代表作排序依据：为什么不能直接按影响因子（JIF）排

`pick_representative_papers()` 早期实现按论文所在期刊的原始影响因子（JIF数值）
从高到低排序。这是个真实的bug：JIF的量纲在学科间差异巨大——医学类期刊
JIF动辄50-600，金融类顶刊JIF通常只有5-15——直接按JIF数值排序，会让一篇
发在医学期刊上的论文系统性地排到金融顶刊论文前面，这和"论文相对其所在
学科而言有多顶尖"完全是两回事。

现在改用 **优先级分档（priority_tier）**，逐级判断，"插队"到前面的每一种
情况都有 stated reason（存在 `priority_reason` 字段里，最终会写进
"代表作推荐"表的"排序理由(是否插队)"列，以及小样本预览的输出里）：

| 优先级 | 条件 | 插队原因 |
|---|---|---|
| 0（最高） | 命中 UTD24 | 呼应 §4：UTD24 已经在"分档"层面覆盖数字百分位判断，选代表作时保持同一套逻辑，不能分档时说它是①档、选论文时又把它排到别的百分位更高但非UTD24的论文后面 |
| 1 | JCR学科类别内排名前3（如 3/109） | 排名比百分位更敏感：两本期刊都显示～99百分位，一本可能是大类目里的第2名，另一本是第18名——大类目下"前几名"和"前百分之几"是不同粒度的信号，排名能分辨，百分位分辨不出来 |
| 2 | 学科类别内排名前5 | 同上，门槛放宽一档 |
| 3 | 已匹配JCR，无特殊排名 | 按有效百分位（ESCI降级后）从高到低排序，可跨学科比较 |
| 4（最低） | 未匹配到JCR | 只在候选不足3篇时才会被拿来补位，且理由明确写"仅作为候选不足时的兜底" |

同一优先级内部按百分位（而不是JIF）排序，因为百分位是JCR自己算好的
跨学科可比口径；JIF数值本身不是。

①档"优先展示窗口B内的SSRN工作论文"和④档"按JCR排名取前3篇"这两条规则
的相对顺序，是交接文档§1.1本身的既定设计（SSRN工作论文代表最新进展，
优先级设定为独立于期刊排名之外的另一个维度），这次改动没有变更这一层，
只是把"期刊论文内部怎么排"从JIF改成了priority_tier。

## 8. 研究方向信号：不成立 / 少见 / 桥梁三档独立规则

一位教授窗口A的论文如果绝大部分不在其主领域，值得让用户知道；但不同的
"不在主领域"情况，性质完全不同——金融教授发点信息系统/统计学论文再正常
不过，但金融教授发肿瘤医学论文基本不可能是同一个人的真实研究方向。早期
版本把这些情况全部塞进同一条"比例阈值"逻辑里判断，这是设计上的错误：
桥梁学科和根本不可能成立的组合，需要的证据量应该完全不同，不该共用一套
"占比超过50%"这样的单一标准。

现在改成`resolve_domain_signal()`，把可能出现的每一对学科关系分成三档，
各自独立判断：

### 8.1 学科分类：17个细分大类，归入5个家族

JCR的254个学科类别先用关键词匹配归到17个细分大类（`_domain_bucket()`，
逻辑不变：词首边界匹配+"主类目,子类目"格式优先取逗号前缀，避免子串误伤，
详见§5和pitfalls.md #15的历史教训）：

| 家族 | 包含的大类 |
|---|---|
| A. 商科 | 商科/经济/管理（金融、经济、管理、市场营销、会计、运筹研究——内部关联度高，不拆） |
| B. 硬科学 | 医学/临床、神经科学、化学、生物学/生命科学、农业/食品科学、物理/天文、材料科学 |
| C. 量化 | 计算机科学、数学/统计、工程 |
| D. 人文社科 | 心理学、社会学/政治学/传播学、法学、教育学、人文 |
| E. 地球/环境科学 | 单独一类，不拆 |

拆分原则：商科和地球环境内部子领域跟其他学科的桥梁关系基本一致，拆了没有
额外判断力，保持粗粒度；硬科学、量化、人文社科三个家族内部子领域跟其他
学科的桥梁关系差异较大（比如心理学和商科关系紧密，法学/人文和商科基本
不沾边；数学统计和金融关系紧密于纯计算机科学；材料科学和天文物理的学科
气质差异不小），按学科惯例拆开，判断力更强。

### 8.2 关系判断：家族默认值 + 具体例外

两两学科对的关系（❌不成立 / 🟡少见 / ✅桥梁）不是17×17=136对全部手工
判断，而是"5个家族×5个家族"先定默认值，再对特例单独覆盖——维护量固定
在"25个家族对+一份短例外表"，以后学科继续拆分也不会让判断表爆炸。

**家族默认关系表**（A=商科, B=硬科学, C=量化, D=人文社科, E=地球环境；
同家族内部默认✅，因为共享的学术训练背景让同时产出两边的论文很常见）：

| | A商科 | B硬科学 | C量化 | D人文社科 | E地球环境 |
|---|---|---|---|---|---|
| **A商科** | — | ❌ | ✅ | 🟡 | ✅ |
| **B硬科学** | ❌ | ✅(家族内部) | ✅ | 🟡 | ✅ |
| **C量化** | ✅ | ✅ | ✅(家族内部) | ✅ | ✅ |
| **D人文社科** | 🟡 | 🟡 | ✅ | ✅(家族内部) | 🟡 |
| **E地球环境** | ✅ | ✅ | ✅ | 🟡 | — |

**具体例外**（覆盖对应的家族默认值，每条都对应一个真实存在或明确不存在的
交叉学科）：

| 学科对 | 家族默认 | 例外判定 | 理由 |
|---|---|---|---|
| 商科 × 神经科学 | ❌(A-B) | ✅ | 神经经济学/行为经济学 |
| 商科 × 农业/食品科学 | ❌(A-B) | 🟡 | 农业经济学 |
| 商科 × 材料科学 | ❌(A-B) | 🟡 | 关键矿产供应链经济学 |
| 神经科学 × 心理学 | 🟡(B-D) | ✅ | 认知神经科学，体量很大，不该只算少见 |
| 医学/临床 × 心理学 | 🟡(B-D) | ✅ | 健康心理学/临床心理学 |
| 农业/食品科学 × 物理/天文 | ✅(B家族内部) | 🟡 | 农业物理学，存在但小众 |
| 农业/食品科学 × 材料科学 | ✅(B家族内部) | 🟡 | 农业生物材料，存在但小众 |
| 物理/天文 × {心理学,社会学/政治学/传播学,法学,教育学,人文} | 🟡(B-D) | ❌ | 硬物理和人文社科没有实质性建制交叉，比B-D整体默认更极端 |
| 材料科学 × {心理学,社会学/政治学/传播学,法学,教育学,人文} | 🟡(B-D) | ❌ | 同上 |

代码里对应`FAMILY_OF`（大类→家族映射）、`_FAMILY_DEFAULT`（家族默认表）、
`RELATIONSHIP_EXCEPTIONS`（例外表），`bucket_relationship(a, b)`先查例外表，
查不到再查家族默认表。这份关系表不是穷尽的——后续遇到具体案例判断不对，
随时可以在`RELATIONSHIP_EXCEPTIONS`里加新例外，不需要重新设计整个表结构。

### 8.3 三档各自的触发规则

先确定**主领域**：优先用`--field-major`锚定（如果它能匹配上窗口A论文
实际出现过的某个大类），锚不上再退回"论文数最多的大类"投票兜底——这是
用户对这批roster的先验知识，比单篇论文的分类投票靠谱，尤其是当真正的
主领域论文数量恰好不是最多的那一类时（比如某几年凑巧在别的学科发得更多，
投票法会把方向判反）。

把主领域之外出现的每个大类，按`bucket_relationship(主领域, 该大类)`分成
三组，对每组分别判断：

| 关系 | 触发条件 | 结果 |
|---|---|---|
| ❌不成立 | 该关系下所有论文汇总 >1篇 | **整体不分档、不推荐代表作**，建议人工核实身份 |
| ❌不成立 | 该关系下所有论文汇总 =1篇 | 把这1篇论文所在的**整个学科桶排除**（窗口A和窗口B都不再采信），不阻断，继续往下走 |
| 🟡少见 | 占比 ≤30% | 沉默，不提示 |
| 🟡少见 | 占比 >30% 且 机构数≤4 | 提示"研究领域较细、针对性较高"，正常推荐 |
| 🟡少见 | 占比 >30% 且 机构数>4 | 判定过于分散，不分档、不推荐 |
| ✅桥梁 | 占比 ≤50% | 沉默，不提示 |
| ✅桥梁 | 占比 >50% 且 机构数≤4 | 提示"该作者倾向交叉学科研究"，正常推荐 |
| ✅桥梁 | 占比 >50% 且 机构数>4 | 判定过于分散，不分档、不推荐 |

**优先级**：不成立 > 少见 > 桥梁，只报最先触发的一条——❌不成立分支的
"排除1篇"处理完之后，仍会继续检查🟡少见和✅桥梁（不是排除完就直接跳过，
因为排除只解决了1篇论文的问题，不代表其余大类没有问题）；但只要🟡少见
分支产生了任何结果（不管是提示还是阻断），就不再检查✅桥梁分支。

**机构数**用的是`rec["affiliation_institutions"]`——OpenAlex返回的完整
职业生涯机构历史，不是当前机构。≤4个机构，读作"这是一段连贯的单一学术
生涯"的佐证；>4个，同样的占比读作"和单一连贯生涯不太一致"，值得更谨慎。

**样本量门槛**：🟡少见和✅桥梁两个比例判断，都要求窗口A匹配JCR成功的
论文总数（排除❌不成立已经排除掉的那1篇之后）≥4篇才评估，论文太少时
"占比"本身没有统计意义。❌不成立分支是数量判断（>1篇），不受这条门槛
限制——判断"是否存在2篇根本不该同时存在的论文"不需要总样本量支撑。

### 8.4 架构上的关键决定：排除必须发生在分档之前

`resolve_domain_signal()`在`main()`里于`classify_professor()`和
`pick_representative_papers()`**之前**单独执行一次，不是`classify_professor`
内部的一个步骤——因为它的"排除某个学科桶"这个结果，要同时影响窗口A（分档
用）和窗口B（代表作候选用），必须在两者都还没被后续函数处理之前就决定好。
`classify_professor()`因此是纯粹的①②③④决策树，不感知研究方向信号；
`main()`负责编排："先算信号→如果block就整体跳过→如果有excluded_buckets
就过滤works_a和works_b→再调用classify_professor和pick_representative_papers"。

**关于窗口A/B的包含关系**：`--window-b-since`必须不早于`--window-a-since`
（`main()`会在启动时校验，配反了直接报错退出）——这保证了窗口B的期刊
论文永远是窗口A期刊论文的子集，"排除"这个决定在窗口A算出来就是完整、
准确的，不会出现"窗口A说排除了，窗口B又冒出一篇窗口A没统计到的同类论文"
这种前后矛盾。

### 8.5 输出

`rec["journal_ranking"]["domain_signal"]`携带完整结果：`primary`（主领域）、
`excluded_buckets`（被排除的大类列表）、`block`（是否整体不分档不推荐）、
`block_reason`、`note`（🟡/✅分支的提示文字，或❌分支排除1篇时的说明）。
被block的教授，`tier`字段是新增的特殊值`"contaminated"`（区别于原有的
①②③④四档），`representative_papers`固定为空列表。

`main()`结尾会分两份清单打印：先打印"研究方向组合不成立、已跳过推荐"的
教授（⛔，对应block=True的记录），再打印"研究方向有提示"的教授（💡，
对应note非空但没有block的记录）——阻断的信息优先级更高，排在提示前面。
最终xlsx的roster sheet：`JR_学术分档`列被block的记录显示"⛔研究方向组合
不成立(已跳过推荐)"，`JR_研究方向偏移提示`列只在有note且未被block时才有
内容（被block的记录这一列留空，因为block_reason已经在`JR_分档依据`列
完整显示，重复展示没有额外信息量）。

## 9. Data-handling rule for the JCR file itself

The JCR journal list is licensed data. This project:

- never bundles the user's JCR xlsx or any full database derived from it in
  the `.skill` package or the git repo;
- treats `load_jcr()`'s output as in-memory/temp-file-only for the current
  run;
- excludes any local JCR-derived cache file from version control (see
  `.gitignore`'s `*jcr*cache*` rule) if a caller ever adds one;
- ships only the UTD24 constant as public academic knowledge, which is not
  derived from the user's JCR file and carries no such restriction.

Every run of `journal_ranking.py` expects the user to supply their own JCR
xlsx via `--jcr` (or the Colab upload cell); the README documents this
requirement rather than working around it.
