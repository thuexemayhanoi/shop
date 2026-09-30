# Factory Reliability — the four-layer hardening

This document is the contract reference for the reliability hardening of
the content factory. Everything described here is enforced by code and
pinned by tests:

* `scripts/ci/factory_final_gate.sh` — the ONE canonical gate
* `scripts/verify_factory_state.py` — semantic production-invariant
  verifier (L3)
* `scripts/factory_health.py` — deterministic health evaluator
* `tests/test_factory_reliability.py` — L4 reliability suite
* `tests/test_factory_operator_workflow.py` — workflow contract suite

## 1. The four reliability layers

| Layer | What | Enforced by |
|---|---|---|
| L1 unit | Python + Node test suites | `factory_final_gate.sh` step 1–2 |
| L2 integration | matrix invariants, factory consistency (matrix/hub/sitemap/leaks), canonical generator freshness (`--check`) | `factory_final_gate.sh` step 3–6 |
| L3 production | semantic factory invariants + op postconditions on the EXACT tree (`PRODUCTION_INVARIANT=PASS`) | `verify_factory_state.py` inside the gate |
| L4 long-run | hermetic reliability: sandbox lifecycle, failure injection, transaction cleanliness, writer-lock contention/races, health verdicts, workflow fail-closed contract | `tests/test_factory_reliability.py`, `tests/test_factory_operator_workflow.py` |

One gate, one definition of green. `factory_final_gate.sh` is run from
the same file by every consumer: the PR/push quality gate
(`article-quality.yml`), the factory operator (before every push, after
every rebase, and once more on the exact final main SHA) and any local
run. A workflow exiting 0 is NEVER "production success" by itself.

## 2. The exact-final-SHA contract

Every operator mutation follows one auditable line:

```
INPUT_SHA -> (deterministic operation) -> OP_RESULT_SHA -> push -> FINAL_MAIN_SHA
```

* `INPUT_SHA` — the exact tree the operation started from (the
  workflow's `GITHUB_SHA`, recorded before any mutation).
* `OP_RESULT_SHA` — the commit produced by the operation's
  deterministic outputs. It is captured from git AFTER the commit; it
  is deliberately NEVER written inside the pushed files (a file cannot
  prove "this commit contains me" — that self-reference is unstable).
* `FINAL_MAIN_SHA` — `origin/main` after the push. The workflow only
  accepts the push when `FINAL_MAIN_SHA == OP_RESULT_SHA`, then
  DETACHES to that exact SHA and reruns the full canonical gate +
  semantic verifier on it. `PRODUCTION_INVARIANT=PASS` is earned only
  on the exact final main SHA, and `INPUT_SHA` / `OP_RESULT_SHA` /
  `FINAL_MAIN_SHA` are recorded in the step summary.

Fail-closed push rules (all pinned by
`tests/test_factory_operator_workflow.py`):

* The push must prove `pushed=true`; up to 5 retries.
* On a push failure: fetch `origin/main`, rebase, then RERUN the full
  canonical gate + semantic verifier on the rebased tree BEFORE pushing
  it (tree A is never tested and tree B pushed).
* A rebase CONFLICT aborts safely: `git rebase --abort`, RED run, no
  force push, no blind auto-resolution.
* After 5 failed retries the run is RED — there is no silent success.
* The QA/requeue exit codes are contract-checked: only 0/3/4 may end
  green (3 = FAIL/refusals legitimately recorded, 4 = REVIEW/BLOCKED
  legitimately recorded); 1 (tool/config), 2 (usage/lock) and any
  unknown exit are RED.
* The operator postcondition runs `verify_factory_state.py` with
  op-specific arguments (`if: always()`), so a green tool exit with a
  broken semantic state can never be pushed.

## 3. Semantic invariants (L3, `verify_factory_state.py`)

On the exact tree it is pointed at, the verifier checks:

1. matrix invariant — parses; unique ids/slugs/paths; known statuses
2. factory consistency — PUBLISHED rows have their public file;
   non-PUBLISHED rows have NO file at the public path (deploy gate: no
   unpublished public leaks)
3. transaction clean — no PENDING marker under `data/batches/txn/`
4. sitemap truth — sitemap article namespace == PUBLISHED rows
5. hub truth — every hub lists exactly its first 50 PUBLISHED articles
6. report truth — `factory-progress.json` is schema 2 with counts equal
   to the matrix (a stale or hand-patched report is a lie and fails)
7. op postcondition — qa recorded results for the target rows; publish
   made every target id PUBLISHED (file + sitemap); requeue actually
   requeued the eligible ids; prepare-next left an active batch (or
   completed the factory)

Exit contract: 0 = every invariant holds on this exact tree, 1 = one or
more failed (each printed with `::error::`), 2 = usage error.

## 4. Report schema 2

`reports/batches/factory-progress.json` and the batch reports are
schema 2:

* `schema_version: 2`
* every timestamp is a timezone-aware HANO timestamp
  (`+07:00`, e.g. `2026-09-30T11:40:15+07:00`; legacy `+00:00` or naive
  timestamps are rejected)
* `source_head_sha` = the INPUT tree the report was generated from
  (`GITHUB_SHA` in Actions, `git rev-parse HEAD` locally, `null` when
  neither exists). Schema-1's `matrix_commit_sha` (the unstable
  "this commit contains me" claim) is gone and its presence is a
  verifier failure.
* `published_commit_sha` remains the durable audit trail, resolved once
  from the publish checkpoint and then carried forward.
* Counts are ALWAYS regenerated from the current matrix truth; the
  verifier compares them and fails on any drift.

## 5. Atomic writer lock (external writers)

`data/batches/writer-lock.json` guards concurrent EXTERNAL writers on
the same active batch (schema 2, TTL 120 minutes):

* Acquisition is ATOMIC: the lock file is created with
  `O_CREAT|O_EXCL`, so of N concurrent writers EXACTLY ONE wins; the
  losers read the winner's lock and refuse (pinned by a 20-process
  contention test).
* The lock carries a unique generation `token`; only the owner's token
  can refresh (heart-beat) or release it — CAS-like replace.
* A FRESH lock owned by another session is never overwritten; release
  is ownership-safe (a foreign session's release is refused).
* A STALE lock (> TTL) is reclaimed only while holding the exclusive
  `writer-lock.recovery` guard, after re-reading and verifying the SAME
  stale token. Two reclaimers that saw the same stale lock are
  serialized by the guard; the loser sees the winner's fresh lock and
  refuses — a reclaim race can never clobber a fresh owner.
* A crashed reclaimer cannot deadlock recovery: the guard auto-expires
  after 5 minutes and is removed on the next attempt.
* `--next-chunk --writer-session <id>` aborts cleanly (exit 2) when a
  fresh lock is held by another writer: never two writers on one batch.

## 6. Transaction recovery

Every multi-file publish mutation (Node side) writes a PENDING marker
under `data/batches/txn/` FIRST, records the planned matrix state and
content, and removes it in the same transaction. If a run is
interrupted:

* All mutation modes refuse to run: `REFUSED: a pending transaction
  marker exists … Run --recover first.`
* `node scripts/js/factory.mjs --recover` verifies the marker against
  the matrix (gitignored, so repo truth wins) and either finishes the
  planned content or rolls the ledger back; on any inconsistency the
  marker is KEPT for manual resolution (never silently dropped).
* The canonical verifier and the health evaluator both treat a pending
  marker as `RECOVERY_REQUIRED` — recovery comes before every other
  verdict. A corrupt marker is still a recovery problem, never
  ignored.

## 7. Kill switch

`config/content-factory.json` `enabled: false` pauses ALL production
mutations (claims, QA, publish) with a non-zero exit. Safety operations
remain available while paused: `--recover`, `--consistency`,
`--writer-lock-status/acquire/release`, `--checkpoint`,
`--checkpoint-reset`, `--progress`. There is NO cron/AI anywhere in the
repository (enforced by `test_no_cron_anywhere`), so the former
`scheduled_runs_enabled` flag was dead configuration and was removed.

## 8. Health evaluation (`factory_health.py`)

A NO_PROGRESS / stalled verdict must be EARNED by evidence, not
assumed. The factory is mostly driven by an EXTERNAL writer, so
WAITING_FOR_WRITER is a legitimate, healthy state. Verdicts, in
priority order:

1. `RECOVERY_REQUIRED` — pending transaction marker exists
2. `LOCKED` — a FRESH writer lock is held (a stale lock is reported but
   does not block: it is reclaimable)
3. `READY_FOR_PUBLISH` — PASS rows with written files exist
4. `READY_FOR_QA` — active rows with written files exist
5. `WAITING_FOR_WRITER` — unwritten WRITING/PLANNED rows (never
   reported as stalled by itself)
6. `BLOCKED` — FAIL/BLOCKED rows and nothing else actionable
7. `COMPLETE` — no actionable rows

Compare mode (`--snapshot` / `--compare`): `NO_PROGRESS` only when the
semantic fingerprint (row statuses, txn/lock ownership — deliberately
EXCLUDING timestamps, so report churn can never look like progress)
is unchanged while an actionable backlog exists; `HEALTHY` when it
changed. The evaluator is read-only.

## 9. Failure modes and recovery process

| Failure | Detection | Recovery |
|---|---|---|
| QA/publish tool red (exit 1/2/unknown) | workflow contract-check | fix the tool/config on the branch; rerun CI — never widen the allowed exits |
| FAIL/REVIEW/BLOCKED article rows | QA exit 3/4 (legitimate) | repair the draft, requeue via `scripts/requeue_rows.py` (FAIL→REPAIR, budget-capped; BLOCKED only with `--allow-blocked` + fresh QA precheck) |
| Interrupted publish transaction | txn marker; consistency refuses mutations | `node scripts/js/factory.mjs --recover`; inspect the marker on inconsistency |
| Two writers on one batch | writer lock; second writer exits 2 | wait for the owner; a STALE lock is reclaimed automatically under the recovery guard |
| Push race on main | push retry: fetch + rebase + FULL gate rerun + push (×5) | rebase conflict = stop safe, resolve manually; exhaustion = RED with evidence preserved |
| Remote/main diverged from tested tree | `FINAL_MAIN_SHA != OP_RESULT_SHA` = RED | re-run the operator command from the new input tree |
| Stale/hand-patched reports | verifier report-truth check (counts vs matrix) | regenerate via the deterministic tools; never hand-edit reports |
| Unpublished public leak | verifier deploy-gate check | keep drafts under `_drafts/` until the publish transaction promotes them |
| Factory paused | kill switch non-zero exit | flip `enabled` back; no cron to restore, nothing else to clean up |

Recovery golden rule: repo truth (the matrix on the exact main SHA)
always wins — checkpoints and reports are reconciled FROM the matrix,
never the other way round, and no recovery step ever rewrites PASS /
PUBLISHED rows.

## 10. What the reliability suites pin

`tests/test_factory_reliability.py` (L4): full sandbox lifecycle
(prepare → write → scoped QA → requeue → chunk-complete → publish
scope → mark-published), verifier invariants + failure injection,
transaction cleanliness, schema-2 report + Hanoi timezone +
`source_head_sha` semantics, health verdicts incl. NO_PROGRESS
evidence, 20-process writer-lock contention (exactly one winner),
stale-lock reclaim race / recovery-guard serialization / CAS
ownership, kill switch.

`tests/test_factory_operator_workflow.py`: QA/requeue allowed exits,
unknown-exit RED, unittest-failure RED, push retry + exhaustion,
rebase path + conflict abort (no force push), canonical gate rerun
after rebase, verifier on the exact pushed tree, FINAL_MAIN_SHA
equality, no silent success on push failure, empty batch/ids parser
robustness, operator postcondition, command whitelisting and
single-flight concurrency.
