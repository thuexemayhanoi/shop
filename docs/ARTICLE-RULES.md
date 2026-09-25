# Article Rules

Requirements every article must satisfy before it can score PASS. The scorer
(`scripts/score_article.py`) measures these deterministically. Quality >
length; no arbitrary keyword-density rules exist in this factory.

## Intent & structure

- One clear search intent; one primary topic per article.
- The useful answer appears early in the article.
- Exactly one H1; useful H2/H3 hierarchy; no skipped heading levels.
- No duplicate sections; no filler written only to pad word count.
- No exact word-count requirement. Only the configurable thin-content
  threshold applies (`thin_content_min_words`, default 300, in
  `config/article-rubric.json`).

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

- Link to the parent category hub.
- Link to relevant related content (sibling hubs, relevant commercial pages)
  only where semantically natural.
- Natural anchor text ("cẩm nang an toàn", "kinh nghiệm đi xe máy"); never
  repeated exact commercial anchors like "thuê xe máy Hà Nội" unless the
  context genuinely targets that commercial page.
- No broken internal links, no self-link spam.

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
