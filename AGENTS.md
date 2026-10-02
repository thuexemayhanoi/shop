# AGENTS.md — Operating Manual for AI Agents (ENTRY POINT)

This file is the single entry point for any AI agent (or human operator)
working on `thuexemayhanoi/shop`. Read it first, then follow the routing
table below. Every procedure lives in `docs/` and follows the same skeleton:
Objective → Preconditions → Canonical data sources → Steps → Verified
commands → Expected results → PASS/FAIL criteria → Error handling →
Checkpoint → Rollback.

**Only commands listed in the procedures as "verified" may be assumed to
work. Anything else must be tested before use and documented in the same
change.**

## 1. Non-negotiable hard rules (apply to every procedure)

- Publish ONLY gate-PASS articles. Never publish drafts, never expose
  unpublished article files at their public URL (`_drafts/` exists for
  exactly this reason).
- Never rewrite PUBLISHED articles (content, URL, slug, canonical, schema
  can be fixed forward only through an explicit repair decision, never
  silently).
- Never invent business facts: prices, deposit, hours, phone, locations,
  policies come ONLY from `config/business-facts.json` (trusted section)
  and owner confirmation. Never invent legal facts: fines, licence rules
  and laws must cite approved official sources (`config/source-policy.json`).
- Never claim "free", "guaranteed", "24/7", fixed promotions or exact
  availability without owner verification.
- Never weaken QA tests, the rubric, or the matrix invariants to make a
  gate pass. Never bulk-flip row statuses by hand-editing the ledger.
- No autonomous AI writer or AI-generation cron may run inside GitHub
  Actions: GitHub Actions must not contain an AI writer or AI API
  keys/secrets for article generation. The deterministic Factory
  Operator / QA / publish tooling stays in GitHub. The WRITER is an
  external AI agent or human. Scheduling that external writer/operator
  outside GitHub is ALLOWED, but every scheduled invocation must resume
  repository truth and obey the canonical lock, transaction, QA,
  publish and checkpoint contract. Two writers must never mutate the
  factory concurrently.
- Kill switch: `config/content-factory.json` `enabled=false` pauses the
  factory. Check it before claiming rows.
- Do not delete articles, change slugs, or add noindex to published pages.

## 2. Routing table — where each procedure lives

| Task | Read this | Status |
|---|---|---|
| Read orientation, site architecture, chatbot/nav rules | `README.md` | current |
| Factory lifecycle, states, URL architecture, locks | `docs/CONTENT-FACTORY.md` | current |
| Article writing rules (length, links, sources, shell) | `docs/ARTICLE-RULES.md` | current |
| Protected search intents | `docs/SEO-OWNERSHIP.md` | current |
| **Write + publish an article chunk (operator loop)** | `docs/PROC-PUBLISH.md` | implemented |
| **Technical SEO audit (live vs source)** | `docs/PROC-SEO-TECHNICAL.md` | implemented |
| **Content SEO review (intent, structure, links, sources)** | `docs/PROC-SEO-CONTENT.md` | implemented |
| **Local SEO & business data** | `docs/PROC-LOCAL-SEO-DATA.md` | implemented |
| **Structured data & GEO** | `docs/PROC-SCHEMA-GEO.md` | partially — see TODOs inside |
| **UX, mobile, accessibility, performance** | `docs/PROC-UX-PERF-A11Y.md` | partially — see TODOs inside |
| **Scoring, evidence & audit reports** | `docs/PROC-SCORING-EVIDENCE.md` | implemented |
| **Master fix matrix (open issues)** | `docs/MASTER-FIX-MATRIX.md` | living document |
| **Post-publish monitoring** | `docs/PROC-POST-PUBLISH.md` | partially — Search Console NOT connected |
| Chatbot technical docs | `docs/MOTOAI.md` | current |
| Fact-safety cleanup history | `docs/fact-safety-pass-3.md` | historical |

Machine-readable truth (never contradict, never hand-edit):

- `config/business-facts.json` — prices, deposit, phone, hours, policies
- `config/article-rubric.json` — the 100-point article rubric
- `config/seo-ownership.json` — protected commercial intents
- `config/source-policy.json` — approved official source domains
- `config/site.json` — site URL / base path `/shop`
- `data/content-matrix.csv` — the article ledger (PLANNED/WRITING/…/PUBLISHED)
- `data/content-taxonomy.json` + `data/content-taxonomy-map.csv` — taxonomy
- `reports/batches/factory-progress.json` — deterministic progress ledger
  (read progress numbers from these files; NEVER hardcode counts)
- `reports/article-quality/qa-evidence.json` — reusable QA verdicts
  (machine-managed; a verdict is reusable ONLY while the article content
  hash, the QA config hash and `article_lib.VALIDATOR_VERSION` all match;
  never hand-edit, never trust stale evidence for changed content).
  The file is gitignored (runtime artifact): in CI it round-trips as the
  `qa-evidence` workflow artifact (restored before every gate, saved
  non-fatally after it), so reuse persists across runs.

## 2b. QA scope contract (workflow hardening 2026-09-28)

The Article Quality Gate (`scripts/qa_scope.py` decides) is SCOPED:

- ALWAYS-GLOBAL on every run: unit tests, matrix invariants,
  `factory.mjs --consistency` (matrix/hub/sitemap coherence, duplicate
  URLs, unpublished leaks), lock/transaction integrity, publish hash-QA.
- CHANGED-ONLY article scanning: only new/modified drafts and modified
  production articles are re-validated per run. Unchanged articles are
  skipped unless their QA evidence no longer matches.
- FULL scan (every production article, drafts included) when ANY
  globally-affecting file changes: `scripts/**`, `tests/**`, the rubric,
  business facts, ownership, source policy, site config, shared
  templates (`_includes/**`, `_snippets/**`, `assets/css/**`), the
  article rules doc, or the gate workflows themselves.
- FULL also runs: manually via Article Quality Gate `workflow_dispatch`,
  and at batch completion (the factory operator publish step detects a
  terminal batch and runs a FULL evidence-aware audit).
- Publish scope: the publish gate re-validates ONLY the freshly
  published articles (evidence is never reused for them); the shared
  article shell is applied only to the files promoted by the same
  transaction.
- Quality thresholds are NEVER weakened or skipped by scoping: the same
  validate/cannibalization/score tools run per checked article.

## 2c. State sync after QA (never hand-edited counts)

After QA and after EVERY factory mutation, `reports/batches/
factory-progress.json` and the batch report regenerate from the current
matrix (`run_article_batch.py` QA path and `factory.mjs` publish both do
this). PASS/WRITING/REPAIR/PUBLISHED counts in the two reports must
always agree; if they ever disagree, treat the matrix as truth, report
drift and repair — never patch numbers by hand. Both files record the
commit they were generated from; consumers must read state pinned to a
commit SHA (for example the raw blob at that SHA, or the `matrix_commit_sha`
/ `published_commit_sha` fields) instead of trusting a possibly stale
local copy of a report.

## 2d. Operator coordination (one command at a time)

- Exactly ONE operator-command stream: never push a new
  `data/batches/operator-command.json` while a previous command has not
  finished. Send a command → wait for the `factory-operator: <op>`
  result commit on MAIN → only then send the next command.
- Never push drafts/reports/matrix changes while the operator run is
  committing/pushing (the operator workflow aborts superseded command
  files and queues on the `article-batch-production` concurrency group).
- Pages builds: GitHub Pages (branch-based) rebuilds the site on every
  push to MAIN — pushes that contain only drafts, operator commands or
  reports still trigger a Pages build. This cannot be path-filtered for
  branch-based Pages and is expected behaviour; do not "fix" it by
  editing unrelated workflow paths.

## 3. Fast path — continue the article run (summary; details in PROC-PUBLISH.md)

Definitions: a BATCH is a canonical group of 50 matrix rows (2,000
production articles = 40 batches x 50). A CHUNK is a small resumable
writing/QA/publish unit INSIDE the active batch, normally 5-10 rows.
The external writer does NOT need to write all 50 immediately. On every
invocation: inspect repository truth, resume unfinished work first,
then take the next 5-10 unfinished WRITING rows. Never start a fresh
batch merely because a new invocation begins; transition to the next
batch only when the current batch reaches its legitimate terminal
state per the factory contract. If an interruption leaves a chunk
partly done, keep the completed work and RECOVER -> RESUME unfinished
rows -> VERIFY -> continue.

1. Fetch current MAIN; verify the matrix state and the kill switch.
2. Recover any pending transaction, check the writer lock.
3. If the active batch has no exported row manifests yet, push operator
   command `{"op":"prepare-next"}`; otherwise read the existing manifests
   under `reports/batches/<BATCH>/rows/`.
4. Write drafts into `_drafts/<output_path>` (5–10 per chunk).
   New articles target **1,600–3,000 main-content Vietnamese words**
   (choose by search intent; already-published articles keep the legacy
   1,600–2,000 band — see `docs/ARTICLE-RULES.md`).
5. Local gate each draft: `python3 scripts/score_article.py <draft>`.
6. Push drafts, run operator `{"op":"qa","batch":"<BATCH>"}`.
7. Publish PASS rows: operator `{"op":"publish","batch":"<BATCH>","ids":"…","date":"<date>"}`.
8. Live-verify URLs + sitemap (curl evidence). Report per chunk.
9. Repeat at a chunk boundary while budget remains; otherwise save the
   checkpoint and stop. Give exact resume commands in the report.

## 4. Acceptance checklist (khi nào được tiếp tục / phải sửa / phải dừng)

Continue the run (next chunk) ONLY if ALL of these hold:

- [ ] All gate suites green: `python3 -m unittest discover tests` → all
      current tests pass, `node --test tests/js/factory.test.mjs`
      → all pass, `node scripts/js/factory.mjs --consistency` → CONSISTENCY OK,
      `python3 scripts/validate_content_matrix.py` → valid matrix.
- [ ] The previous chunk's articles are live: HTTP 200, byte-identical to
      repo, present in `sitemap.xml`, drafts gone (404).
- [ ] Matrix statuses match reality (PASS rows published, no WRITING row
      has a file at its public path).
- [ ] CI on the pushed HEAD is green (Article Quality Gate + Pages deploy).
      Draft-only pushes run the gate in CHANGED scope; engine/rubric/config
      changes force the FULL scan automatically.

Repair (stop advancing, fix, re-verify) when any of these is true:

- [ ] Any QA/REVIEW/FAIL row in the current chunk (bounded repair, max 3
      attempts per row, then BLOCKED with reason).
- [ ] `--consistency` reports drift (leaked unpublished row, stale hub,
      sitemap mismatch).
- [ ] CI red on HEAD, or a pushed file's raw bytes differ from local.

Hard stop (do not continue, report to owner) when:

- [ ] The publish transaction was interrupted and `--recover` cannot finish
      it cleanly.
- [ ] A writer lock is held by another fresh session.
- [ ] A business/legal fact cannot be verified from approved sources —
      mark the row BLOCKED, never guess.
- [ ] Evidence for a live claim is missing (e.g. cannot curl-verify after
      publish). Do not report success without evidence; state NOT VERIFIED.

## 5. Reporting discipline

Report after every chunk: written / PASS / PUBLISHED / REPAIR / BLOCKED,
progress read from `reports/batches/factory-progress.json` (not from
memory), commits pushed, CI + Pages results, live-verify evidence
(HTTP status + byte comparison), and the exact resume commands if stopping.
Mark claims VERIFIED only with evidence (curl output, CI run, matrix row);
everything else must be labeled NOT VERIFIED or TODO.

## SEO Maintenance layer (hardening, read-only by contract)

FACTORY OWNS: content production, `data/content-matrix.csv`, the writer
checkpoint, batch state, `_drafts/`, publication transactions, locks.

SEO/MAINTENANCE OWNS: read-only audits (`scripts/seo/seo_audit.py`),
the Fix Matrix (`reports/seo/fix-matrix.*`), the regression baseline
(`reports/seo/baseline.json`), checker results, and isolated safe-fix PRs.

Non-negotiable rules for the SEO/maintenance layer:

- repo truth > memory > old reports. Always re-read current repo state.
- Never restart the factory casually, never skip an unfinished batch,
  never rewrite PUBLISHED content without a separately verified defect.
- Never weaken QA, never baseline a real defect to make CI green
  (`scripts/seo/seo_regression.py` refuses baselining while P0/P1 exist).
- Never auto-change business facts, prices, opening hours or legal content.
- Never mutate factory state (matrix rows, checkpoint, transactions,
  locks, drafts) from SEO maintenance. Checker workflows are read-only
  with respect to factory state and use their own concurrency groups
  (`seo-readonly-checks`, `lighthouse-readonly`, `lychee-readonly`,
  `codeql-readonly`) that can never cancel the production publisher.
- Safe auto-fix (`scripts/seo/safe_fix.py`) is EXTREMELY NARROW and
  allowlisted: canonical '/shop/shop' repair, root-relative
  self-canonical absolutization, sitemap duplicate dedup, `_config.yml`
  exclude additions. Everything else is REVIEW / Fix Matrix / issue.
- All fixes go through an isolated PR verified by
  `scripts/seo/pr_verify.py` (audit + fix matrix + regression guard on
  the EXACT candidate tree) plus the full factory test suite.
