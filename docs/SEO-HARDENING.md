# SEO Hardening — Architecture Contract

Pre-2000 hardening layer. Extends (does not duplicate) the existing QA
engine, sitemap generator, category-page generator, fact-safety audit and
MASTER-FIX-MATRIX ledger.

## Components

| Component | Entry point | Notes |
|---|---|---|
| SEO Engine + Score | `scripts/seo/seo_audit.py` | Deterministic audit of the page tree, sitemap.xml, robots.txt, `_config.yml`. Findings deduplicated by root cause. Category scores (technical, crawl, canonical/sitemap, linking, structured data, on-page, performance, deploy hygiene) are always shown; an overall score can never hide a P0/P1. |
| Fix Matrix | `scripts/seo/seo_fix_matrix.py` → `reports/seo/fix-matrix.{json,md}` | One row per root cause, affected-URL list attached, `safe_to_auto_fix` flag, execution status REVIEW by default. |
| Regression Guard | `scripts/seo/seo_regression.py` + `reports/seo/baseline.json` | Fails on worse state, passes equal/better. Refuses baseline updates while P0/P1 exist. Growth metrics (published pages, sitemap URLs) only regress when they shrink. |
| Schema Guard | part of `seo_audit.py` (rules `schema.*`) | JSON-LD parse, Article/BreadcrumbList presence on article routes, schema URL ↔ live route agreement, stale slug detection. |
| Safe Auto-Fix | `scripts/seo/safe_fix.py` | Allowlist only: `canonical_shopshop`, `canonical_relative` (self-reference absolutization), `sitemap_duplicates`, `config_excludes`. Dry-run default. Hard-refuses factory paths. Ambiguous cases skipped. |
| PR Verifier | `scripts/seo/pr_verify.py` + `.github/workflows/seo-audit.yml` | Runs audit (strict) + fix matrix + regression guard on the EXACT candidate tree, plus factory non-interference snapshot. Merge only if green. |
| Lighthouse CI | `.github/workflows/lighthouse-ci.yml` + `.github/lighthouserc.json` | Lab scores on representative pages (home, banggia, xemay, topic hub, short/long article, Q&A article). Tolerant thresholds to avoid score-noise failures. Never edits prose. |
| Lychee | `.github/workflows/lychee.yml` + `.github/lychee.toml` | Independent link checker. Retries + failure budget for transient external failures; never edits articles for timeouts. |
| CodeQL | `.github/workflows/codeql.yml` | javascript-typescript + python over factory/QA/SEO/frontend scripts. Not a content review. |
| Dependabot | `.github/dependabot.yml` | github-actions ecosystem only (no npm manifest exists). Opens PRs; never auto-merged; must pass QA + PR verifier. |

## Factory non-interference contract

- `scripts/seo/*` NEVER writes: `data/content-matrix.csv`,
  `data/batches/`, `_drafts/`, article prose, business facts.
- Checker workflows use `permissions: contents: read` and their own
  concurrency groups; they never share `article-batch-production`.
- `pr_verify.py` snapshots the matrix + factory-progress hashes before
  and after and fails on any drift.

## Known accepted review items (not defects to fix silently)

- `nhap.html` cross-page canonical → homepage (deliberate consolidation).
- Pagination `page-N.html` excluded from sitemap (factory generator
  policy; pages are crawlable via hub links and self-canonical).
- 7 Yamaha-Sirius articles share one meta description (P3; fixing means
  editing PUBLISHED content → owner decision via the factory repair path).
