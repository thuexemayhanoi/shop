# Run report 2026-09-28 — BATCH-009 reconciliation and completion

## Outcome
BATCH-009 is fully terminal: 50/50 rows PUBLISHED, 0 PASS/FAIL/REVIEW/BLOCKED.
Result commit: 58a1c44 "factory-operator: publish" (2026-09-28T12:09:54Z).
Verified from reports/batches/BATCH-009.md at 58a1c44: published: 50, fail: 0, pass: 0.
All 8 promoted drafts deleted from _drafts/; public files present at their output_paths.

## Diagnosis (why earlier publish runs failed)
1. Stale CDN cache: raw.githubusercontent served the 10:59 BATCH-009.md (4 PASS / 4 FAIL)
   after the 11:02 QA op (8d7308b) had already re-scored all 8 rows PASS
   (pass: 8, fail: 0, min score 95). The "4 FAIL rows" from the prior run's summary
   were already repaired (chunk-11) and QA-passed at 11:02.
2. Run #364 (76e4273, publish 8 ids): publish + full test suite SUCCEEDED, but the
   commit step failed — writer draft-repair pushes (11:05:39–11:06:08) raced the
   in-flight run; git push was rejected and rebase aborted on the dirty test-output tree.
3. Runs #365/#367 (publish only 4 of 8 PASS ids): the publish itself succeeded, but
   "Full test suites after a publish" failed because tests/test_production_standard.py
   MatrixStatusTests.test_non_planned_rows_confined_to_active_batch requires that when
   no batch has WRITING/QA/REPAIR/REVIEW rows (active = None), there are also no PASS
   rows anywhere. Publishing a subset left 4 PASS rows in that state.
4. The retry push 78e5809 (identical file content, identical tree) triggered no workflow:
   GitHub paths-filters see zero changed files.
5. The unittest op (9894b2b → bec6a97) confirmed the committed-state failure was only
   MatrixStatusTests (4/8 PASS rows, active = None) and committed the suite output.

## Actions taken this run
- Diagnosed runs #364/#365/#367 step-by-step via the Actions API (jobs, annotations, timings).
- Restored 4 drafts to their exact QA-passed versions (ref 8d7308b), because chunk-12
  edits (7525cb6, e17a5e4, fbf8ce4, 237f3ae) had modified PASS drafts AFTER QA, from the
  stale report. Restores: 32ba2b4 (dl-0072), e7ca218 (dl-0073), 610fb27 (dl-0075),
  878e99f (hd-0075). Fetched byte-exact via the contents API (base64), not raw URLs
  (which line-wrap and corrupt files).
- Pushed publish command with ALL 8 PASS ids (9cdb100). No concurrent pushes during the run.
- Run completed clean: publish, canonical generator freshness, full Python+Node suites
  passed; deterministic outputs committed as 58a1c44.

## Rules confirmed for future runs
- NEVER trust raw.githubusercontent for repo truth (CDN cache + 80-char line wrapping);
  use the contents API (base64) or commit-pinned checks.
- NEVER push anything while a factory-operator run is in flight (push conflicts abort
  the run's commit step; rebase cannot recover a dirty tree).
- Publish the FULL set of a batch's PASS rows in one op, or requeue first: a partial
  publish of a batch whose remaining rows are all PASS/FAIL fails MatrixStatusTests.
- One op per operator-command.json push; verify the result commit before the next op.

## Next run
- BATCH-009 complete (9 batches done, 450/2000 published). Production NOT complete.
- NEW WORK for the next run: push {"op":"prepare-next"} to claim BATCH-010 (50 rows),
  then write drafts per reports/batches/BATCH-010/rows/<ID>.json manifests, then
  qa → publish loop.
