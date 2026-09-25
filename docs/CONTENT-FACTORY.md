# Content Factory

Infrastructure that produces up to 2,000 informational articles behind a
deterministic quality gate, in 40 batches of exactly 50 articles. The plan
(2,000 rows) is complete; production article bodies are NOT written yet and
must come from an authorized AI writer or a human author — never templates.

## Production article standard (final)

Every production article must satisfy ALL of:

- **1,600–2,000 Vietnamese words** of main editorial content
  (1,200–1,599 / 2,001–2,300 = REVIEW; <1,200 / >2,300 = FAIL;
  body-only word counting: article/main container minus nav, header,
  footer, breadcrumb, chatbot, scripts, styles; padding/filler detected
  separately)
- **exactly 1 primary search intent**
- **exactly 1 H1**, self canonical, unique title + meta description
- **3–5 contextual internal links** in the editorial body, including the
  required **parent category hub** link; max 1 commercial landing-page link
- descriptive, diverse anchors; no generic or repeated exact-match anchors
- Article schema, breadcrumb, author/date metadata, related content
- source section when `requires_sources=true`
- full QA: PASS (score ≥ 90, no critical failures, no review flags) BEFORE
  publication — see docs/ARTICLE-RULES.md for the full standard

## Scale architecture

- **2,000 production articles** planned in `data/content-matrix.csv`
  (KN 350 / AT 300 / XM 350 / DL 400 / CD 300 / HD 300).
- **40 batches** (`BATCH-001` … `BATCH-040`), **exactly 50 articles each**.
- 8 SAMPLE fixture rows support the test suite and never count as production.
- Verify anytime: `python3 scripts/validate_content_matrix.py`.

## Article URL architecture

This is a GitHub Pages **project site**: the public base path is `/shop/`
(machine-readable source: `config/site.json` — `site_url` =
`https://thuexemayhanoi.github.io/shop`). All generated URLs must resolve
under `/shop/`; bare-root links like `href="/cam-nang/..."` are forbidden
(they would resolve against the host root and 404).

Production articles live at `cam-nang/<category-dir>/<slug>.html` with
`slug = <prefix>-<NNNN>-<slugified-title>` (public URL:
`https://thuexemayhanoi.github.io/shop/cam-nang/kinh-nghiem/kn-0017-….html`).
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
  manifest (writer_context with the full production standard — target word
  range, contextual-link rules, parent hub, allowed targets, commercial
  limit, business facts, protected intents — plus per-article fields) that
  an external AI writer (e.g. a Mistral agent) consumes.
- **No writer configured → no durable claims**: with
  WRITER_NOT_CONFIGURED the manifest is still produced but the matrix rows
  stay PLANNED (nothing pretends content was written). Rows are claimed
  WRITING only when a real writer provider is configured.
- **State persistence**: GitHub Actions runner-local changes are NOT
  persistent unless committed. `data/content-matrix.csv` on MAIN is the
  single durable ledger; the production flow persists PLANNED → WRITING →
  QA → PASS → PUBLISHED transitions to MAIN once a real writer is connected.
- Manifests/locks are gitignored; `data/content-matrix.csv` stays the ledger.
- The batch size is capped at 50 — a larger `--batch-size` is clamped, never
  silently exceeded.
- **Resume safety**: PASS/PUBLISHED rows are never re-claimed or rewritten;
  interrupted batches continue from the unfinished rows. The matrix state is
  the source of truth.
- **Concurrency lock**: `data/batches/BATCH-XXX.lock` (24h TTL) prevents two
  runners on the SAME machine/workspace from claiming the same batch. Inside
  GitHub Actions this local lock is NOT sufficient (separate runners have
  separate workspaces and cannot see each other's lock files), so the
  `article-batch.yml` workflow additionally enforces a GLOBAL
  `article-batch-production` concurrency group with
  `cancel-in-progress: false` — only one batch run may execute at a time,
  across all batch IDs and future scheduled runs.
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

- `scripts/generate_category_pages.py` — deterministic category pagination.
  The six ROOT hub pages (`kinhnghiem.html`, `antoan.html`, `xemay.html`,
  `dulich.html`, `cungduong.html`, `hoidap.html`) ARE page 1 of each
  category; no competing `cam-nang/<category>/index.html` is ever generated.
  The first 50 PUBLISHED article cards are injected into each root hub via
  an idempotent `<!-- ARTICLE-LIST:START/END -->` block (manual hub content
  outside the delimiters is never touched). When a category has MORE than 50
  PUBLISHED articles, page 2+ goes to `cam-nang/<category>/page-2.html`,
  `page-3.html`, … (50 articles per page), each linking back to the root hub.
  Empty pagination pages are never committed. All generated
  links carry the GitHub Pages base path from `config/site.json`
  (`/shop/cam-nang/…`, `/shop/kinhnghiem.html`); bare-root
  `href="/cam-nang/…"` links are forbidden. The page skeleton exposes
  header/footer partial mount points so the existing site design system can
  be included later without redesign.
- `scripts/generate_sitemap.py` — merges the current `sitemap.xml` with
  PUBLISHED production articles only. LEGACY (non-factory) URLs are always
  preserved; factory article URLs (namespace
  `site_url + "/cam-nang/"`) are REBUILT from the CURRENT matrix on every
  generation, so stale article URLs (e.g. a row later changed to BLOCKED)
  are removed instead of accumulating. Article URLs are built from
  `config/site.json` → `site_url`
  (`https://thuexemayhanoi.github.io/shop/cam-nang/<category>/<slug>.html`),
  never from the bare host origin. No SAMPLEs, no
  PLANNED/WRITING/REVIEW/FAIL/BLOCKED, no duplicates, valid XML.
  `--check` verifies freshness.

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

## Production writer pipeline (2026-09-25)

The factory now has a real, end-to-end writer + repair + publish pipeline:

- **Provider registry** (`scripts/providers/`): `WRITER_PROVIDER=mistral`
  selects `scripts/providers/mistral_writer.py` (Mistral chat completions
  API, stdlib-only, timeout + bounded exponential-backoff retries, clear
  error classification). Credentials come from the environment / GitHub
  Actions Secrets ONLY (`MISTRAL_API_KEY`) — never committed.
- **Safe stop**: no provider -> `WRITER_NOT_CONFIGURED` (exit 5); provider
  without key -> `WRITER_SECRET_MISSING` (exit 6). Rows stay PLANNED.
  Content is never fabricated and states are never faked.
- **Per-article lifecycle** (`scripts/run_article_batch.py`):
  PLANNED -> WRITING -> QA -> (REPAIR -> QA) x max 3 -> PASS / FAIL /
  BLOCKED / REVIEW. One bad article never blocks the other 49.
- **Writer context** (`build_writer_context`): article identity, keywords,
  intent, output path, parent hub, protected intents, trusted business
  facts (unverified owner facts are never sent), approved prices,
  unapproved-model policy, deposit wording, legal-source requirements,
  link rules (3-5 contextual, max 1 commercial), 1600-2000 word target,
  site base URL /shop, neighboring matrix topics for cannibalization
  awareness.
- **Repair loop**: REVIEW sends the original article + exact QA report
  back to the writer; only the identified problems are repaired; after 3
  failed attempts the article is BLOCKED and never published. FAIL is
  never auto-published.
- **Crash recovery**: PASS/PUBLISHED never rewritten; WRITING/QA/REPAIR
  rows resume safely (files kept, missing files re-claimed); no duplicate
  IDs or output files; durable state lives in the matrix committed to MAIN.
- **Cost guard**: sequential by default (`--concurrency` 1-3); provider
  failures >= 5 and > 30% stop NEW generation while preserving results.
- **Pilot mode**: `--pilot` (or workflow input `pilot=true`) = BATCH-001
  only, max 50, no chaining.
- **Kill switch**: `config/content-factory.json` — `enabled=false` pauses
  everything; `scheduled_runs_enabled=false` pauses cron runs only.
- **Partial publishing** (`.github/workflows/article-batch.yml`,
  `permissions: contents: write`): only PASS articles are committed with
  the matrix; `--mark-published` flips rows only AFTER the push to MAIN
  succeeds; category hubs + sitemap are regenerated from PUBLISHED rows.
  Batch reports `reports/batches/BATCH-XXX.{json,md}` are committed as the
  audit trail.
- **Scheduling**: NO CRON yet. A daily cron may only be added after a real
  BATCH-001 pilot with a configured writer is proven stable; it must use
  `--next`, check the kill switch, resume active batches before starting
  new ones, and report FACTORY_COMPLETE without changes when done.

## Batch reports

`reports/batches/BATCH-XXX.json` + `.md`: batch id, timestamps, provider,
requested/written/pass/published/review/repair/fail/blocked/provider
errors, score stats, commit SHA, and per-article outcome detail.
