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

## Node fallback tooling (publish without Python)

`scripts/js/` is a dependency-free Node >= 18 fallback for the ledger /
publish operations, so the interactive AI runtime (which usually has
Node but not Python) is never blocked again:

- `scripts/js/ledger.mjs` — byte-preserving RFC 4180 ledger reader/writer
  for `data/content-matrix.csv`. Reads the full ~990 KB file in one pass,
  keeps the RAW text of every row and re-emits unedited rows verbatim
  (unrelated rows/columns preserved byte-semantically); edited rows are
  re-serialized exactly like Python `csv` (QUOTE_MINIMAL, CRLF).
- `scripts/js/factory.mjs` — the transactional CLI:
  - `--qa-record "ID=SCORE:OUTCOME,..."` — record external QA results in
    the ledger with full state-machine validation (WRITING→QA/PASS/
    REVIEW/FAIL, repair budget, PASS requires score ≥ 90)
  - `--publish "ID,ID"` — PASS→PUBLISHED only (file must exist, one batch
    only, score ≥ 90), then regenerates hub ARTICLE-LIST blocks,
    sitemap.xml, factory-progress.json and the batch report
  - `--rebuild-report BATCH` — rewrite the CUMULATIVE batch report from
    current matrix truth (all reserved members, matrix-derived counts)
  - `--recover` — finish/verify an interrupted multi-file transaction
  - `--consistency` — verify matrix/hubs/sitemap agreement, no writes
  - `--dry-run`, `--date`, `--repo`, `--expect-rows` options
  - every output is computed and validated BEFORE the first write; writes
    are a two-phase commit (all tmp files first, then renames). Because
    true cross-file atomicity is impossible on a plain filesystem, the
    publish transaction also writes a recovery marker under
    `data/batches/txn/` (gitignored) with the sha256 of each file's
    pre/post content plus the planned content itself; an interruption
    between renames is recovered deterministically by `--recover`
    (mutations are refused while a marker is pending)
  - batch reports are CUMULATIVE (all reserved members of the batch,
    counts derived from the matrix — never just the latest run's rows);
    `completed_batches` in factory-progress.json is derived from matrix
    state: a batch counts as complete only when every reserved row is
    terminal (PUBLISHED/FAIL/BLOCKED)
- `tests/js/factory.test.mjs` — `node --test` suite (round-trip on the
  real ledger, byte-preservation, state machine, dry-run, full publish
  transaction on a sandbox, interrupted-run rollback, drift detection).

The Node generators are byte-equal to the canonical Python ones
(generate_category_pages.py / generate_sitemap.py are no-ops after a
Node publish). Python scripts stay canonical; the Node tool is the
fallback for restricted runtimes and is cross-validated by CI
(`.github/workflows/article-quality.yml` runs the Node tests and
`--consistency` on every push; `.github/workflows/factory-publish-verify.yml`
is a manually dispatchable, read-only end-to-end verification with both
Python and Node installed).

## Batch orchestration

`scripts/run_article_batch.py` orchestrates ONE batch of at most 50 articles.

```bash
# claim up to 50 PLANNED rows, mark them WRITING, write the agent manifest
python3 scripts/run_article_batch.py --batch BATCH-001 --prepare-agent
# or: resume the active unfinished batch, else the first with PLANNED rows
python3 scripts/run_article_batch.py --next --prepare-agent

# THE EXTERNAL WRITER (the Mistral agent, or a human) now writes the
# article files itself at each row's output_path, per docs/ARTICLE-RULES.md

# deterministic QA of the batch's written files (validate + cannibalization
# + scorer); REVIEW rows get a bounded repair budget
python3 scripts/run_article_batch.py --batch BATCH-001 --qa

# publish scope: list exactly this batch's PASS files; push them to MAIN
python3 scripts/run_article_batch.py --batch BATCH-001 --publish

# after the push reached remote MAIN: flip PASS rows to PUBLISHED
python3 scripts/run_article_batch.py --batch BATCH-001 --mark-published
```

- `--prepare-agent` writes `data/batches/BATCH-XXX.json`, a machine-readable
  manifest (per-article writer_context with the full production standard —
  word_standard 1600-2000, link_standard 3-5 contextual links + parent hub +
  max 1 commercial, protected intents, business facts policy, canonical_url,
  ACTUAL date_published, neighbor topics) that the external writer consumes.
- **No API, no secrets**: the writer is the Mistral agent (or a human)
  operating this repository directly. There is no provider module, no
  MISTRAL_API_KEY and no GitHub secret anywhere in the flow.
- **State persistence**: the agent works on a checkout and commits
  transitions to MAIN. `data/content-matrix.csv` on MAIN is the single
  durable ledger (PLANNED → WRITING → QA/REPAIR → PASS → PUBLISHED, plus
  published_date).
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
- Exit codes: 0 ok, 1 tool/config error, 2 usage/lock, 3 FAIL articles,
  4 REVIEW/BLOCKED remain, 5 WRITER_NOT_CONFIGURED (article_writer.py only).

## Writer requirement (no fake writers)

The WRITER is the external Mistral agent (or a human). The repository
deliberately contains NO AI API provider, NO credentials and NO template
content generator. `scripts/article_writer.py` is a neutral boundary:
calling `write_article()` raises `WriterNotConfigured` (exit 5) with
instructions for the agent — prepare the batch, read the manifest, write
the files at their output_path, then run --qa. Rows are never faked: if
the agent cannot write an article honestly, it stays unwritten.

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
- `.github/workflows/article-batch.yml` — `workflow_dispatch` ONLY
  (read-only helper: contents: read, no secrets). Inputs: batch_id,
  batch_size, pilot, dry_run, qa, progress. It runs the test suite and
  matrix validation, resolves the batch, dry-runs the scope, optionally
  runs deterministic --qa on the files in the checkout, and uploads
  reports as artifacts. It NEVER writes articles, NEVER pushes, NEVER
  claims rows (no --prepare-agent / --publish / --mark-published in CI).
- **No cron anywhere, by design.** Hourly repetition belongs to the
  EXTERNAL Mistral agent operator, not to GitHub Actions. A scheduled AI
  writer must never be added to CI.

## External-agent operating model (hourly operator flow)

The Mistral agent IS the writer and the publisher; GitHub is the
deterministic planner / validator / ledger / CI.

1. Fetch CURRENT MAIN; verify the SHA before editing.
2. Run `--next --dry-run` to resolve the batch ONCE (an active unfinished
   batch is resumed before any new PLANNED batch; FAIL/BLOCKED never block).
3. `--prepare-agent` (max 50 rows) → manifest `data/batches/BATCH-XXX.json`.
4. Write each article per `docs/ARTICLE-RULES.md` at its output_path:
   1600-2000 Vietnamese words, 1 H1, self canonical, Article +
   BreadcrumbList JSON-LD, lang="vi", author "Mr Tú", datePublished = the
   manifest's date_published (ACTUAL date, never planned_date), 3-5
   contextual internal links (parent hub required, max 1 true commercial).
   requires_sources rows must cite >=1 approved official source URL
   (config/source-policy.json) verified via web research in a visible
   "Nguồn tham khảo" section; if verification is impossible, leave the
   article unwritten or BLOCK it honestly — never guess.
5. `--qa`: validator + cannibalization checker + scorer for EVERY article.
6. REVIEW → the agent repairs the file using the exact QA report and
   re-runs --qa (max 3 attempts, notes carry repair:N) → still REVIEW →
   BLOCKED (never published).
7. FAIL → stop, do not publish that article; keep the batch's PASS articles.
8. PASS, in order: `--publish` lists the PASS files → push them + the
   matrix to MAIN → verify on remote → `--mark-published` → regenerate the
   six root category hubs (generate_category_pages.py: first-50 block
   injected into the root hub; page-2+ only when a category exceeds 50
   PUBLISHED) and sitemap.xml (PUBLISHED articles only) → push hubs +
   cam-nang/ + sitemap.xml → write the batch report +
   factory-progress.json.
   PYTHON-LESS RUNTIME: replace steps 8's ledger flip + hub/sitemap/report
   regeneration with one atomic Node transaction:
   `node scripts/js/factory.mjs --publish "ID,ID" --date YYYY-MM-DD`
   (dry-run first with `--dry-run`; verify with `--consistency`).
   Never hand-edit the 990 KB ledger.

## Chunked writer mode (canonical scheduled-run behavior)

The batch of 50 stays canonical; the WRITER works inside it in chunks.

- Chunk size: default 5, allowed 5–10, hard max 10 (clamped; going higher
  needs an explicit owner override).
- Chunk selection: `--next-chunk N` deterministically returns the next N
  WRITING rows (matrix order) whose article file does NOT exist yet.
  PUBLISHED/PASS rows are never re-claimed; FAIL/BLOCKED only via
  `scripts/requeue_rows.py`; REPAIR/REVIEW belong to the repair path; a
  WRITING row that already has a file goes to scoped QA, never a rewrite.
- Checkpoint: `data/batches/writer-checkpoint.json` (gitignored, schema v1):
  batch, head_at_start, chunk_size, current/completed/pending-qa/
  pending-repair/pending-publish ids, last_completed_step. On every rerun
  it is reconciled with the matrix — the MATRIX always wins.
- Writer lock: `data/batches/writer-lock.json` (gitignored, schema v1,
  120-minute TTL, session-scoped). Fresh lock held by another writer →
  abort cleanly (exit 2). Stale lock → recover only after reconciling
  matrix/HEAD truth. Release on graceful completion. This guards EXTERNAL
  writers; GitHub's `article-batch-production` concurrency group only
  guards Actions runners. Never run two writer sessions on one batch.
- Scoped QA: `--ids A,B --qa` runs the full deterministic gate
  (validate + cannibalization + scorer, business facts, source gate,
  schema, links, matrix invariants) on exactly those rows. Full-batch
  consistency runs before the first chunk, after each grouped publish and
  at batch completion.
- Grouped publish: all PASS rows of the chunk in ONE
  `factory.mjs --publish ID1,...,IDN` transaction (dry-run first, recovery
  marker, hubs + sitemap + progress regenerated once per chunk). Python
  `--publish --ids ...` prints the verified scope and the exact commands.
- Repair: unchanged budget (max 3, factual → legal/source → schema →
  structure → style; never a full rewrite for one wrong claim;
  exhausted → REVIEW/BLOCKED; independent rows continue).
- Throughput: `reports/batches/factory-throughput.json` (committed) holds
  honest tool-verified counters per batch. No estimated rates are written.

Canonical scheduled writer run:

```
A. READ HEAD (verify SHA before editing)
B. RECOVER pending transaction (factory.mjs --recover)
C. VERIFY writer lock (--writer-lock-status; acquire for this session)
D. RESUME checkpoint (--checkpoint; matrix truth wins)
E. TAKE 5 rows   (--next-chunk 5 [--time-budget-remaining MIN])
F. WRITE 5 article files (external writer only)
G. QA 5          (--ids <chunk> --qa)
H. REPAIR failed/review rows (bounded), re-run scoped QA
I. PUBLISH all PASS together (factory.mjs --publish ID,... after --dry-run)
J. CHECKPOINT    (--chunk-complete; release the writer lock)
K. CONTINUE with the next chunk while runtime budget remains
```

If no errors: continue automatically. On a blocker: record state in the
checkpoint and stop safely. Never reset the active batch on every
scheduled run; resume it.

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

## Production writer pipeline (API-free, external agent)

The factory has a real, end-to-end claim → write → QA → repair → publish
pipeline in which the Mistral agent is the writer:

- **No provider layer**: `scripts/providers/` is gone for good. There is
  no WRITER_PROVIDER, no MISTRAL_API_KEY, no API client, no GitHub secret
  and no billing path anywhere in the repository. `article_writer.py`
  only raises `WriterNotConfigured` (exit 5) — the agent writes files
  itself.
- **Per-article lifecycle** (`scripts/run_article_batch.py`):
  PLANNED → WRITING (--prepare-agent) → agent writes → --qa → PASS /
  FAIL / REVIEW → agent repairs (≤ 3, notes repair:N) → PASS | BLOCKED.
  One bad article never blocks the other 49.
- **Writer context** (`build_writer_context`, in the manifest): article
  identity, keywords, intent, output path, parent hub, protected intents,
  business facts policy (unverified owner facts never sent), legal-source
  requirements, link_standard (3-5 contextual, max 1 TRUE commercial —
  category hubs are informational, not commercial), word_standard
  (1600-2000), canonical_url, ACTUAL date_published (never the future
  planned_date), site base URL /shop, neighboring matrix topics.
- **Source policy** (`config/source-policy.json`): requires_sources rows
  must cite ≥1 approved official domain (chinhphu.vn, vanban.chinhphu.vn,
  congbao.chinhphu.vn, thutuc.gov.vn, mt.gov.vn, hanoi.gov.vn — exact or
  subdomain match) in a visible "Nguồn tham khảo" section; otherwise the
  source gate FAILS the article in --qa.
- **Repair loop**: REVIEW rows consume a bounded budget; after 3 attempts
  they are BLOCKED and never published. FAIL is never auto-published.
- **Crash recovery**: PASS/PUBLISHED never rewritten; WRITING/QA/REPAIR
  rows with existing files resume safely; file-less rows stay claimable;
  durable state lives in the matrix committed to MAIN.
- **Publish invariant order**: push PASS files + matrix → verify remote →
  --mark-published → regenerate root hubs + sitemap → push. Root hub =
  page 1 (first 50 PUBLISHED per category); page-2+ exists only above 50;
  never cam-nang/<cat>/index.html.
- **Pilot mode**: `--pilot` = BATCH-001 only, max 50, no chaining.
- **Kill switch**: `config/content-factory.json` — `enabled=false` pauses
  everything.
- **Scheduling**: NO CRON, ever, in GitHub Actions. The hourly operator
  flow above belongs to the external agent.

## Batch reports

`reports/batches/BATCH-XXX.json` + `.md`: batch id, timestamps, writer
(external-agent), processed/written/pass/published/review/repair/fail/
blocked, score stats, source-gate counts, commit SHA, and per-article
outcome detail. `reports/batches/factory-progress.json` is the global
deterministic progress ledger.
