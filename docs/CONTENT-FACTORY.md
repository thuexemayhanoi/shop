# Content Factory

Infrastructure that will produce ~2,000 informational articles behind a
deterministic quality gate. Production articles are not written yet; this
document defines how they will be produced safely.

## Lifecycle states

```
PLANNED → WRITING → QA → REVIEW → PASS → PUBLISHED
                     ↘ FAIL      ↘ BLOCKED
```

- `PLANNED` — row exists in `data/content-matrix.csv`, nothing written.
- `WRITING` — an agent has claimed the row and is drafting.
- `QA` — draft complete, quality-gate tools running/repairing.
- `REVIEW` — score 80–89 without critical failures, or unresolved review
  flags; needs human/owner decision. Not publishable.
- `PASS` — score 90–100, no critical failures, no review flags.
- `PUBLISHED` — live on the site.
- `FAIL` — critical failure or score < 80. Must not be published.
- `BLOCKED` — cannot proceed (missing owner confirmation, conflicting facts,
  repeated repair failure). Escalate to Mr Tú; do not guess.

## Rules

- One article task at a time per agent.
- Stable article ID, never reused or renumbered (format `KN-0001`, `AT-0001`,
  `XM-0001`, `DL-0001`, `CD-0001`, `HD-0001` for the six categories).
- Never create an article that is not present in `data/content-matrix.csv`.
- Never silently change an article's intent, keyword or category.
- Never change protected commercial-page ownership (see
  `config/seo-ownership.json`).
- Idempotent execution; resume safely after interruption (matrix status is
  the source of truth).
- No duplicate article ID, no duplicate slug, no duplicate primary keyword.
- Record score and validation state in the matrix after each gate run.
- Publish only PASS articles.
- Never treat a schedule as permission to invent new work.

## Auto-writer contract (future)

1. Fetch CURRENT MAIN; verify the SHA before editing.
2. Read all files in the README agent read order.
3. Select one PLANNED matrix row; ensure no other row is WRITING for the
   same intent.
4. Mark the row WRITING.
5. Write the article per `docs/ARTICLE-RULES.md`.
6. Run the validator, cannibalization checker, scorer.
7. If REVIEW: fix and re-run. Max 3 repair attempts. If still not PASS,
   mark REVIEW/BLOCKED and stop.
8. If FAIL: stop. Do not publish.
9. If PASS: update matrix (score, status PASS) — only then eligible for
   publication.

Automatic article generation is NOT implemented yet; this is the contract a
future auto-writer must follow.

## Scale path

```
pilot 20–30 articles → audit → 100 → audit → 250 → audit
→ larger batches → eventual ~2,000 articles
```

Each audit reviews quality, cannibalization and business-fact compliance
before the next batch. Publishing 2,000 articles in one batch is explicitly
forbidden.

## Where things live

- `config/` — machine-readable truth (facts, rubric, ownership).
- `data/content-matrix.csv` — the backlog and status ledger.
- `data/articles/` — future published articles directory.
- `scripts/` — validator, scorer, cannibalization checker (+ shared lib).
- `tests/` — unit tests + fixtures proving gate behavior.
- `reports/article-quality/` — generated per-article JSON reports (gitignored
  except `.gitkeep`).
- `.github/workflows/article-quality.yml` — CI quality gate.
