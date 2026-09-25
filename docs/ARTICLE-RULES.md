# Article Rules

## PRODUCTION ARTICLE STANDARD (Mr Tú Content Factory)

This is the site's internal editorial standard. It is NOT a Google
requirement — it is the owner-selected quality bar for this factory.

- TARGET LENGTH: **1,600–2,000 Vietnamese words** of main editorial content
  - 1,600–2,000 = length requirement satisfied
  - 1,200–1,599 or 2,001–2,300 = REVIEW (cannot PASS without repair)
  - <1,200 or >2,300 = FAIL
  - Words are counted from the article MAIN CONTENT only: the
    `<article>`/`<main>` container minus navigation, header, footer,
    breadcrumb, chatbot, scripts and styles. Padding never satisfies the
    standard: repeated sentences/paragraphs, duplicate sections and filler
    are detected separately and block PASS.
- CONTEXTUAL INTERNAL LINKS: exactly **3–5** inside the editorial body
  - menu, footer, breadcrumb, logo, chatbot, pagination, social and
    external links never count
  - exactly 1 link to the article's parent category hub is REQUIRED
    (Kinh nghiệm → `kinhnghiem.html`, An toàn → `antoan.html`,
    Xe máy → `xemay.html`, Du lịch → `dulich.html`, Cung đường →
    `cungduong.html`, Hỏi đáp → `hoidap.html`)
  - at most 1 contextual commercial landing-page link by default
  - 0 contextual links, missing parent hub, <3 or >5 links: cannot PASS
- PRIMARY INTENT: exactly 1 per article
- H1: exactly 1
- CANONICAL: self-referencing
- SCHEMA: Article (JSON-LD)
- BREADCRUMB: required
- AUTHOR/DATE metadata: required
- RELATED CONTENT: useful related-article links (count toward the 3–5 total)
- ANCHORS: descriptive and diverse — "kinh nghiệm kiểm tra xe trước khi
  nhận" is good; "xem thêm", "tại đây", "bấm vào đây", "click here",
  "link này" are flagged. The same exact-match anchor must not repeat; the
  same exact-match COMMERCIAL anchor repeated is a strong REVIEW.
- SOURCES: required for legal/safety topics with `requires_sources=true`
- BROKEN LINKS: any broken required internal link = FAIL; articles may only
  link to PUBLISHED articles (or articles publishing in the same validated
  batch)
- QUALITY GATE: PASS requires score ≥ 90, no critical failures, no review
  flags, 1,600–2,000 words, 3–5 contextual links, parent hub present, no
  broken links, no protected-intent conflict, fact-safety pass and legal
  sources satisfied

Requirements every article must satisfy before it can score PASS. The scorer
(`scripts/score_article.py`) measures these deterministically. Quality >
length; no arbitrary keyword-density rules exist in this factory.

## Intent & structure

- One clear search intent; one primary topic per article. The 1,600–2,000
  word budget must answer that intent deeply — never mix unrelated intents
  or add unrelated sections just to reach the word count.
- The useful answer appears early in the article (answer the intent in the
  introduction; avoid long generic Hanoi/tourism preambles).
- Exactly one H1; useful H2/H3 hierarchy; no skipped heading levels
  (H1 → H3 without H2 is flagged).
- Readable paragraphs; avoid giant text walls.
- No duplicate sections; no filler written only to pad word count
  (detected and blocked).
- No exact word-count requirement for SAMPLE fixtures. For production rows
  the 1,600–2,000 standard above applies. The configurable thin-content
  threshold (`thin_content_min_words`, default 300) still applies to all
  articles.

## Truthfulness (critical failures otherwise)

- No fake statistics, no fake reviews, no fabricated customer quotes.
- No fabricated legal claims, fines, licence or insurance rules.
- No fabricated prices — approved prices only, from
  `config/business-facts.json` / `assets/js/prices.js`.
- No fixed price for unknown/unapproved models (50cc, Lead, Janus, Attila,
  NVX, SH, PKL, …) — those must say "Liên hệ để xác nhận giá hiện tại".
- No unsupported superlatives ("tốt nhất Việt Nam", "rẻ nhất Hà Nội").
- No hidden keyword stuffing; no copied text from other sites; no duplicate
  article text.

## Categories

Exactly ONE primary category per article:

| Hub | Category |
|---|---|
| `kinhnghiem.html` | Kinh nghiệm |
| `antoan.html` | An toàn |
| `xemay.html` | Xe máy |
| `dulich.html` | Du lịch |
| `cungduong.html` | Cung đường |
| `hoidap.html` | Hỏi đáp |

Do not create additional top-level Cẩm nang categories without explicit owner
approval.

## Internal linking

- 3–5 contextual internal links inside the editorial body (counted from
  the main content container only; navigation/footer/breadcrumb links are
  excluded by the tools).
- Link to the parent category hub (required, see standard above).
- Link to relevant informational articles (siblings, related categories)
  where semantically natural.
- At most 1 contextual commercial landing-page link; repeated commercial
  links or repeated exact-match commercial anchors are flagged REVIEW.
- Natural, descriptive, diverse anchor text; generic anchors
  ("xem thêm", "tại đây", "click here") are flagged; never repeat the same
  exact-match anchor.
- No broken internal links, no self-link spam. Article links may only
  target already-PUBLISHED articles or articles publishing in the same
  validated batch.

## Metadata & SEO

- Unique `<title>` (roughly 20–75 chars) and meta description (roughly
  60–170 chars).
- Self-canonical pointing at the article's own URL; no placeholder
  canonicals.
- `lang="vi"`; robots must allow indexing.
- Article schema (JSON-LD) and breadcrumb where the article architecture
  supports it; author/date metadata where applicable.

## Legal-content safety

Articles in An toàn (or any article covering law, fines, licence, insurance,
government rules) that are marked `requires_sources=true` in the matrix MUST
contain a source/reference section with source URLs (official Vietnamese
government/legal domains preferred). The validator checks presence and format
of source links offline — it never fetches the internet. Missing source
evidence yields REVIEW or FAIL; an unsupported legal claim can never PASS.

## Review flags (not critical, but block PASS)

- Thin content below the configured threshold.
- Parent hub not linked.
- Very similar title to another matrix row / article (deterministic
  SequenceMatcher ≥ 0.90).
- requires_sources article lacking source evidence.
