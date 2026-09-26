#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Requeue repaired FAIL rows for deterministic re-QA (FAIL -> REPAIR).

The documented factory flow (see run_article_batch.py) is:
    WRITING -> --qa -> PASS / FAIL / REVIEW
            -> (agent repairs the file, <= MAX_REPAIR_ATTEMPTS,
                notes carry repair:N)
            -> PASS | BLOCKED
select_qa_rows() re-QAs WRITING/QA/REPAIR/REVIEW rows, so after the
operator has meaningfully repaired a failed article this tool moves the
FAIL row to REPAIR with an incremented repair:N note.

Safety rules (never bypassed):
  - only FAIL rows are requeued; one requeue = one repair attempt
  - the article file must exist on disk at the REAL repository path
  - hard budget: total repair attempts may never exceed MAX_REPAIR_ATTEMPTS
  - nothing about QA is skipped: the next --qa run applies the full
    canonical validation, source gate and scorer to the repaired file
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import article_lib as lib
import run_article_batch as rb

MAX_REPAIR_ATTEMPTS = rb.MAX_REPAIR_ATTEMPTS


def parse_ids(raw):
    ids = []
    for part in re.split(r"[,\s]+", raw or ""):
        part = part.strip().upper()
        if part:
            ids.append(part)
    return ids


def merge_repair_note(notes, n):
    marker = "repair:%d" % n
    notes = (notes or "").strip()
    if re.search(r"repair:\d+", notes):
        return re.sub(r"repair:\d+", marker, notes)
    return (notes + "; " if notes else "") + marker


def requeue_updates(rows, ids, repo_root):
    """Return (updates, refusals). updates maps article_id -> ledger update."""
    by_id = {r["article_id"]: r for r in rows}
    updates, refusals = {}, []
    for aid in ids:
        row = by_id.get(aid)
        if row is None:
            refusals.append({"article_id": aid, "reason": "unknown article_id"})
            continue
        status = (row.get("status") or "").strip()
        if status != "FAIL":
            refusals.append({"article_id": aid,
                             "reason": "not FAIL (status=%s)" % status})
            continue
        path = os.path.join(repo_root, row.get("output_path") or "")
        if not (row.get("output_path") and os.path.isfile(path)):
            refusals.append({"article_id": aid,
                             "reason": "article file missing on disk"})
            continue
        attempts = rb.repair_attempts(row.get("notes") or "")
        if attempts >= MAX_REPAIR_ATTEMPTS:
            refusals.append({"article_id": aid,
                             "reason": "repair budget exhausted (%d attempts)"
                                       % attempts})
            continue
        updates[aid] = {
            "status": "REPAIR",
            "quality_status": "REPAIR",
            "notes": merge_repair_note(row.get("notes"), attempts + 1),
            "last_checked": rb.today(),
        }
    return updates, refusals


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="FAIL -> REPAIR requeue (repair budget enforced)")
    ap.add_argument("--ids", required=True, help="comma-separated article ids")
    args = ap.parse_args(argv)
    ids = parse_ids(args.ids)
    if not ids:
        print("no ids given")
        return 2
    matrix = lib.load_matrix()
    updates, refusals = requeue_updates(matrix, ids, lib.ROOT)
    if updates:
        rb.update_matrix_statuses(lib.ROOT, updates)
    print(json.dumps({"requeued": sorted(updates), "refused": refusals},
                     ensure_ascii=False, indent=2))
    if refusals:
        return 3
    return 0 if updates else 1


if __name__ == "__main__":
    sys.exit(main())
