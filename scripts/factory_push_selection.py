#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory_push_selection.py - deterministic push-scope selection for the
event-driven factory-publish workflow (WRITE-AHEAD QUEUE contract).

Ported from the stable thuexemayhanoi/vanchinh factory design and adapted
to the /shop deploy-gate drafts model: article files for rows that are
NOT yet PUBLISHED live under _drafts/<output_path>; scripts/js/factory.mjs
--publish promotes a draft to its REAL output_path inside the same
transaction. The selector therefore maps BOTH forms (_drafts/<path> and
the final <path>) back to the row's output_path.

The workflow derives the article scope from the files the writer actually
added/modified in the push - never a blind limit-based claim that grabs
PLANNED rows whose files do not exist yet.

WRITE-AHEAD QUEUE CONTRACT (supersedes the old "exact 2 per push"
micro-pair contract; owner-approved 2026-10-05):
  - one writer push may queue 2..MAX_PER_PUSH (10) article files;
  - the queue is validated against repository/matrix truth (no
    duplicates, no PUBLISHED rows, no rows outside the active batch,
    matrix order);
  - the queue is split into deterministic PAIRS of 2 which the factory
    consumes sequentially inside the SAME production run
    (pair -> exact-ID claim -> scoped QA -> transactional publish ->
    checkpoint -> next pair); a failed pair NEVER rolls back
    already-published pairs and stays recoverable (REVIEW/REPAIR/
    BLOCKED states) for a repair push.

Inputs (newline-separated path lists, one path per line):
  --added <file>     paths ADDED in this push    (git diff --diff-filter=A)
  --modified <file>  paths MODIFIED in this push (git diff --diff-filter=M)

Output: JSON on stdout describing the exact, verifiable scope:
  {
    "proceed": bool,          # false => workflow skips everything
    "mode": "new"|"repair"|"backlog"|"skip",
    "batch": "BATCH-012"|null,
    "claim_ids": [...],      # PLANNED -> WRITING claim targets (<= 10)
    "qa_ids": [...],         # explicit scoped-QA targets (claim + repair)
    "publish_ids": [...],    # already-PASS touched rows (publish, no re-QA)
    "queue": [...],           # the full write-ahead queue (matrix order)
    "pairs": [[A,B],...],     # deterministic pairs of PAIR_SIZE (2)
    "pair_count": int,
    "refuse": null|"reason",  # non-null => the push violates the contract
    "published_edits": [...],  # audit: PUBLISHED-row edits (ignored)
    "unmapped_paths": [...]   # audit: touched paths without a matrix row
  }

Selection rules (deterministic, matrix truth):
  NEW mode:     PLANNED rows of the active batch whose output_path is in
                the touched list (added or modified, draft or final
                form) AND the file exists. A PLANNED row whose file is
                NOT touched (or missing) is NEVER claimed.
  REPAIR mode:  rows of the active batch in WRITING/QA/REVIEW/REPAIR
                whose file is touched AND exists -> scoped QA targets;
                PASS rows touched -> direct publish targets. A repair
                push NEVER claims fresh PLANNED rows.
  BACKLOG mode: nothing claimable/repairable in this push, but PLANNED
                rows of the active batch already have files in the repo
                (e.g. a previous pipeline failure between file add and
                claim). Deterministic first MAX_PER_PUSH by matrix order.
  SKIP:         nothing to do (e.g. tooling-only push, or the factory's
                own state commit re-triggering this workflow on the
                promoted PUBLISHED files).
  REFUSE:       > MAX_PER_PUSH (10, write-ahead queue) queued article /
                files in one push; or the push touches article rows
                that contradict matrix truth (rows of a non-active
                batch, terminal FAIL/BLOCKED rows).

Exit codes: 0 ok, 3 refuse (contract violation; state unchanged).
"""
import argparse
import json
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import article_lib as lib

TERMINAL = ("PUBLISHED", "BLOCKED", "FAIL")
ACTIVE = ("WRITING", "QA", "REVIEW", "REPAIR")
MAX_PER_PUSH = 10  # write-ahead queue: one writer push queues at most
                   # 10 articles (ported from the stable vanchinh
                   # factory contract; refuse anything larger)
PAIR_SIZE = 2      # the factory consumes the queue as deterministic
                   # pairs of 2 (scripts/factory_queue.py)


def max_per_push():
    """Write-ahead queue cap, from config/content-factory.json.

    Fail-closed: missing config, missing key, or an out-of-range value
    (not 2..MAX_PER_PUSH) falls back to MAX_PER_PUSH, never above it."""
    try:
        cfg = json.loads(pathlib.Path(
            lib.repo_path("config", "content-factory.json")
        ).read_text(encoding="utf-8"))
        n = int(cfg.get("queue_max_push", MAX_PER_PUSH))
    except Exception:
        n = MAX_PER_PUSH
    if n < 2 or n > MAX_PER_PUSH:
        n = MAX_PER_PUSH
    return n

DRAFTS_PREFIX = "_drafts/"


def read_paths(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [line.strip() for line in p.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def article_output_path(repo_path):
    """Map a repository path to a matrix output_path.

    _drafts/cam-nang/<cat>/<slug>.html -> cam-nang/<cat>/<slug>.html
    cam-nang/<cat>/<slug>.html          -> itself
    anything else (hubs, taxonomies, tooling) -> None
    """
    p = (repo_path or "").strip()
    if p.startswith(DRAFTS_PREFIX):
        p = p[len(DRAFTS_PREFIX):]
    if p.startswith("cam-nang/"):
        return p
    return None


def production_rows():
    return [r for r in lib.load_matrix() if not lib.is_sample_row(r)]


def active_or_next_batch(rows):
    """Same resolution order as run_article_batch.next_batch_id():
    resume the active batch (WRITING/QA/REPAIR/REVIEW rows) first; only
    when no batch is unfinished select the first batch with PLANNED
    rows. FAIL/BLOCKED never block later batches."""
    order = []
    for r in rows:
        b = (r.get("batch_id") or "").strip()
        if b and b not in order:
            order.append(b)
    for b in order:
        if any((r.get("status") or "").strip() in ACTIVE
               for r in rows if (r.get("batch_id") or "").strip() == b):
            return b
    for b in order:
        if any((r.get("status") or "").strip() == "PLANNED"
               for r in rows if (r.get("batch_id") or "").strip() == b):
            return b
    return None


def row_has_file(row):
    """The row's article file exists at the draft or the final path."""
    op = (row.get("output_path") or "").strip()
    if not op:
        return False
    if pathlib.Path(lib.repo_path("_drafts", op.lstrip("/"))).is_file():
        return True
    return pathlib.Path(lib.repo_path(op.lstrip("/"))).is_file()


def _matrix_order(rows):
    """article_id -> position in matrix (repository/matrix order)."""
    return {r["article_id"]: i for i, r in enumerate(rows)}


def _queue_pairs(ids, order):
    """Split ordered ids into deterministic PAIR_SIZE chunks."""
    ordered = sorted(ids, key=lambda a: order.get(a, 10 ** 9))
    return [ordered[i:i + PAIR_SIZE]
            for i in range(0, len(ordered), PAIR_SIZE)]


def select(added, modified):
    rows = production_rows()
    batch = active_or_next_batch(rows)
    out = {"proceed": False, "mode": "skip", "batch": batch,
           "claim_ids": [], "qa_ids": [], "publish_ids": [],
           "queue": [], "pairs": [], "pair_count": 0,
           "refuse": None, "published_edits": [], "unmapped_paths": []}
    if batch is None:
        return out
    by_output_path = {}
    for r in rows:  # duplicate output paths are a matrix violation; first wins
        op = (r.get("output_path") or "").strip()
        if op:
            by_output_path.setdefault(op, r)

    touched_paths = [p for p in (added + modified) if p]
    mapped = []       # (repo_path, output_path, row_or_None)
    for p in touched_paths:
        op = article_output_path(p)
        if op is None:
            continue  # structural/tooling path - not an article row
        mapped.append((p, op, by_output_path.get(op)))

    for p, op, row in mapped:
        if row is None:
            out["unmapped_paths"].append(p)  # audit only; never blocks
            continue
        st = (row.get("status") or "").strip()
        rb = (row.get("batch_id") or "").strip()
        if st == "PUBLISHED":
            out["published_edits"].append(p)  # shell/rebuild edits - ignored
            continue
        if rb != batch:
            out["refuse"] = (
                "push touches %s row %s of batch %s while %s is the "
                "active batch - write only rows of the active batch"
                % (st or "unknown-status", row.get("article_id"), rb, batch))
            return out
        if st in ("FAIL", "BLOCKED"):
            out["refuse"] = (
                "push touches terminal %s row %s - requeue it via "
                "scripts/requeue_rows.py before pushing a repair"
                % (st, row.get("article_id")))
            return out
    touched_output_paths = {op for _, op, _ in mapped}

    br = [r for r in rows if (r.get("batch_id") or "").strip() == batch]

    # NEW: PLANNED rows of the active batch whose file was touched.
    new_ids = sorted(r["article_id"] for r in br
                     if (r.get("status") or "").strip() == "PLANNED"
                     and (r.get("output_path") or "").strip()
                     in touched_output_paths
                     and row_has_file(r))
    # REPAIR: active (WRITING/QA/REVIEW/REPAIR) rows touched -> scoped QA.
    repair_ids = sorted(r["article_id"] for r in br
                        if (r.get("status") or "").strip() in ACTIVE
                        and (r.get("output_path") or "").strip()
                        in touched_output_paths
                        and row_has_file(r))
    # Already-PASS rows touched -> publish directly (never re-QA'd).
    pass_ids = sorted(r["article_id"] for r in br
                      if (r.get("status") or "").strip() == "PASS"
                      and (r.get("output_path") or "").strip()
                      in touched_output_paths
                      and row_has_file(r))

    limit = max_per_push()
    queued = sorted(set(new_ids) | set(repair_ids) | set(pass_ids))
    if len(queued) > limit:
        out["refuse"] = ("push queues %d article files; max %d per "
                         "commit (queue_max_push, the write-ahead "
                         "queue contract) - split the push "
                         "deterministically" % (len(queued), limit))
        return out

    order = _matrix_order(rows)
    if new_ids:
        out["mode"] = "new"
        out["claim_ids"] = new_ids
        out["qa_ids"] = sorted(set(new_ids) | set(repair_ids))
        out["publish_ids"] = pass_ids
        out["queue"] = queued
        out["pairs"] = _queue_pairs(queued, order)
        out["pair_count"] = len(out["pairs"])
        out["proceed"] = True
        return out
    if repair_ids or pass_ids:
        # repair/resume push: process EXACTLY these IDs; never claim
        # fresh PLANNED rows on a repair push.
        out["mode"] = "repair"
        out["qa_ids"] = repair_ids
        out["publish_ids"] = pass_ids
        out["queue"] = queued
        out["pairs"] = _queue_pairs(queued, order)
        out["pair_count"] = len(out["pairs"])
        out["proceed"] = True
        return out
    # BACKLOG: PLANNED rows whose files already exist (no files in this
    # push) - recovery for a pipeline failure between file add and claim.
    backlog = [r["article_id"] for r in br
              if (r.get("status") or "").strip() == "PLANNED"
              and row_has_file(r)]
    backlog = _queue_pairs(backlog, order)
    backlog = [a for pair in backlog for a in pair][:limit]
    if backlog:
        out["mode"] = "backlog"
        out["claim_ids"] = backlog
        out["qa_ids"] = backlog
        out["queue"] = backlog
        out["pairs"] = _queue_pairs(backlog, order)
        out["pair_count"] = len(out["pairs"])
        out["proceed"] = True
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--added", default=None,
                    help="file with newline-separated added paths")
    ap.add_argument("--modified", default=None,
                    help="file with newline-separated modified paths")
    args = ap.parse_args()
    added = read_paths(args.added) if args.added else []
    modified = read_paths(args.modified) if args.modified else []
    out = select(added, modified)
    print(json.dumps(out, ensure_ascii=False))
    return 3 if out["refuse"] else 0


if __name__ == "__main__":
    sys.exit(main())
