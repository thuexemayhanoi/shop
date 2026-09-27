# Run report 2026-09-27 — BATCH-007 publish recovery (chunk 1) and safe stop on concurrent writer

## Priority order executed
RECOVER > RESUME UNFINISHED > REPAIR > QA > PUBLISH PASS > NEW WORK.

## Recovery: publish command failed 3x (run 36334339878)
The pending `{"op":"publish"}` command for BATCH-007 chunk 1 (KN-0051, XM-0051, AT-0051, CD-0051, DL-0051, HD-0051) had failed three times (16:32Z, 16:37Z, 16:44Z) at the "Full test suites after a publish" step. The unittest op (commit 155b745 / operator 9af4243) proved the suite passed on pre-publish main, so the failure was post-publish state.

## Root cause (verified in code)
Publishing 1 article per category crossed 50 PUBLISHED/category for the first time. The Node transaction regenerated hub blocks with a "trang 2" link but never wrote `cam-nang/<cat>/page-2.html`, and the Python generator only ran with `--check`. Post-publish suite failed deterministically:
- `test_legacy_seo.test_no_broken_local_links`: broken root-hub "trang 2" link.
- `test_publish_gate.test_all_cam_nang_pages_carry_footer`: page-2 template had only a footer placeholder (no compact footer, no chatbot embed).

## Repair (single commit ecda924)
- `scripts/generate_category_pages.py`: added CHATBOT_EMBED + footer_compact(); render_page_n emits footer snippet + chatbot embed.
- `.github/workflows/factory-operator.yml`: publish path now runs the canonical Python generator in write mode before the two --check verifications.
- `tests/test_publish_gate.py`: added PaginationPageTests.test_page2_carries_footer_embed_and_hub_link.
- `docs/CONTENT-FACTORY.md`: byte-equality claim amended honestly (page-2+ written by the canonical Python generator).

CI on ecda924: build, deploy, report-build-status success; article-quality all steps success (check-runs API served stale "in_progress" data; jobs endpoint confirmed completion).

## Publish retry (command commit 0c08874 → operator transaction 380078d, 17:16:52Z)
Fresh `data/batches/operator-command.json` pushed (the unittest run had deleted it). The operator executed the transaction: 6 article files promoted to `cam-nang/<cat>/`, 6 new `page-2.html` files, hub block updates (6 root hubs + chu-de hubs + chu-de index), sitemap, matrix flips to PUBLISHED, BATCH-007 report, factory-progress. Post-publish suite passed (subsequent runs by the concurrent writer recovered no pending transaction and passed all pre-op consistency checks on this state).

Live verification: kn-0051 article returns 200 and renders on GitHub Pages; `cam-nang/kinh-nghiem/page-2.html` renders; sitemap excludes page-2 URLs as required.

## Concurrent writer detected — run stopped safely
Between 18:04:48Z and 18:10:35Z another external-agent session wrote, QA'd, repaired (AT-0053/0054 draft-target links), requeued and published BATCH-007 chunk 2 (AT-0052..AT-0056, 5 articles, operator commit dbd7e15). Its last commit was minutes before this run ended. To avoid duplicate rows, racing operator commands, or overwriting drafts, this run did NOT claim any of the 39 remaining WRITING rows. Two uncoordinated writers on the same batch is a conflict under the operating rules; this run stopped safely at that boundary.

## Repository truth at end of run (HEAD dbd7e15)
- BATCH-007: 50 rows, 11 PUBLISHED (chunk 1: KN-0051, XM-0051, AT-0051, CD-0051, DL-0051, HD-0051; chunk 2: AT-0052..AT-0056), 39 WRITING, 0 FAIL/BLOCKED.
- Factory totals: ~311 published of 2000; completed_batches 6; active_batch BATCH-007 (writer: external-agent).
- Remaining WRITING rows (next resume point, before any NEW batch work):
  - AT-0057..AT-0059 (3)
  - CD-0052..CD-0058 (7)
  - DL-0052..DL-0058 (7)
  - HD-0052..HD-0058 (7)
  - KN-0052..KN-0059 (8)
  - XM-0052..XM-0058 (7)

## Known landmines for the next run
- Published chunk-1/2 articles carry minor mojibake and "word broken across newline" artifacts (worst: AT-0051, fully double-encoded body). Publishing is forward-only; repair-in-place is a separate decision for Mr Tú. New drafts must be clean UTF-8.
- Never place a model name within 60 chars before a digit price (QA price-gate regex bug); use model-free pricing sentences with approved prices from config/business-facts.json.
- The actions API via the web fetcher caches responses (check-runs and run status stayed "in_progress" long after completion); use the jobs endpoint or commit listing (github_app connector) for fresh state.
- Only ONE operator command commit at a time; the workflow deletes the command file after executing.
- FAIL rows are terminal: push fixed article + op requeue, wait for operator commit, then op qa.

## Next run resume point
1. Poll commits: if the concurrent writer has continued past dbd7e15, reconcile from its latest state before claiming rows.
2. If the batch is idle, resume chunked writing with the 39 WRITING rows above, then op qa → repair/requeue → op publish per docs/CONTENT-FACTORY.md and docs/PROC-PUBLISH.md.
