# PROC-SEO-CONTENT — Content SEO Review

## Objective

Review an article (draft or published) for search intent fit, on-page
structure (title/description/H1–H3), usefulness, factual accuracy,
duplication, cannibalization, anchor quality, internal linking, hub
membership, sources and authorship — WITHOUT keyword stuffing, without
padding word count, and without mass-publishing low-value content.

The per-article writing rules live in `docs/ARTICLE-RULES.md` (canonical,
do not duplicate here). This procedure defines the REVIEW LOOP and the
evidence trail.

## Preconditions

- The article's row manifest (`reports/batches/<BATCH>/rows/<ID>.json`).
- `docs/ARTICLE-RULES.md`, `docs/SEO-OWNERSHIP.md`,
  `config/business-facts.json`, `config/source-policy.json`.

## Canonical data sources

- Primary keyword / intent / working title: the matrix row + manifest.
- Protected intents: `config/seo-ownership.json`.
- Rubric weights: `config/article-rubric.json`.
- Approved prices/models: `config/business-facts.json`.
- Approved legal sources: `config/source-policy.json`.

## Steps (verified commands)

1. **Deterministic review** — the scorer IS the content-SEO reviewer:

   ```bash
   python3 scripts/score_article.py _drafts/cam-nang/<cat>/<slug>.html
   ```

   It reports per-section scores: technical_seo (title 20–75 chars,
   description 60–170, canonical, single H1, lang), search_intent
   (primary keyword in title/H1/body), content_quality (thin content,
   duplicate sentences, placeholders, H2 sections), internal_linking
   (parent hub linked, ≥3 distinct targets), cannibalization (protected
   intents, duplicate keywords, similar titles), fact_safety (prices,
   deposit wording), schema_metadata, readability_structure (paragraph
   size, heading order), technical_validation (broken links, malformed
   HTML), plus the production standard (word count 1,600–2,000 main
   content; 3–5 contextual links; ≤1 commercial; source gate for
   `requires_sources`).

2. **Manual intent review** (agent judgment, recorded in the report):
   - Does the article answer its ONE primary intent early and completely?
   - Would a renter in Hanoi act on it? (usefulness > length)
   - Any section added only to pad word count? → remove (padding is also
     detected deterministically).
   - Any claim needing a source that lacks one? → source gate must pass.
3. **Duplication across articles**: exact duplicate primary keyword or
   title = critical FAIL (scorer). Near-similar title (≥0.90) = REVIEW
   flag → retitle or differentiate the angle before PASS.
4. **Cannibalization vs commercial pages**: the scorer FAILs any article
   whose primary keyword or title/H1 collides with a protected intent in
   `config/seo-ownership.json`. If hit: change the article's angle (keep
   the row's identity — never silently change the row's keyword/category;
   escalate to the owner if the row itself is unviable).
5. **Anchor text**: descriptive, diverse, no generic ("xem thêm",
   "tại đây", "click here"), no repeated exact-match anchors; repeated
   exact-match COMMERCIAL anchor = strong REVIEW.
6. **Internal linking**: parent hub required; child hub when the manifest
   says so; siblings in the same child cluster preferred; only PUBLISHED
   articles (or same-batch) as targets.
7. **Sources & authorship**: `requires_sources=true` → visible
   "Nguồn tham khảo" section with ≥1 approved-domain URL, content verified
   by web research BEFORE writing. Author "Mr Tú" + real publish date in
   Article schema.

## Expected results

- `score_article.py` exit 0, status PASS, score ≥ 75 (rubric PASS.min in
  `config/article-rubric.json`), no critical
  failures, no review flags, and a report file under
  `reports/article-quality/<slug>.json`.

## PASS/FAIL criteria

- PASS: scorer PASS + manual intent review (step 2) recorded as sound.
- FAIL/REVIEW: any scorer REVIEW/FAIL signal, or a manual finding of
  stuffing/padding/off-intent/inaccurate content — the machine score can
  never override a factual defect found by the reviewer.

## Error handling

- Review flag → bounded repair (max 3 attempts per row) in the order:
  factual → legal/source → schema/metadata → structure → style. Never a
  full rewrite for one wrong claim. Exhausted → BLOCKED with reason.
- Keyword collision with a protected page → re-angle the article; if
  impossible, BLOCK the row and escalate (do not change the ledger row's
  identity on your own).
- Suspected factual error in a PUBLISHED article → verify against
  `config/business-facts.json` / official sources → fix forward with a new
  commit; record in `docs/MASTER-FIX-MATRIX.md`.

## Checkpoint

- QA outcomes + scores are recorded in the matrix by the operator QA/publish
  flows (never hand-edited). Per-article reports:
  `reports/article-quality/<slug>.json`.
- Repair attempts are budgeted and recorded (notes carry `repair:N`).

## Rollback

- Drafts: edit freely before publish; nothing to roll back.
- Published content: fix forward only (no deletes, no URL/canonical/slug
  changes). A factual fix is a normal repair commit; record it in the fix
  matrix.

## Hard prohibitions (recap)

- No keyword stuffing; no filler to reach 1,600 words; no bulk low-value
  publishing to hit throughput numbers; no copied text; no fake
  statistics/reviews/quotes; no unsupported superlatives.
