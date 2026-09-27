# PROC-LOCAL-SEO-DATA — Local SEO & Business Data

## Objective

Keep every business claim on the site (prices, opening hours, phone
numbers, locations, policies) sourced EXCLUSIVELY from owner-confirmed
data. Support multiple phone numbers / locations when they are
intentional, and treat them as features — not as inconsistencies to
"fix". Never invent delivery, rescue, promotion, review or any other
business commitment.

## Preconditions

- Read `config/business-facts.json` fully. Understand its structure:
  - `trusted` section (machine-enforced): approved prices per model,
    deposit policy + standard wording + forbidden stale claims,
    phone(s), opening hours.
  - owner-confirmation-null fields (e.g. support hours, delivery/pickup,
    late-return specifics): they are NULL because the owner has NOT
    confirmed them; they must stay null until confirmed.
- Read `docs/fact-safety-pass-3.md` (history: 29 unsupported claims
  removed across 30 root pages, 2026-09-25).

## Canonical data sources

| Data | Source | Notes |
|---|---|---|
| Prices per approved model | `config/business-facts.json` trusted + `assets/js/prices.js` | The ONLY price source for chatbot/calculator/pages. |
| Deposit | `config/business-facts.json` `deposit_policy` | Standard wording + range 2,000,000–5,000,000 VND. Forbidden stale claims are listed there and FAIL the fact-safety gate. |
| Phone numbers | `config/business-facts.json` trusted | Owner confirmed BOTH current numbers are OK — keep contact info and chatbot content unchanged; multiple numbers are intentional. |
| Opening hours | `config/business-facts.json` trusted | 08:00–17:00 daily. Never promise service outside them; never call the shop 24/7. |
| Locations/districts | district pages (`tayho.html`, …) | Owner-created; do not invent new locations or branches. |
| Policies (licence/insurance) | `config/business-facts.json` rules | >50cc needs a valid licence; insurance is the customer's responsibility — never claim included insurance. |

## Steps (verified commands)

1. **Site-wide fact audit** (covers all 30 root pages + inline JS):

   ```bash
   python3 scripts/audit_legacy_pages.py
   # expect exit 0; prints unsupported-claim counts (all 0 on current MAIN)
   ```

2. **Per-article fact gate** (runs inside every scorer invocation):
   `python3 scripts/score_article.py <article>` — the fact_safety section
   (10 pts) FAILs (critical) on: wrong price near an approved model,
   invented fixed price for an unapproved model (50cc, Lead, Janus,
   Attila, NVX, SH, PKL, …), stale deposit claims, deposit amounts outside
   the approved range wording.
3. **Full-suite enforcement**:

   ```bash
   python3 -m unittest discover tests   # includes config-aware fact-safety tests
   ```
4. **Writing rules for any page or article**:
   - Unapproved models must use the standard "liên hệ để xác nhận giá
     hiện tại" wording — never a fixed price.
   - Deposit mentions must use the approved range wording; no "miễn cọc",
     no guaranteed reductions.
   - No invented: delivery times, rescue service, promotions, customer
     reviews, ratings, awards, "best/cheapest in Hanoi" superlatives.
   - Anything not in the trusted files → confirm with Mr Tú by phone or
     Zalo BEFORE publication; if unconfirmed, it stays out of the page.

## Expected results

- `audit_legacy_pages.py` exit 0, zero unsupported claims.
- No page contradicts `config/business-facts.json`.
- Multiple phone numbers / district pages render coherently with their
  role described (contact page, chatbot, footer) — NOT reported as errors.

## PASS/FAIL criteria

- PASS: audit exit 0 + fact_safety 10/10 on the article gate + no
  owner-unconfirmed claim introduced.
- FAIL: any unsupported business claim (publish blocker, P0), any stale
  deposit phrasing, any invented price/hour/policy.

## Error handling

- Found an unsupported claim on a page: fix the page to the trusted
  wording (or remove the claim), re-run the audit + tests, record the
  incident in `docs/MASTER-FIX-MATRIX.md`.
- Owner gives NEW facts (price change, new hour, new location): update
  `config/business-facts.json` in the same change that updates the pages,
  with the owner confirmation noted in the commit message; never update
  pages without the config.
- Unconfirmed-but-needed info: publish the page WITHOUT that info and
  direct users to contact Mr Tú (phone/Zalo) for specifics.

## Checkpoint

- The audit is re-run in CI (article-quality workflow) and in the
  operator flows; its exit status is part of the chunk report evidence.
- Any fact change = one commit containing config + affected pages +
  updated tests, so the audit never drifts.

## Rollback

- A bad fact change is reverted by restoring the previous content of
  `config/business-facts.json` + affected pages (forward-fix preferred:
  correct the value again with owner confirmation; the config is the
  truth, pages follow).
- Never "roll back" by deleting a page or changing its URL.

## Multiple numbers / locations policy (explicit)

Differences between phone numbers, or several district pages, are NOT
inconsistencies. Do NOT "unify" them without owner instruction. Report
them as "intentional, owner-confirmed" in audits.
