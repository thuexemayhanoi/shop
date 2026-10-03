# PROC-SCORING-EVIDENCE — Scoring, Evidence & Audit Reports

## Objective

Define the two scoring systems used in this repo, how evidence is recorded,
and how audit results are reported honestly. Rule zero: an internal score
is NEVER a Google score, and a high score NEVER guarantees ranking or
indexing.

## System 1 — Per-article 100-point rubric (machine gate, canonical)

Canonical definition: `config/article-rubric.json`. Enforced by
`scripts/score_article.py` (verified command) and the operator QA flow.

Weights (total 100):

| Section | Pts | Covers |
|---|---|---|
| technical_seo | 15 | title length, meta description, canonical, single H1, lang |
| search_intent | 15 | primary keyword in title/H1/body, valid matrix category |
| content_quality | 15 | thin content, duplicate sentences, placeholders, H2 structure |
| internal_linking | 10 | parent hub linked, ≥3 distinct targets, anchor variety |
| cannibalization | 15 | protected intents, duplicate keywords/titles |
| fact_safety | 10 | prices, deposit wording (see PROC-LOCAL-SEO-DATA) |
| schema_metadata | 10 | Article schema, breadcrumb, author, date |
| readability_structure | 5 | paragraph size, heading order, word length |
| technical_validation | 5 | broken internal links, malformed HTML |

Status thresholds (centralized in `config/article-rubric.json`):
PASS = 75–100 AND no critical failures AND no review
flags (no EXCELLENT tier and no QA warning band).
REVIEW = 70–74 or unresolved review flags, AND no critical failures.
FAIL = <70 OR any critical
failure (the critical-failure list lives in the rubric config — placeholder
text, invented prices, broken links, protected-intent collision, etc.).

This is the Mr Tú Content Factory's internal editorial standard. It is
NOT a Google ranking model and is never presented as one.

## System 2 — Site-level audit evidence report (this procedure)

For site/infra audits (SEO technical, UX, local data), report criteria as
a checklist with per-criterion status and evidence. Format for every
criterion row:

```
| ID | Criterion | Weight group | Status | Evidence |
```

Statuses (exactly these four — nothing else):

- `PASS` — verified with concrete evidence (command output, HTTP status,
  byte comparison, CI run URL/sha).
- `FAIL` — verified defect with evidence.
- `NOT VERIFIED` — could not be checked with available tooling (say which
  tool would be needed).
- `N/A` — does not apply (state why).

Mandatory report properties:

1. **Coverage ratio**: display `verified / total` criteria and the
   percentage. Unchecked criteria are never counted as passing.
2. **No premature totals**: if any criterion in a blocking group is
   missing evidence, publish the report WITHOUT a grand total score —
   list the gaps instead.
3. **Blocking failures (P0)** override everything: a leaked draft, a wrong
   canonical, missing content, a broken build block publish/rollout
   regardless of how high anything scores.
4. **No rubric/test tampering**: scores rise only by fixing the artifact.
   Editing the rubric, tests or thresholds to pass is prohibited; rubric
   changes require owner approval and land in the same commit as the
   rationale.
5. Every claim of success in any report must carry its evidence inline
   (e.g. "HTTP 200 + md5 match, commit <sha>").

## Steps (verified commands producing evidence)

```bash
# Article-level evidence
python3 scripts/score_article.py <article>          # section scores + status + report JSON under reports/article-quality/
# Site-level evidence set (all verified)
python3 -m unittest discover tests                  # 275 tests at time of writing — quote the "Ran/OK" lines
node --test tests/js/factory.test.mjs              # 23 tests — quote "# pass / # fail"
node scripts/js/factory.mjs --consistency          # quote the full CONSISTENCY line (rows + sitemap count)
python3 scripts/validate_content_matrix.py         # quote the OK line (NEVER hardcode counts in reports/prose)
python3 scripts/audit_legacy_pages.py; echo $?     # exit 0 = zero unsupported business claims
python3 scripts/validate_taxonomy.py               # TAXONOMY OK line
# Live evidence (patterns)
curl -s -o /dev/null -w "%{http_code}" <URL>       # status
curl -s <URL> | md5sum                              # byte-integrity vs local
```

## Expected results

- Article: PASS at ≥75 (rubric PASS.min) with the section table quoted in the chunk report.
- Site audit: a criteria table with statuses + evidence + coverage ratio;
  grand total only when no blocking group has gaps.

## PASS/FAIL criteria

- PASS: machine gate PASS + evidence quoted + coverage ratio stated.
- FAIL: any P0 blocker, any PASS claim without evidence, any unverified
  item counted as verified, or a rubric/test edit made during scoring.

## Error handling

- Score < 75 (rubric PASS.min) → repair loop (PROC-SEO-CONTENT), never rubric edits.
- Evidence collection fails (curl error, CI unreachable) → report NOT
  VERIFIED for that criterion; never substitute assumption.

## Checkpoint

- Article scores/outcomes live in the matrix (via operator flows) and
  `reports/article-quality/<slug>.json`; batch reports under
  `reports/batches/`. Audit reports are pasted into the session report +
  material defects get a row in `docs/MASTER-FIX-MATRIX.md`.

## Rollback

- Scoring artifacts are generated (safe to regenerate). A wrongly
  recorded score is corrected by re-running the gate — never by editing
  the report file to the desired value.
