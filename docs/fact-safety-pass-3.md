# Fact-Safety Pass 3 (2026-09-25)

Final fact-safety cleanup before BATCH-001. Baseline: 0445e58.

## Scope
- All 30 root HTML pages audited against config/business-facts.json requires_owner_confirmation nulls (opening_hours, support_hours, delivery_or_pickup, late_return_policy).
- scripts/audit_legacy_pages.py now enforces config-aware fact-safety checks with a neutral conditional wording allowlist and scans inline JavaScript.
- Status widgets no longer infer open/closed from unverified hours; they show neutral contact-to-confirm wording.
- 11 new config-aware tests in tests/test_legacy_seo.py (116 -> 127).

## Result
- Pages with unsupported claims before: 29 (opening_hours 21, delivery 21, late_return 4, support 2).
- After: 0 on all 30 pages. Trusted facts (phone 0816659199, approved prices, deposit wording) preserved.
- Null owner-confirmation fields remain null; nothing unverified was promoted to trusted.
