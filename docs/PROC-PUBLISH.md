# PROC-PUBLISH — Write & Publish an Article Chunk

## Objective

Produce 5–10 gate-PASS articles per chunk inside the active batch
(max 50 per batch) and publish them to the live site WITHOUT ever exposing
unpublished drafts. The external AI agent is the writer; GitHub Actions
("Factory Publish, event-driven write-ahead queue") consumes the
writer's pushes (claim → QA → publish inside one run); deterministic
scripts are the gate.

Definitions (batch vs chunk — not contradictory):

- **BATCH** = canonical group of 50 matrix rows (2,000 production
  articles = 40 batches x 50). `prepare-next` claims/exports the
  canonical active batch per the existing implementation.
- **CHUNK** = small resumable writing/QA/publish unit INSIDE the active
  batch, normally 5-10 rows. The external writer does NOT need to
  write all 50 immediately.
- Correct operating model per invocation: inspect repository truth ->
  resume unfinished work first -> select the next 5-10 unfinished
  WRITING rows -> write drafts -> local QA -> official QA -> repair if
  necessary -> publish PASS -> verify -> checkpoint -> repeat.
- If an interruption leaves a chunk only partly done: KEEP completed
  work; the next invocation runs RECOVER -> RESUME unfinished rows ->
  VERIFY -> continues the remaining active batch. Never start a fresh
  batch merely because a new scheduled invocation begins; transition
  only after the current batch reaches its legitimate terminal state
  per the factory contract.

## Preconditions

- Current MAIN checkout; remote HEAD verified before editing.
- `config/content-factory.json` → `enabled: true` (kill switch check).
- No pending transaction: `node scripts/js/factory.mjs --recover` → clean.
- Writer lock free: `python3 scripts/run_article_batch.py
  --writer-lock-status` → `{"lock": null, ...}` (verified command).
- Read `README.md`, `docs/CONTENT-FACTORY.md`, `docs/ARTICLE-RULES.md`,
  `docs/SEO-OWNERSHIP.md`, `AGENTS.md` hard rules.

## Canonical data sources

| Need | Source |
|---|---|
| Row scope, keywords, output paths, draft paths, dates, taxonomy, link targets | `reports/batches/<BATCH>/rows/<ID>.json` (exported by `run_article_batch.py --claim-ids`) |
| Ledger state | `data/content-matrix.csv` (read-only for the writer; NEVER hand-edit) |
| Business facts | `config/business-facts.json` (trusted section only) |
| Legal sources | `config/source-policy.json` (approved domains, min 1 URL for `requires_sources=true`) |
| Protected intents | `config/seo-ownership.json` |
| Article shell (footer/chatbot) | `_snippets/footer-compact.html` + chatbot snippet per `docs/ARTICLE-RULES.md` |

## Steps (verified push-driven loop)

Push discipline (hard rules, see AGENTS.md §2c–2d): there is NO
operator command file. One push queues 2–10 article files
(`queue_max_push`); the factory-publish run consumes the queue as
deterministic pairs of 2 (claim → QA → publish inside the same run)
under the `factory-publish` concurrency group. After every publish run
the queue runner regenerates `factory-progress.json` and the batch
report from the current matrix; always read them pinned to a commit SHA
(`source_head_sha` — the schema-2 INPUT-tree sha — plus the durable
`published_commit_sha` audit trail), never from a stale
local copy.

1. **Claim the exact rows you will write** —
   `python3 scripts/run_article_batch.py --batch <BATCH> --claim-ids
   --ids ID1,ID2,...` claims exactly those PLANNED rows → WRITING and
   exports per-row manifests. Claim only what this push will queue
   (2–10 rows); the rest of the batch stays PLANNED.
2. **Write drafts** at the manifest's `draft_output_path`
   (`_drafts/<output_path>`) — NEVER at the public `output_path`.
   Follow `docs/ARTICLE-RULES.md`: 1,500–5,000 words main content for
   new articles (choose by search intent; already-published articles
   keep the legacy 1,600–2,000 band), 1 H1,
   self-canonical = `canonical_url` from the manifest, Article +
   BreadcrumbList JSON-LD, `datePublished` = manifest `date_published`
   (never `planned_date`), 3–8 contextual internal links (parent hub
   required; child hub when the manifest's `taxonomy.child_hub` is
   non-empty; ≤1 commercial), "Nguồn tham khảo" section with ≥1 approved
   official URL for `requires_sources=true` rows (verify via web research
   first; if unverifiable → leave unwritten or BLOCK, never guess).
3. **Local pre-gate** (verified commands, run in the repo root):

   ```bash
   python3 scripts/score_article.py _drafts/cam-nang/<cat>/<slug>.html
   ```

   Repeat until `status: PASS` (exit 0). Also available:
   `python3 scripts/validate_article.py <file>` (exit 0 = valid) and
   `python3 scripts/check_cannibalization.py <file>` (exit 0 = no conflict).
   Check hard invariants before pushing: slug == manifest slug, canonical ==
   manifest `canonical_url`, meta date == manifest `date_published`.
4. **Push drafts** (one commit, 2–10 files under `_drafts/` — the
   write-ahead queue cap). Jekyll never deploys underscore directories
   (live-proven: drafts return 404). The factory-publish workflow
   consumes the queue by itself: pairs of 2 → exact-ID claim → scoped
   QA (validator + cannibalization + scorer + source gate + business
   facts) → transactional publish of PASS, all inside the same run.
5. **Repair loop** — no command to re-run: edit the DRAFT, re-run the
   local gate, push again. The queue runner re-QAs exactly the touched
   rows (touched PASS rows publish directly, never re-QA'd).
6. **Bounded repair** — max 3 meaningful repairs per row
   (factual → legal/source → schema → structure → style order);
   exhausted → the row becomes BLOCKED with the reason recorded. One
   bad row never blocks the queue's PASS rows. `FAIL→REPAIR` requeue
   uses `scripts/requeue_rows.py` (do not hand-edit the matrix).
7. **Publish PASS rows — automatic.** Each pair publishes inside the
   same run: `factory.mjs --publish --dry-run` → real `--publish`
   (promotes each QA-passed draft `_drafts/<output_path>` → public
   `output_path` inside one transaction, flips rows PUBLISHED, regenerates
   category hubs, child hubs, sitemap, batch report) → `--consistency` →
   generator freshness checks. A failed pair never rolls back published
   pairs; an interrupted run is recovered by the next publish run
   (`factory.mjs --recover` + `--consistency`).
8. **Live verification** (verified command patterns):

   ```bash
   curl -s -o /dev/null -w "%{http_code}" https://thuexemayhanoi.github.io/shop/cam-nang/<cat>/<slug>.html   # expect 200
   curl -s https://thuexemayhanoi.github.io/shop/cam-nang/<cat>/<slug>.html | md5sum   # compare with local file
   curl -s https://thuexemayhanoi.github.io/shop/sitemap.xml | grep -c "<loc>"        # count must match --consistency output
   curl -s -o /dev/null -w "%{http_code}" https://thuexemayhanoi.github.io/shop/_drafts/cam-nang/<cat>/<slug>.html   # expect 404
   ```

9. **Checkpoint & report** — chunk boundary: matrix statuses, scores,
   progress (from `reports/batches/factory-progress.json`), commits, CI +
   Pages results, live evidence, resume commands.

## Expected results

- Chunk of 5–10: drafts written → all PASS at score ≥ 75 (rubric PASS.min) → PUBLISHED at
  their public URLs, in sitemap, listed on parent + child hubs.
- Drafts removed from the repo by the publish transaction (raw 404).
- CI (Article Quality Gate) and the Pages build both green on HEAD.

## PASS/FAIL criteria

- PASS chunk: every intended row PUBLISHED with live 200 + byte-identical
  content + sitemap entry + green CI. No leaked drafts.
- FAIL chunk (block the chain): any draft reachable publicly, canonical or
  slug mismatch, missing sitemap entry, red CI, or consistency drift —
  stop, repair, re-verify; do not start the next chunk with an open defect.

## Error handling

| Symptom | Action |
|---|---|
| Local scorer REVIEW (score 70–74 or review flags) | Fix per its report (word count inside the target band — 1,500–5,000 for new articles, 1,600–2,000 legacy band for published rows — link count 3–8, parent hub, sources…) and re-score. |
| `canonical inconsistent with slug` / `article not in content matrix` | Draft filename must equal the manifest slug exactly; canonical must equal the manifest `canonical_url`. |
| QA workflow reports FAIL/REVIEW rows | Bounded repair (max 3), else BLOCKED with reason. Never publish a non-PASS row. |
| Publish run interrupted | `node scripts/js/factory.mjs --recover` finishes/verifies the transaction; the next publish run also recovers first. Never mutate while a marker is pending. |
| Writer lock held by a fresh session | Abort cleanly (exit 2). Never two writers on one batch. |
| Pushed bytes differ from local (integrity) | Re-fetch MAIN, byte-compare, fix from local truth; suspect transport truncation — re-push from a full checkout. |

## Checkpoint

- Durable state: `data/content-matrix.csv` on MAIN (statuses + scores).
- Chunk state: `data/batches/writer-checkpoint.json`
  (`python3 scripts/run_article_batch.py --checkpoint` prints it
  reconciled with the matrix — verified command; THE MATRIX ALWAYS WINS).
- Lock: `--writer-lock-status` / `--acquire-writer-lock` /
  `--release-writer-lock` (verified: status + clean abort on foreign lock).
- Resume = repeat steps 3–9 for the next 5 unwritten WRITING rows; PASS/
  PUBLISHED rows are never re-claimed or re-QA'd.

## Rollback

- Publishing is FORWARD-ONLY by policy: no deletes, no slug changes, no
  noindex on published articles. A published defect is fixed by a new
  commit (repair-in-place), never by removal.
- Interrupted publish → `--recover` (two-phase commit + recovery marker
  under `data/batches/txn/`); mutations are refused until recovered.
- Wrongly claimed batch/rows → owner decision (requeue via
  `scripts/requeue_rows.py`); the agent must not silently renumber or reset.
- Factory-wide stop → set `config/content-factory.json` `enabled=false`
  (kill switch) and report.
