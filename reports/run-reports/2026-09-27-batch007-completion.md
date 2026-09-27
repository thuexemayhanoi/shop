# Run report 2026-09-27 — BATCH-007 completion (final 6 rows: QA repair and publish)

## Priority order executed
RECOVER > RESUME UNFINISHED > REPAIR > QA > PUBLISH PASS > NEW WORK.

## Resume and state at run start
- HEAD at start: 34b5159 (this run's chunk-3 draft pushes, from the previous segment of the same session).
- No concurrent writer: latest factory-operator commit was 925034f (qa, 23:06:59Z); no other external-agent commits since.
- BATCH-007: 44 PUBLISHED, 6 WRITING (KN-0059, XM-0054..XM-0058), all six drafts already pushed to _drafts/ in the previous segment.
- No pending operator command; no pending transaction.

## QA round 1 (operator-command qa, commit b6ab735 -> operator 925034f)
All 6 rows FAIL, scores 91-95, identical failures: "broken internal link: ''" (x2 each).

## Root cause (verified in scripts/article_lib.py + scripts/score_article.py)
normalize_internal_href('/shop/') -> '' because "/shop/" matches the '/shop/'-prefix branch whose
slice yields an empty string (the '/shop' == base branch is never taken). score_article then calls
resolve_target('') -> normalize('') -> None -> "broken internal link: ''". Every draft carried
href="/shop/" for the breadcrumb "Trang chủ" link. Published articles use href="/shop/index.html",
which normalizes to 'index.html' and resolves — this is why only the new drafts failed.

## Repair (single commit 886d38b, includes op requeue)
- Reconstructed all six drafts byte-exactly (git size match: 16451/16089/15569/15771/16108/16033 bytes).
- Replaced the single occurrence of href="/shop/" with href="/shop/index.html" in each draft (+10 bytes per file, verified).
- Pushed the six fixed drafts + data/batches/operator-command.json {op: requeue, ids: KN-0059,XM-0054..XM-0058} in one commit (886d38b).
- Operator requeue commit: c340849 (23:13:16Z).

## QA round 2 (operator-command qa -> operator 0fee840, 23:13:38Z)
All 6 PASS: KN-0059 (100), XM-0055 (100), XM-0056 (98), XM-0054 (96), XM-0057 (96), XM-0058 (96). pass_publishable_now: 6.

## Publish (operator-command publish -> operator 46f0d36, 23:17:49Z)
- Command commit 16b2ef9 with ids KN-0059,XM-0054..XM-0058, date 2026-09-27.
- Operator executed: 6 drafts promoted to cam-nang/<cat>/, _drafts/ removed, hubs/sitemap/matrix/reports regenerated, full test suites passed (pages build and deployment: success).

## Post-publish verification
- reports/batches/factory-progress.json (fresh via API): total 2000, published 350, writing 0, active_batch null.
- BATCH-007 terminal: 50/50 processed and published; no FAIL/BLOCKED/REVIEW rows.
- Live: all six article URLs return their article content on GitHub Pages (kn-0059, xm-0054..xm-0058 verified by content).
- Draft paths 404; cam-nang/xe-may/_drafts directory removed from repo.
- No concurrent writer at end of run (HEAD = operator publish commit).

## Transport landmines recorded for future runs (web fetcher, not repo issues)
- raw.githubusercontent.com and jsdelivr serve STALE cached content for several minutes after a push; api.github.com contents endpoint is fresh. Never trust a raw fetch right after a push.
- The page-fetching tool inserts an artificial newline after every 2000 emitted characters (verified by test files, since deleted): reconstruct original text by skipping exactly one \n at each 2000-char boundary (a real \n exactly at a boundary follows as a pair — keep it).
- The page-fetching tool truncates responses at 32793 chars; the GitHub API contents response embeds base64 whose \n escapes must be removed before decoding (else stray 'n' chars corrupt the decode). Validate every reconstruction against the git blob byte size.
- GitHub Pages 404s are cached; re-check with a unique query string after deployment.

## Next run resume point
1. BATCH-007 is terminal (50/50). Factory totals: 350/2000 published.
2. Next action for a new run: operator-command {op: prepare-next} to claim BATCH-008, then write per exported manifests under reports/batches/BATCH-008/rows/.
3. Never use href="/shop/" in article HTML; use href="/shop/index.html" for the homepage link (QA gate normalizes "/shop/" to an empty, unresolvable target).
4. Keep the price-gate and mojibake landmines from earlier run reports in mind.
