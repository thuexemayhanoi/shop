# PROC-SCHEMA-GEO — Structured Data & GEO

## Objective

Ensure structured data (JSON-LD) matches the actual page type and visible
content, and that content is written for genuine answerability
(Generative Engine Optimization principles) — WITHOUT fake reviews or
ratings, and WITHOUT promising rich results or AI citations.

## Preconditions

- Read the article shell rules in `docs/ARTICLE-RULES.md` (schema is part
  of the page shell) and the scorer's schema_metadata section weights in
  `config/article-rubric.json`.

## Canonical data sources

- `scripts/article_lib.py` (Article class) — what the validator actually
  checks for `has_article_schema`, `has_breadcrumb`, author, date.
- `config/article-rubric.json` — schema_metadata scoring (10 pts:
  Article schema 5, breadcrumb 3, author 1, date 1).

## Steps

1. **Per-article schema gate** (verified command):

   ```bash
   python3 scripts/score_article.py <article>
   ```

   Requirements enforced for every production article:
   - `Article` JSON-LD: headline = the article's real `<h1>`/title,
     author Person "Mr Tú", datePublished = the manifest's
     `date_published`, mainEntityOfPage = the article's own canonical URL.
   - `BreadcrumbList` JSON-LD: Trang chủ → parent category hub → article.
   - Schema must match the VISIBLE content. Never describe things the page
     does not show (no invented offers, no fake local business data inside
     article schema).
   - Exactly one Article + one BreadcrumbList per page (shell rule).
2. **Schema type = page type**:
   - Article pages → Article (+ BreadcrumbList). This is the implemented
     and enforced set.
   - Commercial pages (index/landing/pricing): currently have their own
     HTML/meta but NO dedicated LocalBusiness/Product/Organization schema
     — NOT IMPLEMENTED (see TODOs). Do not add it ad hoc: it must be
     designed with owner confirmation of every field (address, geo,
     hours) from `config/business-facts.json` trusted data only.
3. **No fake engagement signals**: review/rating/aggregateRating schema
   must NEVER be generated anywhere. There is no review system in this
   repo; any rating markup would be fabricated. (Hard prohibition.)
4. **GEO answerability (writing-level, reviewed in PROC-SEO-CONTENT)**:
   - Clear direct answers early in the article (the intent answered in
     the intro; FAQ sections with real questions).
   - Consistent entities: stable names (Mr Tú, shop, districts) across
     pages; consistent hours/phone from trusted config.
   - Citations to authoritative sources for legal/factual claims
     (the source gate already enforces ≥1 official URL where required).

## Expected results

- Scorer schema_metadata = 10/10 on every production article; Article +
  BreadcrumbList present, matching visible content.

## PASS/FAIL criteria

- PASS: schema gate 10/10 + manual check that schema fields mirror the
  visible page (headline, dates, URLs) and contain no review/rating data.
- FAIL: missing/mismatched schema, datePublished ≠ real publish date,
  schema describing non-visible content, any review/rating markup (P0).

## Error handling

- Schema mismatch → bounded repair (schema/metadata step), re-run the
  scorer; do not hand-tune JSON-LD outside the article file.
- Rich result not appearing in Google: this is NOT a defect and NOT
  actionable by us — schema is a necessary input, never a guarantee.
  Record observation only.

## Checkpoint

- Evidence: scorer output (schema_metadata line) + the JSON-LD block
  itself quoted in the chunk report.

## Rollback

- Schema fixes are in-place edits to the article file (forward-only).

## TODO / NOT IMPLEMENTED (do not claim otherwise)

- TODO (needs owner decision): LocalBusiness/Organization schema for the
  commercial pages, with owner-confirmed NAP data.
- NOT IMPLEMENTED: FAQPage schema (FAQ sections exist as plain HTML).
- NOT IMPLEMENTED: any GEO/AI-citation tracking. No tool in this repo
  measures whether AI engines cite the site; never report GEO "success".
- NEVER PROMISE: rich results, knowledge panel inclusion, or AI citation
  — outside our control entirely.
