#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory_queue.py - WRITE-AHEAD QUEUE processor for the factory-publish
workflow (TURBO QUEUE contract, ported from the stable /vanchinh factory
and adapted to the /shop engine tooling).

Input contract (produced by scripts/factory_push_selection.py from the
push): one writer push queues 2..MAX_PER_PUSH (10) article IDs; this
processor consumes the queue as deterministic PAIRS of 2, sequentially,
inside ONE production run:

    pair -> claim (new mode only, exact pair IDs, never a blind claim)
         -> scoped QA (exit contract: ONLY 0/3/4 are valid results)
         -> transactional publish (PASS only; already-PASS touched rows
            publish directly, never re-QA'd)
         -> report checkpoint
         -> next pair

Safety contract:
  - repository truth is revalidated BEFORE any mutation: IDs must exist
    in the matrix, belong to the requested batch, never be PUBLISHED or
    terminal (FAIL/BLOCKED), carry no duplicates, and have their article
    file present (draft or final path);
  - each pair's publish is its OWN transaction; a failed pair NEVER
    rolls back already-published pairs;
  - a failed/review pair stays RECOVERABLE (REVIEW/REPAIR/BLOCKED
    states in the matrix) and is reported explicitly for a follow-up
    repair push;
  - full-site gates are NOT part of this hot loop (Simple Production
    Mode); the workflow runs the light matrix smoke and the scoped
    publish gate after the queue.

Run report: reports/batches/factory-queue-last-run.json is rewritten
after every pair (crash-resilient) and lists per-pair outcomes, the
published total and the recoverable IDs.

Usage:
  python3 scripts/factory_queue.py run --batch BATCH-017 --mode new    --ids A,B,C,...
  python3 scripts/factory_queue.py run --batch BATCH-017 --mode repair --ids A,B,...

Exit codes:
  0 = queue fully processed (published or recoverable states committed;
      partial QA failures are recoverable and do not fail the run)
  1 = fatal, nothing mutated (pending txn, invalid queue)
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import article_lib as lib

PAIR_SIZE = 2
QA_OK_EXITS = (0, 3, 4)   # 0 clean, 3 FAIL rows recorded, 4 REVIEW/
                          # BLOCKED rows recorded; anything else is a
                          # tool/config (1), usage/lock (2) or unknown
                          # failure and aborts the pair recoverably
QUEUEABLE_NEW = ("PLANNED", "WRITING", "QA", "REVIEW", "REPAIR", "PASS")
QUEUEABLE_REPAIR = ("WRITING", "QA", "REVIEW", "REPAIR", "PASS")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def report_path():
    """Report location; the env override is read at WRITE time so
    sandbox tests never write the production report."""
    return pathlib.Path(os.environ.get(
        "FACTORY_QUEUE_REPORT",
        str(lib.repo_path("reports", "batches",
                          "factory-queue-last-run.json"))))


def load_rows():
    return [r for r in lib.load_matrix() if not lib.is_sample_row(r)]


def run_cmd(cmd):
    """Run one canonical tool. Module-level so tests can stub it."""
    return subprocess.run(cmd, capture_output=True, text=True)


def _row_has_file(row):
    op = (row.get("output_path") or "").strip()
    if not op:
        return False
    if pathlib.Path(lib.repo_path("_drafts", op.lstrip("/"))).is_file():
        return True
    return pathlib.Path(lib.repo_path(op.lstrip("/"))).is_file()


def _validate_queue(batch_id, ids, mode):
    """Revalidate the queue against fresh repository truth BEFORE
    mutating anything. Returns (queue, error); queue is matrix-ordered
    and deduplicated, any violation is fatal and mutates nothing."""
    rows = load_rows()
    order = {r["article_id"]: i for i, r in enumerate(rows)}
    seen, queue = set(), []
    for a in ids:
        if a in seen:
            return None, "duplicate id in queue: %s" % a
        seen.add(a)
        queue.append(a)
    by_id = {r["article_id"]: r for r in rows}
    for a in queue:
        r = by_id.get(a)
        if r is None:
            return None, "%s: not found in matrix" % a
        if (r.get("batch_id") or "").strip() != batch_id:
            return None, ("%s: belongs to batch %s, not %s"
                          % (a, r.get("batch_id"), batch_id))
        st = (r.get("status") or "").strip()
        if st == "PUBLISHED":
            return None, ("%s: row is already PUBLISHED "
                          "(never re-claim/overwrite)" % a)
        if st in ("FAIL", "BLOCKED"):
            return None, "%s: terminal status %s" % (a, st)
        allowed = QUEUEABLE_NEW if mode == "new" else QUEUEABLE_REPAIR
        if st not in allowed:
            return None, ("%s: status %s not queueable in mode %s"
                          % (a, st, mode))
        if not _row_has_file(r):
            return None, "%s: article file missing at %s" % (
                a, r.get("output_path"))
    queue.sort(key=lambda a: order[a])
    return queue, None


def _write_report(state):
    p = report_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _pair_claim(batch_id, qa_ids):
    """Exact-ID claim via the canonical CLI (new mode only)."""
    return run_cmd([sys.executable, "scripts/run_article_batch.py",
                    "--batch", batch_id,
                    "--claim-ids", "--ids", ",".join(qa_ids)])


def _pair_qa(batch_id, qa_ids):
    """Scoped QA via the canonical CLI; exit contract 0/3/4."""
    return run_cmd([sys.executable, "scripts/run_article_batch.py",
                    "--batch", batch_id,
                    "--ids", ",".join(qa_ids), "--qa"])


def _pair_publish(ids_csv, dry_run=False):
    cmd = ["node", "scripts/js/factory.mjs", "--publish", ids_csv]
    if dry_run:
        cmd.append("--dry-run")
    return run_cmd(cmd)


def run_queue(batch_id, mode, ids, pair_size=PAIR_SIZE):
    started = _now()
    queue, err = _validate_queue(batch_id, ids, mode)
    if err is not None:
        print(json.dumps({"error": "refusing queue: %s" % err,
                          "batch": batch_id, "mode": mode},
                         ensure_ascii=False))
        return 1
    if pathlib.Path(lib.repo_path("data", "batches", "txn",
                                 "txn.json")).is_file():
        print(json.dumps({"error": "pending transaction marker present; "
                          "run factory.mjs --recover first",
                          "batch": batch_id}, ensure_ascii=False))
        return 1
    pairs = [queue[i:i + pair_size] for i in range(0, len(queue), pair_size)]
    state = {"schema_version": "1", "batch": batch_id, "mode": mode,
             "queue": queue, "pair_size": pair_size, "started": started,
             "finished": None, "pairs": [], "published_total": 0,
             "published_ids": [], "recoverable_ids": [], "fatal": None}
    _write_report(state)
    for idx, pair in enumerate(pairs, 1):
        entry = {"pair_index": idx, "ids": pair, "claimed": [],
                 "pass": [], "published": [], "review": [], "repair": [],
                 "blocked": [], "publish_rc": 0, "status": "pending"}
        state["pairs"].append(entry)
        _write_report(state)
        try:
            rows = load_rows()
            st = {r["article_id"]: (r.get("status") or "").strip()
                  for r in rows if r["article_id"] in pair}
            # already-PASS rows publish directly (never re-QA'd)
            direct = [a for a in pair if st.get(a) == "PASS"]
            qa_ids = [a for a in pair if st.get(a) != "PASS"]
            if qa_ids and mode == "new":
                rc = _pair_claim(batch_id, qa_ids)
                if rc.returncode != 0:
                    entry["status"] = "claim_failed"
                    state["recoverable_ids"] += qa_ids
                    _write_report(state)
                    continue
                entry["claimed"] = qa_ids
            if qa_ids:
                qa = _pair_qa(batch_id, qa_ids)
                code = qa.returncode
                rows = load_rows()
                st = {r["article_id"]: (r.get("status") or "").strip()
                      for r in rows if r["article_id"] in pair}
                entry["pass"] = [a for a in pair if st.get(a) == "PASS"]
                entry["review"] = [a for a in pair if st.get(a) == "REVIEW"]
                entry["repair"] = [a for a in pair if st.get(a) == "REPAIR"]
                entry["blocked"] = [a for a in pair
                                    if st.get(a) == "BLOCKED"]
                if code not in QA_OK_EXITS:
                    entry["status"] = "qa_failed"
                    entry["qa_rc"] = code
                    state["recoverable_ids"] += [
                        a for a in qa_ids if a not in entry["pass"]]
                    _write_report(state)
                    continue
            publish_ids = sorted(set(entry["pass"]) | set(direct))
            if publish_ids:
                ids_csv = ",".join(publish_ids)
                drc = _pair_publish(ids_csv, dry_run=True)
                if drc.returncode != 0:
                    entry["status"] = "publish_dry_run_failed"
                    entry["publish_rc"] = drc.returncode
                    state["recoverable_ids"] += publish_ids
                    _write_report(state)
                    continue
                prc = _pair_publish(ids_csv)
                entry["publish_rc"] = prc.returncode
                rows = load_rows()
                st2 = {r["article_id"]: (r.get("status") or "").strip()
                       for r in rows if r["article_id"] in pair}
                pass_ids = [a for a in publish_ids
                            if st2.get(a) == "PUBLISHED"]
                entry["published"] = pass_ids
                state["published_total"] += len(entry["published"])
            recoverable = [a for a in pair if a not in entry["published"]]
            state["recoverable_ids"] += recoverable
            entry["status"] = ("published" if not recoverable
                               else "partial" if entry["published"]
                               else "recoverable")
            _write_report(state)
        except Exception as e:  # noqa: BLE001 - pair isolation contract
            entry["status"] = "error"
            entry["error"] = str(e)
            state["recoverable_ids"] += [
                a for a in pair if a not in entry["published"]]
            _write_report(state)
            continue
    state["recoverable_ids"] = sorted(set(state["recoverable_ids"]))
    state["published_ids"] = sorted({a for e in state["pairs"]
                                     for a in e["published"]})
    state["finished"] = _now()
    _write_report(state)
    summary = {"batch": batch_id, "mode": mode, "queue": queue,
               "pairs": len(pairs),
               "published_total": state["published_total"],
               "published_ids": state["published_ids"],
               "recoverable_ids": state["recoverable_ids"],
               "report": str(report_path())}
    print("SHOP_FACTORY_QUEUE_DONE " + json.dumps(summary,
                                                 ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("command", choices=["run"])
    ap.add_argument("--batch", required=True)
    ap.add_argument("--mode", choices=["new", "repair"], required=True)
    ap.add_argument("--ids", required=True,
                    help="comma-separated queue ids (matrix order "
                         "revalidated)")
    ap.add_argument("--pair-size", type=int, default=PAIR_SIZE)
    args = ap.parse_args()
    ids = [v.strip() for v in args.ids.split(",") if v.strip()]
    if args.command == "run":
        return run_queue(args.batch, args.mode, ids,
                         pair_size=args.pair_size)
    return 2


if __name__ == "__main__":
    sys.exit(main())
