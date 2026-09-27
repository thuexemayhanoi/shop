# PROC-POST-PUBLISH — Post-Publish Monitoring

## Objective

Watch what happens AFTER publication: indexing, impressions, clicks, CTR
and queries — where data access exists — and make honest comparisons over
suitable time windows. Success is NEVER concluded from a green CI run or
an HTTP 200 alone.

## Preconditions & current capability (honest state)

- VERIFIED TODAY (works, use it): HTTP status + byte-integrity + sitemap
  membership of every published URL (see PROC-SEO-TECHNICAL), CI status,
  matrix/progress ledgers.
- NOT AVAILABLE: Google Search Console access is not connected for this
  site in this pipeline. Until the owner connects it, indexing,
  impressions, clicks, CTR and query data CANNOT be reported — only
  marked NOT VERIFIED. Do not fabricate or estimate these numbers.
- NOT IMPLEMENTED: rank tracking, log-file (crawl) analysis, AI-engine
  citation tracking.

## Canonical data sources

- `sitemap.xml`, `data/content-matrix.csv`,
  `reports/batches/factory-progress.json` (read numbers from files).
- Search Console (once connected): property
  `https://thuexemayhanoi.github.io/shop` (URL-prefix type).

## Steps

### A. Immediate post-publish verification (implemented, verified)

After every publish (see PROC-PUBLISH step 8): every new URL 200 +
byte-identical + in sitemap; drafts 404; CI + Pages deploy green. Record
the evidence in the chunk report.

### B. Deployment drift sweep (implemented)

Periodically re-run the live sweep of PROC-SEO-TECHNICAL §B over the
sitemap (all URLs 200, no noindex, robots.txt unchanged, count agreement
with `--consistency`). A URL that was 200 and later 404s = P1 incident
→ row in the fix matrix.

### C. Search performance review (BLOCKED until Search Console is connected)

When access exists, per PROC convention:

1. Compare windows of equal length (e.g. last 28 days vs the previous 28),
   never cherry-picked ranges.
2. Look at: indexed pages count (Coverage), impressions, clicks, CTR,
   average position for the article queries; filter by
   `https://thuexemayhanoi.github.io/shop/cam-nang/*`.
3. Expected healthy signal for a new article batch: gradual impressions
   growth over weeks; sudden de-indexing of previously indexed URLs is a
   P1 investigation (check canonical, noindex, sitemap, duplicates).
4. Record findings as evidence rows; do not claim "SEO success" from any
   single green signal. Conclusions require: indexation + impressions
   trend + no technical regressions together.

## Expected results

- A: all checks pass with recorded evidence.
- B: zero drift between sweeps.
- C: (future) a dated comparison snapshot in the session report.

## PASS/FAIL criteria

- PASS: A+B fully evidenced; C reported or explicitly marked
  NOT VERIFIED (no access) — honesty is the pass condition.
- FAIL: any drift/regression unreported, or any fabricated/estimated
  Search Console number, or a success conclusion drawn from CI/200 alone.

## Error handling

- De-indexed/404 published URL → PROC-SEO-TECHNICAL error handling;
  P1 row in the fix matrix.
- Suspected ranking drop → do NOT bulk-change URLs/canonicals/noindex and
  do NOT delete content. Investigate with evidence; any structural change
  requires explicit owner approval (site policy: no URL changes).
- Search Console shows errors (canonical conflicts, duplicate without
  canonical) → reproduce with the site-level checks, fix forward.

## Checkpoint

- Every sweep's outputs are saved in the session report; incidents get
  fix-matrix rows; monitoring status ("what we can and cannot see") is
  restated in every report until Search Console is connected.

## Rollback

- Monitoring is read-only; nothing to roll back. Any remediation it
  triggers follows the other procedures' rollback rules.

## TODO (owner actions needed)

- Owner connects Google Search Console (URL-prefix property for the site)
  and Bing Webmaster if desired.
- THEN: define the recurring review cadence and add the exact report
  template here once the first real export exists.
- Field Core Web Vitals need Chrome UX/CrUX data access — same owner
  decision (lab Lighthouse alone is NOT field data).
