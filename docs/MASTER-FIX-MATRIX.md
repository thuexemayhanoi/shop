# MASTER-FIX-MATRIX — Living Defect & Risk Ledger

Merge duplicates; one row per real issue. Read progress/state from data
(`data/content-matrix.csv`, `reports/batches/factory-progress.json`,
`sitemap.xml`, CI history) — never from memory or older docs. When code or
a procedure changes, update the affected rows in the SAME change.

## Row schema (every row must have all fields)

```
| ID | Sev | Scope | Root cause | Evidence | Depends on | Fix | Risk | Status | Before/After | Commit | Live check | Rollback |
```

- `ID`: FX-NNN (stable, never reused).
- `Sev`: P0 (blocks publish/site integrity), P1 (user-visible defect),
  P2 (quality/verification gap), P3 (cleanup/accepted limitation).
- `Status`: OPEN / IN PROGRESS / FIXED (code) / FIXED (live-verified) /
  NOT VERIFIED (fix deployed, visual/field confirmation missing) /
  ACCEPTED (documented limitation).
- Evidence, Before/After, Commit, Live check: concrete outputs, never
  adjectives.

## Current matrix (2026-09-27, HEAD 09d7eeb4)

| ID | Sev | Scope | Root cause | Evidence | Depends on | Fix | Risk | Status | Before/After | Commit | Live check | Rollback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FX-001 | P2 | `gioithieu.html` header 1025–1440px | nowrap flex children could overflow container | Source: tiered compact CSS + `min-width:0` added; `node --check` n/a; live 200 + md5 match | none | Responsive tiers (1281–1440, 1025–1280), status-widget hidden ≤1440px | Visual regression on other pages is NOT covered — only gioithieu was changed | NOT VERIFIED (fix deployed; no rendering tool available) | Before: no tiers, widget hidden ≤1280px. After: 2 tiers + min-width:0 | 81fe78c2 | HTTP 200 + byte-identity only; NO device/browser visual check | Restore previous CSS content (git history) |
| FX-002 | P2 | Whole site | No visual regression testing capability in the pipeline (no browser/Lighthouse/device) | All UI verification is grep/tests/curl; e.g. FX-001 cannot be visually confirmed | CI tooling decision | TODO: add headless Lighthouse (lab) step + define a manual device spot-check protocol | Lab scores ≠ real-user CWV; must be labeled lab | OPEN | n/a | none | n/a | n/a |
| FX-003 | P2 | Monitoring | Google Search Console / field Core Web Vitals not connected (no verified owner access in pipeline) | PROC-POST-PUBLISH TODO section | Owner grants access | TODO: owner connects Search Console; then impressions/clicks/CTR per PROC-POST-PUBLISH | none (data gap only) | OPEN | n/a | none | n/a | n/a |
| FX-004 | P3 | Redirects | GitHub Pages project sites have no server-side redirect mechanism; site policy also forbids URL changes | PROC-SEO-TECHNICAL §C | none | None needed while policy forbids slug/URL changes; any future URL migration needs an explicit owner-approved refactor | Changing URLs would break indexed pages with no recovery | ACCEPTED | n/a | n/a | n/a | n/a |
| FX-005 | P3 | Repo root | Legacy MotoAI v39/v41 script files unused in deployment (kept per chatbot-history decision) | README §3: canonical chatbot is the external embed; these files must not be loaded | Owner decision | TODO (owner approval): remove or archive under docs/ history | Zero runtime risk; repo hygiene | ACCEPTED (documented) | n/a | n/a | n/a | n/a |
| FX-006 | P2 | Site-wide business claims | Historical: 29 unsupported claims across 30 root pages (opening_hours 21, delivery 21, late_return 4, support 2) | `python3 scripts/audit_legacy_pages.py` → exit 0; docs/fact-safety-pass-3.md | none | Config-aware audit + neutral wording allowlist + 11 config-aware tests | New pages reintroducing claims are caught by audit/tests | FIXED (live-verified) | 29 unsupported → 0 | fact-safety baseline 0445e58 | audit exit 0 in CI | Re-run audit after any config/policy change |
| FX-007 | P0 | Deploy gate | (Pre-fix risk) unpublished drafts historically written straight to public paths — a draft could be deployed before QA/publish | Live proof after gate implementation: `_drafts/...` → 404; future URL → 404 pre-publish, 200 post-publish; sitemap gained exactly the published rows | `_drafts/` workflow + publish promotion in `factory.mjs` | Drafts live under `_drafts/` (Jekyll never deploys underscore dirs); publish promotes draft→final in one transaction; consistency check flags leaks | A WRITING row's file pushed at its public path = P0 leak, chain stop | FIXED (live-verified) | Drafts at public paths → drafts 404 pre-publish | d70dde0d (gate), 07e00511 (first gated publish) | curl 404/200 evidence recorded | Restore pre-gate content would reintroduce the risk — do not |

## Maintenance rules

1. Any new defect found by any PROC gets a row HERE in the same session
   that finds it; the fix commits update the row in the same push.
2. Duplicate reports of the same root cause are merged into one row
   (keep the oldest ID, append evidence).
3. A P0 row blocks the publish chain until FIXED (live-verified).
4. `NOT VERIFIED` rows must name the tool/evidence still needed.
5. Never close a row without the Live check column filled with real
   output (status code, audit exit, CI run).
