# Thuê Xe Máy Hà Nội — Mr Tú Motorbike Rental (thuexemayhanoi/shop)

Static site for Mr Tú Motorbike Rental in Hanoi, served via GitHub Pages at
`https://thuexemayhanoi.github.io/shop/`. This README is the ENTRY POINT for
humans and AI agents working on this repository.

**Language: nội dung tiếng Việt / tooling tiếng Anh.**

---

## 1. Project purpose

Marketing + rental site for a motorbike rental business in Hanoi, plus a
content factory (planned ~2,000 informational articles) with a deterministic
quality gate. The public site must stay fast, stable, and must never invent
business facts (prices, deposit, availability, policies).

## 2. Current public site architecture

- Pure static HTML/CSS/JS, Jekyll front-matter enabled (`---\n---`) for
  `{% include %}` partials (`_includes/`).
- Menu is rendered client-side from `CONFIG.MENU` defined in shared JS
  (`assets/js/app.js`, `app-rental.js`, `app-info.js`) and inline copies in a
  few pages. Current nav: parent categories including **Dịch vụ**, **Địa điểm**,
  **Cẩm nang** (6 children: Kinh nghiệm, An toàn, Xe máy, Du lịch, Cung đường,
  Hỏi đáp), **FAQ**.
- Shared styling via `assets/css/`. Animations (hero blur, logo spin) are
  intentionally disabled for performance — do not re-enable.
- Booking uses a static form + mailto. No backend, no database.

### Commercial landing pages (DO NOT duplicate their intent)

| Page | Primary intent |
|---|---|
| `index.html` | thuê xe máy Hà Nội |
| `phoco.html` | thuê xe máy Phố Cổ / Phố Cổ Hà Nội |
| `hoankiem.html` | thuê xe máy Hoàn Kiếm |
| `banggia.html`, `ngay.html`, `tuan.html`, `thang.html` | pricing / daily / weekly / monthly rental |
| `thutuc.html` | rental procedure |
| District pages: `tayho.html`, `badinh.html`, `caugiay.html`, `dongda.html`, `thanhxuan.html`, `haibatrung.html`, `longbien.html`, `gahn.html` | district rental intents |

### Cẩm nang structure (informational hubs)

| Hub | Category |
|---|---|
| `kinhnghiem.html` | Kinh nghiệm |
| `antoan.html` | An toàn |
| `xemay.html` | Xe máy |
| `dulich.html` | Du lịch |
| `cungduong.html` | Cung đường |
| `hoidap.html` | Hỏi đáp |

Hubs are category pages, NOT replacements for commercial landing pages.
Future articles belong to exactly ONE of these six categories. Do not create
new top-level categories without owner approval.

## 3. MotoAI production state (current MAIN)

The production chatbot is `motoai_v40_bm25plus_final.js` (MotoAI v40, BM25+).
Current production configuration on ALL pages:

```
autolearn: false
debug: false
smart.autoPriceLearn: false
```

- Prices come from `assets/js/prices.js` (`window.MotoTusPrices`) — the only
  approved price source. Auto price crawling is DISABLED and must stay
  disabled. MotoAI v39 files in the repo root are legacy, unused; do not load
  them.
- On `index.html`, v40 is lazy-loaded only after the user taps the AI button
  (performance rule). Child pages may load it directly with the same safe
  config (`assets/js/motoai-config.js` runs first, then v40 `defer`).
- The homepage "Tìm Xe Chân Ái" Bike Matchmaker is a separate tool that uses
  experience, destination and height; it uses approved models only and no
  invented prices or fake confidence scores.
- Deposit-policy wording in all chatbot answers follows
  `config/business-facts.json` (2.000.000 – 5.000.000đ tùy xe và điều kiện;
  liên hệ để xác nhận). Stale claims ("2–3tr xe số / 3–5tr xe ga", "miễn cọc",
  "500k–1 triệu", guaranteed reduced deposit) are forbidden.

Detailed MotoAI technical documentation: [docs/MOTOAI.md](docs/MOTOAI.md).

## 4. Performance rules (non-negotiable)

- No background crawling on any page.
- No new infinite animations, no backdrop-filter increases, no continuous
  effects on the homepage.
- No heavy scripts loaded during page startup on `index.html`.
- Previous performance fixes (disabled hero blur, disabled logo spin) stay
  intact.

## 5. Business source-of-truth files

| File | Truth about |
|---|---|
| `config/business-facts.json` | prices, deposit policy, phone, opening hours, licence/insurance rules (machine-readable) |
| `assets/js/prices.js` | runtime prices for chatbot/calculator |
| `config/seo-ownership.json` | protected search intents per commercial page |
| `config/article-rubric.json` | scoring weights, thresholds, critical-fail rules |
| `data/content-matrix.csv` | the article backlog (status tracking) |

Never contradict these files. Anything not in them must be confirmed with
Mr Tú (phone 0816659199) before publication.

## 6. The 2,000-article content factory (batch architecture)

The plan is now concrete: **2,000 production articles** in **40 batches** of
**exactly 50 articles each**. The matrix
(`data/content-matrix.csv`) holds all 2,000 planned rows (categories: KN 350,
AT 300, XM 350, DL 400, CD 300, HD 300) plus 8 SAMPLE fixture rows that do not
count toward the total. Production articles are NOT written yet.

**Production article standard (Mr Tú Content Factory — internal editorial
standard, not a Google requirement):** every production article targets
**1,600–2,000 Vietnamese words** of main editorial content (1,200–1,599 or
2,001–2,300 → REVIEW; <1,200 or >2,300 → FAIL; padding never counts) and
exactly **3–5 contextual internal links** including the required **parent
category hub** link, with descriptive diverse anchors and at most 1
commercial landing-page link. Public URLs live under the GitHub Pages base
path `/shop/` (source: `config/site.json`); generated bare-root
`/cam-nang/...` links are forbidden.

Policy per article:

- `PASS` → publishable immediately after QA.
- `REVIEW` → repair and re-score, max **3 attempts**; still REVIEW → `BLOCKED`, do not publish.
- `FAIL` → never publish automatically. One failed article never blocks the other PASS articles in its batch.
- `PUBLISHED` is set only after the article file is actually committed to MAIN.

The WRITER is the external Mistral agent (or a human) operating this repo
directly. `scripts/article_writer.py` is a neutral boundary: asked to
write, it stops with `WRITER_NOT_CONFIGURED` (exit 5) and instructs the
agent to run `--prepare-agent`, read the manifest, write the files itself,
then run `--qa`. No API, no secrets, no provider modules; never fabricate
template content.

Lifecycle, URL architecture, resume and lock behavior:
[docs/CONTENT-FACTORY.md](docs/CONTENT-FACTORY.md). Writing rules:
[docs/ARTICLE-RULES.md](docs/ARTICLE-RULES.md). Protected intents:
[docs/SEO-OWNERSHIP.md](docs/SEO-OWNERSHIP.md).

## 7. AGENT READ ORDER — read BEFORE writing ANY article

1. `README.md` (this file)
2. `docs/CONTENT-FACTORY.md`
3. `docs/ARTICLE-RULES.md`
4. `docs/SEO-OWNERSHIP.md`
5. `config/business-facts.json`
6. `config/article-rubric.json`
7. `config/seo-ownership.json`
8. `data/content-matrix.csv`

Then select exactly ONE eligible (PLANNED) matrix row. For every production
article, an agent MUST:

1. write **1,600–2,000 useful Vietnamese words** (main content only; no filler)
2. exactly **1 primary search intent**
3. exactly **1 H1**
4. **3–5 contextual internal links** in the editorial body (nav/footer/breadcrumb links do not count)
5. include the **parent category hub** link
6. use **descriptive, diverse anchors** (no "xem thêm"/"click here"; no repeated exact-match anchors)
7. **no broken links** (only link PUBLISHED articles or same-batch articles)
8. **Article schema** (JSON-LD)
9. **breadcrumb** + author/date metadata
10. **source section** when the row has `requires_sources=true`
11. run the **full QA** (validator + cannibalization + scorer)
12. **publish only PASS**

After writing, run the quality gate. An article is NOT publishable until
final status is PASS.

## 8. Quality-gate commands

```bash
# single-article gate
python3 scripts/validate_article.py path/to/article.html
python3 scripts/check_cannibalization.py path/to/article.html
python3 scripts/score_article.py path/to/article.html
# matrix + factory
python3 scripts/validate_content_matrix.py
python3 scripts/run_article_batch.py --batch BATCH-001 --prepare-agent
python3 scripts/run_article_batch.py --batch BATCH-001 --qa
python3 scripts/run_article_batch.py --next --dry-run
python3 -m unittest discover tests
```

Pipeline per article: PLAN → WRITE → VALIDATE → SCORE → CHECK CANNIBALIZATION → FIX →
RE-SCORE → PASS → PUBLISH. The deterministic tools are the gate; an AI writer
may NEVER publish merely because it thinks the article is good.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | PASS (scorer) / valid (validator) / no conflict (cannibalization) |
| 1 | validator: hard errors |
| 2 | REVIEW required (not publishable) |
| 3 | FAIL (critical failure or score below threshold) |
| 4 | tool/config error |
| 5 | WRITER_NOT_CONFIGURED (batch runner / writer interface) |

Scoring: 100 points total. PASS = 90–100 AND no critical failures.
REVIEW = 80–89 AND no critical failures. FAIL = 0–79 OR any critical failure.

CI: `.github/workflows/article-quality.yml` runs tests and the full gate on
every PR / relevant push; REVIEW or FAIL fails CI. It also runs
`scripts/validate_content_matrix.py` (2000 rows / 40 batches x 50). The manual
batch workflow `.github/workflows/article-batch.yml` is `workflow_dispatch`
only (inputs: batch_id, batch_size default 50, hard max 50); it validates the
matrix and dry-runs the batch scope, optionally runs deterministic QA on
the files in the checkout, and uploads reports as artifacts (read-only:
contents: read). NO CRON is attached to any workflow — the hourly operator
flow belongs to the external agent, never to GitHub Actions. Legacy
special-purpose workflows `recover-phoco.yml` and `seo-phoco.yml` are
separate and must not be modified casually.

## 9. CONTENT FACTORY — CHUNKED WRITER MODE

Speed-oriented orchestration for the 2,000-article run. Quality gates,
business-fact safeguards, matrix invariants and the publish policy are
UNCHANGED — only the shape of a writer run changes.

- **Canonical batch max stays 50.** Chunking happens INSIDE a batch.
- **Writer chunk default = 5 articles; allowed 5–10; never more than 10**
  without an explicit owner override (the CLI clamps to 10).
- **One chunk loop**: resolve the active batch once → take the next 5
  unwritten WRITING rows (`--next-chunk 5`) → write all 5 files → run
  scoped QA on exactly those 5 (`--ids ... --qa`) → repair failed/review
  rows (same 3-attempt budget) → publish ALL PASS rows of the chunk in ONE
  grouped publish (`node scripts/js/factory.mjs --publish ID1,...,ID5`,
  dry-run first) → `--chunk-complete` → continue while runtime budget
  remains. Do NOT write one article and immediately publish it unless
  only one remains.
- **Resume-safe checkpoint**: `data/batches/writer-checkpoint.json`
  (schema v1) records the current chunk, pending QA/repair/publish ids.
  On rerun it is reconciled with the matrix — THE MATRIX ALWAYS WINS; a
  stale checkpoint never overrides actual row statuses. `--checkpoint`
  prints it reconciled; `--checkpoint-reset` discards it.
- **Writer lock**: `data/batches/writer-lock.json` (schema v1, 120-minute
  TTL) prevents two EXTERNAL writer sessions on the same active batch.
  A fresh lock owned by another session aborts cleanly (exit 2); a stale
  lock is recovered only after reconciling with matrix/HEAD truth. This
  complements the GitHub Actions `article-batch-production` concurrency
  group, which cannot see external sessions. **Never run two writer
  sessions on the same active batch.**
- **Scoped QA**: `--ids A,B --qa` checks exactly those rows; full-batch
  consistency still runs before the first chunk, after each grouped
  publish and at batch completion. PASS/PUBLISHED rows are never re-QA'd.
- **Grouped publish**: one `factory.mjs --publish` per chunk (transaction,
  recovery marker, hubs + sitemap + progress regenerated ONCE per chunk).
- **Repair budget unchanged**: max 3 meaningful repairs per row, repair
  order factual → legal/source → schema/metadata → structure → style;
  never rewrite a full article for one wrong claim; exhausted → REVIEW/
  BLOCKED per the canonical rules; safe independent rows always continue.
- **Runtime budget**: pass `--time-budget-remaining MIN` to `--next-chunk`;
  at ≤ 0 the run stops cleanly with the checkpoint saved, never mid-write.
- **Throughput reporting**: `reports/batches/factory-throughput.json`
  accumulates honest, tool-verified counters (articles written / QA
  checked / published, chunks, publish operations, repairs, average QA
  score). No fake benchmarks; per-hour rates are derived from real elapsed
  time only.
- **GitHub Actions never writes prose.** No AI API, no provider secrets,
  no cron: the external Mistral writer remains the sole content author.

## 10. Hard rules recap

- Never change existing public URLs, titles/H1/canonicals of commercial pages
  (especially `phoco.html`, `hoankiem.html`, `index.html`).
- Never invent prices, availability, promotions, guarantees, delivery times
  or policies.
- Never claim free/24-7/guaranteed anything unless owner-verified.
- Opening hours: 08:00–17:00 daily; do not promise service outside them.
- Motorcycles over 50cc require a valid driving licence; never encourage
  traffic-law violations.
- Insurance is the customer's responsibility; never claim included insurance.

## Node fallback tooling

If Python is unavailable, `scripts/js/factory.mjs` (Node >= 18, zero
dependencies) performs the same ledger/publish transaction safely:

    node scripts/js/factory.mjs --consistency
    node scripts/js/factory.mjs --publish "KN-0002,XM-0002,DL-0001" --dry-run
    node scripts/js/factory.mjs --publish "KN-0002,XM-0002,DL-0001"
    node scripts/js/factory.mjs --rebuild-report BATCH-001
    node scripts/js/factory.mjs --recover

- Batch reports are CUMULATIVE: every reserved member of the batch appears
  and all counts derive from the matrix rows of that batch.
- Multi-file publishes write a transaction/recovery marker under
  `data/batches/txn/` (gitignored); if a commit is interrupted, `--recover`
  finishes or verifies it (mutations are refused until recovered).
- `completed_batches` in factory-progress.json is computed from matrix
  state: a batch is complete only when every reserved row is terminal
  (PUBLISHED/FAIL/BLOCKED).

See `docs/CONTENT-FACTORY.md` and `tests/js/factory.test.mjs`.
