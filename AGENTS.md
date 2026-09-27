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
- No cron, no scheduled AI writers, no new AI systems inside GitHub
  Actions. The external agent is the only writer.
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

## 3. Fast path — continue the article run (summary; details in PROC-PUBLISH.md)

1. Fetch current MAIN; verify the matrix state and the kill switch.
2. Recover any pending transaction, check the writer lock.
3. If the active batch has no exported row manifests yet, push operator
   command `{"op":"prepare-next"}`; otherwise read the existing manifests
   under `reports/batches/<BATCH>/rows/`.
4. Write drafts into `_drafts/<output_path>` (5–10 per chunk).
5. Local gate each draft: `python3 scripts/score_article.py <draft>`.
6. Push drafts, run operator `{"op":"qa","batch":"<BATCH>"}`.
7. Publish PASS rows: operator `{"op":"publish","batch":"<BATCH>","ids":"…","date":"<date>"}`.
8. Live-verify URLs + sitemap (curl evidence). Report per chunk.
9. Repeat at a chunk boundary while budget remains; otherwise save the
   checkpoint and stop. Give exact resume commands in the report.

## 4. Acceptance checklist (khi nào được tiếp tục / phải sửa / phải dừng)

Continue the run (next chunk) ONLY if ALL of these hold:

- [ ] All gate suites green: `python3 -m unittest discover tests` → OK
      (275 tests at time of writing), `node --test tests/js/factory.test.mjs`
      → all pass, `node scripts/js/factory.mjs --consistency` → CONSISTENCY OK,
      `python3 scripts/validate_content_matrix.py` → valid matrix.
- [ ] The previous chunk's articles are live: HTTP 200, byte-identical to
      repo, present in `sitemap.xml`, drafts gone (404).
- [ ] Matrix statuses match reality (PASS rows published, no WRITING row
      has a file at its public path).
- [ ] CI on the pushed HEAD is green (Article Quality Gate + Pages deploy).

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
