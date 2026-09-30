#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory_health.py — deterministic factory health evaluator.

Part of the four-layer reliability hardening: a NO-PROGRESS / STALLED
verdict must be EARNED by evidence, not assumed. "Not running" is not
"stalled" — the factory is mostly driven by an EXTERNAL writer, and
WAITING_FOR_WRITER is a legitimate, healthy state.

Statuses (deterministic, in priority order):

  RECOVERY_REQUIRED   a pending transaction marker exists under
                      data/batches/txn/ — run factory --recover first
  LOCKED              a FRESH writer lock is held (another writer owns
                      the batch); a stale lock is reported in details
                      but does not block health (it is reclaimable)
  READY_FOR_PUBLISH   PASS rows with written files exist
  READY_FOR_QA        WRITING rows with written files exist
  WAITING_FOR_WRITER  WRITING rows without files, or PLANNED rows the
                      writer has not claimed yet — legitimate waiting,
                      never reported as stalled by itself
  BLOCKED             FAIL/BLOCKED rows exist and nothing else is
                      actionable (operator attention required)
  COMPLETE            no actionable rows at all
  NO_PROGRESS         compare-mode verdict: the state fingerprint is
                      UNCHANGED since the snapshot while an actionable
                      backlog exists — the operation claimed to do work
                      and did nothing
  HEALTHY             compare-mode verdict: the fingerprint CHANGED
                      (real progress observed) and no problem state

The evaluator is READ-ONLY: it never mutates lib.ROOT, the matrix, the
reports or any lock. The snapshot (--snapshot PATH) only writes its own
JSON file for a later --compare.
"""
import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ACTIVE_STATUSES = ("WRITING", "QA", "REPAIR", "REVIEW")
ACTIONABLE = ("READY_FOR_PUBLISH", "READY_FOR_QA", "WAITING_FOR_WRITER")


def _load_rows(repo_root):
    p = os.path.join(repo_root, "data", "content-matrix.csv")
    with io.open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _is_sample(row):
    return (str(row.get("article_id", "")).upper().startswith("SAMPLE")
            or "SAMPLE" in str(row.get("notes", "")).upper())


def _written(repo_root, output_path):
    path = (output_path or "").strip()
    if not path:
        return False
    return (os.path.isfile(os.path.join(repo_root, path))
            or os.path.isfile(os.path.join(repo_root, "_drafts", path)))


def _read_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _txn_pending(repo_root):
    p = os.path.join(repo_root, "data", "batches", "txn", "txn.json")
    if not os.path.isfile(p):
        return None
    try:
        m = _read_json(p)
    except ValueError:
        return {"state": "CORRUPT"}
    if not isinstance(m, dict):
        return {"state": "CORRUPT"}
    return m


def _writer_lock(repo_root):
    """(lock_or_None, fresh_bool) — stale-tolerant freshness check."""
    p = os.path.join(repo_root, "data", "batches", "writer-lock.json")
    if not os.path.isfile(p):
        return None, False
    try:
        lock = _read_json(p)
    except ValueError:
        return None, False
    if not isinstance(lock, dict) or not lock.get("writer_session"):
        return None, False
    try:
        ts = datetime.datetime.fromisoformat(lock.get("updated_at"))
        if ts.tzinfo is None:
            ts = ts.replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
        age = (datetime.datetime.now(ts.tzinfo) - ts)
        return lock, age < datetime.timedelta(hours=2)
    except (TypeError, ValueError):
        return lock, False


def fingerprint(repo_root):
    """State fingerprint for NO_PROGRESS detection.

    Deliberately EXCLUDES timestamps (generated/updated_at fields change
    on every report rebuild, which must never look like progress). Only
    semantic state counts: row statuses, actionable ids, transaction and
    lock ownership, report counts.
    """
    rows = _load_rows(repo_root)
    prod = [r for r in rows if not _is_sample(r)]
    parts = []
    for r in prod:
        parts.append("%s=%s" % ((r.get("article_id") or "").strip(),
                                (r.get("status") or "").strip()))
    txn = _txn_pending(repo_root)
    parts.append("txn=%s" % ((txn or {}).get("state") if txn else "clean"))
    lock, fresh = _writer_lock(repo_root)
    if lock:
        parts.append("lock=%s:fresh=%s" % (lock.get("writer_session"),
                                           "yes" if fresh else "no"))
    h = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return h, prod


def evaluate(repo_root, compare_snapshot=None):
    """Deterministic health verdict. Returns a JSON-able dict."""
    repo_root = os.path.abspath(repo_root)
    fp, prod = fingerprint(repo_root)

    details = {
        "fingerprint": fp,
        "rows": len(prod),
        "counts": {},
        "ready_for_publish_ids": [],
        "ready_for_qa_ids": [],
        "waiting_for_writer_ids": [],
        "blocked_ids": [],
        "fail_ids": [],
    }
    ready_pub, ready_qa, waiting, blocked, fails = [], [], [], [], []
    for r in prod:
        st = (r.get("status") or "").strip()
        aid = (r.get("article_id") or "").strip()
        details["counts"][st] = details["counts"].get(st, 0) + 1
        if st == "PASS" and _written(repo_root, r.get("output_path")):
            ready_pub.append(aid)
        elif st in ACTIVE_STATUSES and _written(
                repo_root, r.get("output_path")):
            ready_qa.append(aid)
        elif st == "PLANNED" or st in ACTIVE_STATUSES:
            waiting.append(aid)
        elif st == "BLOCKED":
            blocked.append(aid)
        elif st == "FAIL":
            fails.append(aid)
    details["ready_for_publish_ids"] = ready_pub
    details["ready_for_qa_ids"] = ready_qa
    details["waiting_for_writer_ids"] = waiting[:20]
    details["waiting_for_writer_count"] = len(waiting)
    details["blocked_ids"] = blocked
    details["fail_ids"] = fails

    txn = _txn_pending(repo_root)
    lock, fresh = _writer_lock(repo_root)
    details["writer_lock"] = lock
    details["writer_lock_fresh"] = bool(lock and fresh)

    # ---- priority order (see module docstring) ----
    if txn is not None:
        status = "RECOVERY_REQUIRED"
        details["txn"] = txn
    elif lock and fresh:
        status = "LOCKED"
    elif ready_pub:
        status = "READY_FOR_PUBLISH"
    elif ready_qa:
        status = "READY_FOR_QA"
    elif waiting:
        status = "WAITING_FOR_WRITER"
    elif blocked or fails:
        status = "BLOCKED"
    else:
        status = "COMPLETE"

    # ---- compare mode: NO_PROGRESS must be EARNED ----
    if compare_snapshot is not None:
        prev_fp = compare_snapshot.get("fingerprint")
        progressed = (prev_fp is not None and prev_fp != fp)
        if status in ACTIONABLE and not progressed:
            # actionable backlog exists AND nothing changed since the
            # snapshot: the operation that claimed to do work did not
            # move the state — a defect, not "waiting"
            status = "NO_PROGRESS"
        elif status in ACTIONABLE and progressed:
            status = "HEALTHY"

    return {"status": status, "repo_root": repo_root, "details": details}


def main_func(argv=None):
    ap = argparse.ArgumentParser(
        description="Deterministic, read-only factory health verdict.")
    ap.add_argument("--repo-root", default=ROOT,
                    help="repository root to inspect (default: this repo)")
    ap.add_argument("--snapshot", default=None,
                    help="write the current state snapshot to this JSON "
                         "file (for a later --compare)")
    ap.add_argument("--compare", default=None,
                    help="previous snapshot JSON to compare against "
                         "(NO_PROGRESS verdict when nothing changed)")
    args = ap.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    prev = None
    if args.compare:
        try:
            with io.open(args.compare, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError) as e:
            print("::error::cannot read snapshot %s: %s" % (args.compare, e))
            return 2
    result = evaluate(repo_root, compare_snapshot=prev)

    if args.snapshot:
        snap = {"fingerprint": result["details"]["fingerprint"],
                "status": result["status"],
                "repo_root": repo_root}
        d = os.path.dirname(os.path.abspath(args.snapshot))
        if d:
            os.makedirs(d, exist_ok=True)
        with io.open(args.snapshot, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main_func())