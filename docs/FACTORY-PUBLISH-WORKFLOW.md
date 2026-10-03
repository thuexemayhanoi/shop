# Factory Publish Workflow (Simple Production Mode)

Event-driven publish pipeline: `.github/workflows/factory-publish.yml`.
Ported from the `vanchinh` design, adapted to the `/shop` deploy-gate
drafts model. Deterministic only: no AI, no API keys, no secrets, no
cron. The external WRITER commits article files; the workflow derives
the exact scope from the files actually added/modified in the push and
runs the canonical factory tooling for that scope ONLY.

The matrix (`data/content-matrix.csv`) is the source of truth for
status, score and batch membership. The workflow NEVER trusts a claim
that is not derivable from the pushed files plus matrix truth.

## Trigger and scope selection

```
on: push to main, paths: _drafts/cam-nang/**, cam-nang/**,
               .github/workflows/factory-publish.yml
on: workflow_dispatch (input publish_ids: explicit PASS ids)
```

`scripts/factory_push_selection.py` receives the added/modified path
lists of the push (drafts live at `_drafts/<output_path>`; published
articles at `<output_path>` — both map back to the matrix row) and
emits a JSON scope: `{proceed, mode, batch, claim_ids, qa_ids,
publish_ids, refuse, published_edits, unmapped_paths}`.

### Modes

| Mode | Condition | Action |
|---|---|---|
| `new` | PLANNED rows of the active batch whose file was added by this push (≤ 50; the micro-loop pushes exactly 2) | claim exactly those IDs → scoped QA → publish PASS |
| `repair` | Active rows (WRITING/QA/REVIEW/REPAIR) touched by this push; touched PASS rows | scoped QA on the repaired IDs; publish touched PASS IDs. NEVER claims fresh PLANNED rows |
| `backlog` | No claimable/repairable files in this push, but PLANNED rows of the active batch already have files | claim + QA the first 50 by article_id (recovery for a pipeline failure between file add and claim) |
| `skip` | Nothing to do (tooling-only push, or the factory's own state commit re-triggering on promoted PUBLISHED files) | exit green, bounded — no recursion: a state commit never produces new article work |
| `refuse` | > 50 new article files, or the push touches non-PUBLISHED rows of a batch other than the active batch | exit 3, state unchanged |
| `dispatch-publish` | `workflow_dispatch` with explicit `publish_ids` | publish exactly those PASS ids (canonical transaction, full gates) |

Edits to PUBLISHED rows (article-shell rebuilds, repair-in-place) are
ignored by the selector. Unmapped article-like paths are recorded for
audit only.

## Pipeline steps (per run)

1. Guard: `factory.mjs --recover`, assert no pending txn marker
   (`data/batches/txn/txn.json`) and no batch lock (`data/batches/*.lock`).
2. Pre-op invariants: `validate_content_matrix.py` + `factory.mjs --consistency`.
3. Claim exactly the added-article IDs: `run_article_batch.py --batch
   <batch> --claim-ids --ids <claim_ids>` (PLANNED → WRITING only;
   refuses duplicates/unknown/non-PLANNED/lock/kill-switch).
4. Scoped QA (single run): `run_article_batch.py --batch <batch>
   --ids <qa_ids> --qa`. Exit contract: 0 clean / 3 FAIL rows recorded /
   4 REVIEW-or-BLOCKED rows recorded — all three are green pipeline
   results; 1 (tool/config), 2 (usage/lock) and any other exit are RED.
5. Compute publish scope: explicit PASS ids only (dispatch preselection
   ∪ qa_ids that reached PASS in the matrix this run).
6. Transactional publish: `factory.mjs --publish <ids>` (dry-run first)
   — promotes drafts to their real `output_path`, flips rows to
   PUBLISHED, regenerates hubs/sitemap/progress/report in ONE
   transaction.
7. `apply_article_shell.py` on the promoted files; then
   `gate_published_articles.py --ids <ids>` re-validates every freshly
   published article.
8. Batch-terminal FULL audit DISPATCH (2026-10-01): when the publish
   completes the batch (every non-SAMPLE row terminal), the pair loop
   dispatches `factory-publish-verify.yml` (read-only heavy audit: full
   python + node suites, full consistency, semantic verifier, generator
   freshness, full cannibalization sweep, evidence-aware full
   published-articles audit). The heavy audit no longer runs inline in
   the pair loop.
9. Generator freshness (`generate_category_pages.py`,
   `generate_sitemap.py --check`), matrix smoke, semantic verifier
   (`verify_factory_state.py --op publish --ids …` + `--op consistency`).
10. ONE commit of derived state
    (`factory: <mode> publish (<ids>) [automated txn]`) with a bounded
    rebase retry (2 attempts, re-verify consistency before pushing).
11. Assert clean: no txn marker, no batch lock left behind.

## Thresholds (75/70/75, owner-approved)

Centralized in `config/article-rubric.json` — the single source read by
`score_article.py`, `run_article_batch.py`, `factory.mjs` (qa-record and
publish gates) and the tests:

- QUALITY_MIN = PUBLISH_MIN = `thresholds.PASS.min` = **75**
  (one 100-point total score; no separate SEO score on `/shop`)
- SEO floor = `thresholds.REVIEW.min` = **70** (mapped as the FAIL
  boundary: FAIL = score < 70)
- PASS = 75–100 AND no critical failures AND no review flags.
  **Scores 75–100 are simply PASS: no EXCELLENT tier and no QA warning band.**
- REVIEW = 70–74 (or unresolved review flags).
- FAIL = < 70 OR any critical failure.

Critical gates are NEVER lowered: fabricated facts, invented
prices/deposits, broken canonical, duplicate ID/slug/canonical,
placeholder leakage, legal source-policy, broken required links — a
critical failure fails the article even at score 100.

## Micro-pair production loop

1. Writer picks the next 2 PLANNED rows of the active batch, writes
   the two drafts to `_drafts/<output_path>`, and pushes ONLY those
   files to main.
2. The workflow selects `new` mode, claims exactly the 2 IDs, runs
   scoped QA, publishes the PASS ones and commits the derived state.
3. Writer verifies (rows PUBLISHED in the matrix, no txn marker, no
   lock, workflow green), fetches fresh main, then continues with the
   next pair. Repair pushes (REVIEW/FAIL rows, max 3 attempts, then
   BLOCKED) follow the same event-driven path in `repair` mode.

One failing article never blocks its pair: FAIL/REVIEW are legitimate
recorded states (exit 3/4) and every PASS row of the same push still
publishes.

## Fail-closed properties preserved

Atomic writer lock (`data/batches/<batch>.lock`), stale-lock recovery,
transaction recovery (`--recover`), exact-SHA verification, kill switch
(`config/content-factory.json` `enabled`), semantic verifier
(`verify_factory_state.py`), Hanoi (+07:00) timestamps, schema-2
reports, `source_head_sha` semantics. The workflow mutates the ledger
only through the canonical transactional tooling; concurrency group
`factory-publish` (cancel-in-progress: false) serializes runs.

The full test suites and the full-site audit are NOT part of the
per-pair loop (dual-mode gate, 2026-10-01): `article-quality.yml` runs
the FAST content gate on content-only pushes (matrix + consistency +
the exact changed candidates) and the FULL canonical gate
(`scripts/ci/factory_final_gate.sh`) only on engine/global-affecting
changes and manual FULL dispatch; `factory-publish-verify.yml` owns the
heavy whole-repository audit (manual, batch terminal, engine change,
final 2000-article audit). The micro-pair is bounded by
`chunk_size = 2` (`config/content-factory.json`): a NEW push claims at
most 2 fresh article ids.
