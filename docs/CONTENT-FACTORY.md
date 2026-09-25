# Content Factory

Infrastructure that produces up to 2,000 informational articles behind a
deterministic quality gate, in 40 batches of exactly 50 articles. The plan
(2,000 rows) is complete; production article bodies are NOT written yet and
must come from an authorized AI writer or a human author — never templates.

## Scale architecture

- **2,000 production articles** planned in `data/content-matrix.csv`
  (KN 350 / AT 300 / XM 350 / DL 400 / CD 300 / HD 300).
- **40 batches** (`BATCH-001` … `BATCH-040`), **exactly 50 articles each**.
- 8 SAMPLE fixture rows support the test suite and never count as production.
- Verify anytime: `python3 scripts/validate_content_matrix.py`.

## Article URL architecture

Production articles live at `cam-nang/<category-dir>/<slug>.html` with
`slug = <prefix>-<NNNN>-<slugified-title>` (e.g. `cam-nang/kinh-nghiem/kn-0017-….html`).
The six hub URLs (`kinhnghiem.html`, `antoan.html`, `xemay.html`,
`dulich.html`, `cungduong.html`, `hoidap.html`) are unchanged and remain the
parent hub for each article. This is a flat `.html` pattern — no Jekyll
refactor is required for it. A directory-style clean-URL migration would be a
separate, explicit refactor and must not happen silently.

## Lifecycle states

```
PLANNED → CLAIMED/WRITING → QA → PASS → PUBLISHED
                        ↘ REVIEW → REPAIR (max 3) → BLOCKED
                        ↘ FAIL
```

- `PLANNED` — row exists in the matrix, nothing written.
- `WRITING` — a writer agent has claimed the row and is drafting.
- `QA` / `REPAIR` — draft exists, gate tools running or repairing.
- `REVIEW` — score 80–89 or unresolved review flags; NOT publishable.
- `PASS` — score 90–100, no critical failures, no review flags; publishable.
- `PUBLISHED` — **only after the article file is actually committed to MAIN.**
- `FAIL` — critical failure or score < 80. Never auto-published.
- `BLOCKED` — cannot proceed (max repairs exhausted, unconfirmed facts,
  conflicts). Escalate to Mr Tú; do not guess.

Publishing (GitHub Pages) means: the final article file exists at its
production `output_path`, the matrix row says PASS/PUBLISHED, the article is
listed on its category index, it is in `sitemap.xml`, and the commit has been
pushed to MAIN. Never mark PUBLISHED before that commit exists
(`scripts/run_article_batch.py --mark-published` is the explicit post-push
step).

## Publish policy

- `PASS` → publish.
- `REVIEW` → repair, max 3 attempts (run all 3 gate tools after each attempt);
  still REVIEW → `BLOCKED`.
- `FAIL` → not published automatically; mechanically repairable failures may
  use the same 3-attempt budget, but critical fact/legal failures must never
  be papered over.
- **One failed article never blocks the other PASS articles of its batch.**

## Batch orchestration

`scripts/run_article_batch.py` orchestrates ONE batch of at most 50 articles.

```bash
# claim up to 50 PLANNED rows, mark them WRITING, write the manifest
python3 scripts/run_article_batch.py --batch BATCH-001 --prepare
# or the first batch that still has PLANNED rows
python3 scripts/run_article_batch.py --next --batch-size 50

# after an external writer produced the files: QA unfinished rows
python3 scripts/run_article_batch.py --batch BATCH-001 --resume

# after the commit reached MAIN: flip PASS rows to PUBLISHED
python3 scripts/run_article_batch.py --batch BATCH-001 --mark-published
```

- `--prepare` writes `data/batches/BATCH-XXX.json`, a machine-readable
  manifest (article_id, keyword(s), intent, title, slug, output_path, parent
  hub, requires_sources, link targets) that an external AI writer (e.g. a
  Mistral agent) consumes. Manifests/locks are gitignored;
  `data/content-matrix.csv` stays the single ledger.
- The batch size is capped at 50 — a larger `--batch-size` is clamped, never
  silently exceeded.
- **Resume safety**: PASS/PUBLISHED rows are never re-claimed or rewritten;
  interrupted batches continue from the unfinished rows. The matrix state is
  the source of truth.
- **Concurrency lock**: `data/batches/BATCH-XXX.lock` (24h TTL) prevents two
  runners from claiming the same batch; rows already WRITING/QA/PASS/PUBLISHED
  are skipped by any other runner.
- Every run writes `reports/batches/BATCH-XXX.json`:
  requested / written / pass / published / review / fail / blocked + per-article
  results. Reports are gitignored.
- Exit codes: 0 ok, 1 usage/lock, 2 REVIEW articles remain, 3 FAIL articles,
  4 tool error, **5 WRITER_NOT_CONFIGURED**.

## Writer requirement (no fake writers)

`scripts/article_writer.py` defines the provider contract
(`write_article(matrix_row, context)`). With no authorized provider
configured it raises `WriterNotConfigured` and the batch runner stops with
`WRITER_NOT_CONFIGURED`. The repository deliberately contains no template
content generator and no API keys; provider credentials belong in GitHub
Actions secrets only, and none are configured yet.

## Category index and sitemap

- `scripts/generate_category_index.py` — deterministic category listing
  pages under `cam-nang/<category>/index.html`, **50 articles per page**
  (`page-2.html`, …). Pages are generated only when a category actually has
  PUBLISHED articles; empty index pages are never committed.
- `scripts/generate_sitemap.py` — merges the current `sitemap.xml` (every
  existing public URL is preserved) with PUBLISHED production articles only.
  No SAMPLEs, no PLANNED/WRITING/REVIEW/FAIL/BLOCKED, no duplicates, valid
  XML. `--check` verifies freshness.

## CI / workflows

- `.github/workflows/article-quality.yml` — tests (`python3 -m unittest
  discover tests`), matrix validation, and the full article gate; REVIEW/FAIL
  fails CI.
- `.github/workflows/article-batch.yml` — `workflow_dispatch` ONLY (inputs:
  batch_id, batch_size default 50, max 50). Validates the matrix and tests,
  prepares the batch manifest, uploads it as an artifact, and reports
  `WRITER_NOT_CONFIGURED` (notice, not a misleading failure) when no writer
  provider exists.
- **No cron anywhere.** When scheduling is added later, it must never start a
  new batch while an earlier batch is still WRITING/QA.

## Auto-writer contract

1. Fetch CURRENT MAIN; verify the SHA before editing.
2. Read all files in the README agent read order.
3. Prepare/claim one batch (max 50 PLANNED rows) via the batch runner.
4. Write each article per `docs/ARTICLE-RULES.md` (requires_sources rows need
   official-source verification first).
5. Run validator, cannibalization checker, scorer for EVERY article.
6. REVIEW → fix and re-run (max 3 attempts) → still REVIEW → BLOCKED.
7. FAIL → stop, do not publish that article; keep the batch's PASS articles.
8. PASS → commit the article files, push to MAIN, then `--mark-published`
   (this also refreshes the category index and sitemap).

## Rules recap

- One article task at a time per agent; stable IDs, never reused/renumbered.
- Never create an article absent from `data/content-matrix.csv`.
- Never silently change intent, keyword or category of a row.
- Never weaken the gate; all tests must keep passing.
- Record score and validation state in the matrix after each gate run.
- Publish only PASS articles; never mark PUBLISHED before the MAIN commit.

## Where things live

- `config/` — machine-readable truth (facts, rubric, ownership).
- `data/content-matrix.csv` — the 2,000-row backlog and status ledger.
- `data/batches/` — generated batch manifests + locks (gitignored).
- `cam-nang/<category>/` — future published article directory.
- `scripts/` — validator, scorer, cannibalization checker, matrix validator,
  batch runner, writer interface, category-index and sitemap generators.
- `tests/` — unit tests + fixtures proving gate and batch behavior.
- `reports/article-quality/`, `reports/batches/` — generated reports
  (gitignored except `.gitkeep`).
