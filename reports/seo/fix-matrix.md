# SEO Fix Matrix

Generated from reports/seo/audit.json. One row per root cause.
Execution status REVIEW unless safe_to_auto_fix is true AND the
fix was applied by scripts/seo/safe_fix.py on an isolated branch.

## Category scores

- technical_seo: 100/100
- crawl_indexability: 100/100
- canonical_sitemap: 92/100
- internal_linking: 100/100
- structured_data: 100/100
- onpage_structure: 96/100
- performance: 100/100
- deploy_hygiene: 100/100

| ID | Sev | Rule | Affected | Root cause | Status |
|---|---|---|---|---|---|
| SEO-001 | P3 | canonical.cross-page | 1 | Canonical deliberately points at another live page (duplicate-content consolidat | REVIEW |
| SEO-002 | P3 | sitemap.pagination-policy | 6 | Generated pagination pages (page-N.html) are excluded from sitemap.xml by the fa | REVIEW |
| SEO-003 | P3 | description.duplicate | 1 | Multiple pages share the same meta description. | REVIEW |

## SEO-001 — canonical.cross-page (P3)
- Root cause: Canonical deliberately points at another live page (duplicate-content consolidation, e.g. legacy landing pages onto the homepage).
- Evidence: canonical resolves to a different existing live route
- Affected: 1 URL(s)
- Safe to auto-fix: False
- Recommended fix: Review: keep if intentional consolidation; else self-canonicalize.
- Best tool: manual review
- Verified: NOT VERIFIED

## SEO-002 — sitemap.pagination-policy (P3)
- Root cause: Generated pagination pages (page-N.html) are excluded from sitemap.xml by the factory sitemap generator policy.
- Evidence: generate_sitemap.py rebuilds /cam-nang/ URLs from matrix rows only; pagination is reachable via hub links and self-canonical
- Affected: 6 URL(s)
- Safe to auto-fix: False
- Recommended fix: Owner decision: keep excluded (crawlable via links) or extend generate_sitemap.py to include pagination.
- Best tool: manual review
- Verified: NOT VERIFIED

## SEO-003 — description.duplicate (P3)
- Root cause: Multiple pages share the same meta description.
- Evidence: duplicate description
- Affected: 1 URL(s)
- Safe to auto-fix: False
- Recommended fix: Differentiate descriptions per page.
- Best tool: manual review
- Verified: NOT VERIFIED
