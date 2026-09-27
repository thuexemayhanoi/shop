#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotent, stale-safe requeue for the article factory.

Semantics (repo truth > old commands):
  FAIL    -> REPAIR  (budget enforced: total repair attempts may never
                       exceed MAX_REPAIR_ATTEMPTS)
  BLOCKED -> REPAIR  ONLY with --allow-blocked AND a fresh QA precheck
                       (zero validation errors and zero critical
                       failures on the current article file). The
                       repair:N note is NOT re-incremented: the blocker
                       was an external condition, not a QA attempt.
  REPAIR  -> skip (idempotent no-op, reported as skipped)
  PASS / PUBLISHED / any other status -> refused, never touched
  unknown article_id -> refused (stale command IDs never crash the run)

Exit codes:
  0  ok (some rows requeued or nothing to do)
  1  no ids given
  2  invalid usage (argparse)
  3  refusals recorded (not fatal; refused rows are reported)
  4  fatal (matrix write failed after precheck passed)

The tool is idempotent: rerunning the same command requeues nothing new
and can never regress PASS -> REPAIR.
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


def _article_file(repo_root, out_path):
    final = os.path.join(repo_root, out_path)
    draft = os.path.join(repo_root, rb.draft_rel(out_path))
    if os.path.isfile(final):
        return final
    if os.path.isfile(draft):
        return draft
    return None


def qa_precheck_ok(repo_root, out_path):
    """Fresh QA precheck on the CURRENT article file.

    Returns (ok, reason). ok means: full canonical validation produced
    zero validation errors and zero critical scorer failures, i.e. the
    article is plausibly PASS material already and the blocker was an
    external condition. Never fabricates a result: if the article file
    is missing the precheck fails.
    """
    path = _article_file(repo_root, out_path or "")
    if path is None:
        return False, "article file missing on disk"
    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        res = rb.qa_article(path, matrix, ownership, facts, rubric)
    except Exception as exc:  # precheck itself failed -> refuse
        return False, "precheck error: %s" % exc
    errors = res.get("validation_errors") or []
    criticals = res.get("critical_failures") or []
    if errors or criticals:
        return False, ("precheck failed: %d validation errors, "
                       "%d critical failures" % (len(errors), len(criticals)))
    return True, "precheck ok"


def requeue_updates(rows, ids, repo_root, allow_blocked=False):
    """Return (updates, skipped, refusals).

    updates  maps article_id -> matrix update (only eligible rows)
    skipped   lists rows safely left untouched (e.g. already REPAIR)
    refusals lists rows that must not be requeued and why
    """
    by_id = {r["article_id"]: r for r in rows}
    updates, skipped, refusals = {}, [], []
    for aid in ids:
        row = by_id.get(aid)
        if row is None:
            refusals.append({"article_id": aid, "reason": "unknown article_id"})
            continue
        status = (row.get("status") or "").strip()
        out_path = (row.get("output_path") or "").strip()
        if status in ("PASS", "PUBLISHED"):
            refusals.append({"article_id": aid,
                             "reason": "already %s; never requeued" % status})
            continue
        if status == "REPAIR":
            skipped.append({"article_id": aid,
                            "reason": "already REPAIR (idempotent no-op)"})
            continue
        if status != "FAIL" and status != "BLOCKED":
            refusals.append({"article_id": aid,
                             "reason": "not requeueable (status=%s)" % status})
            continue
        if not (out_path and _article_file(repo_root, out_path)):
            refusals.append({"article_id": aid,
                             "reason": "article file missing on disk"})
            continue
        if status == "BLOCKED":
            if not allow_blocked:
                refusals.append({
                    "article_id": aid,
                    "reason": "BLOCKED without --allow-blocked"})
                continue
            ok, reason = qa_precheck_ok(repo_root, out_path)
            if not ok:
                refusals.append({"article_id": aid, "reason": reason})
                continue
            # External blocker resolved and content already QA-clean:
            # unblock without consuming a repair attempt.
            updates[aid] = {
                "status": "REPAIR",
                "quality_status": "REPAIR",
                "notes": (row.get("notes") or "").strip(),
                "last_checked": rb.today(),
            }
            continue
        # FAIL -> REPAIR, budget enforced
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
    return updates, skipped, refusals


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Idempotent, stale-safe FAIL/BLOCKED -> REPAIR requeue")
    ap.add_argument("--ids", required=True, help="comma-separated article ids")
    ap.add_argument("--allow-blocked", action="store_true",
                    help="permit BLOCKED -> REPAIR when a fresh QA precheck "
                         "passes on the current article file")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the would-be updates without writing")
    args = ap.parse_args(argv)
    ids = parse_ids(args.ids)
    if not ids:
        print("no ids given")
        return 1
    matrix = lib.load_matrix()
    updates, skipped, refusals = requeue_updates(
        matrix, ids, lib.ROOT, allow_blocked=args.allow_blocked)
    print(json.dumps({"requeued": sorted(updates),
                      "skipped": skipped,
                      "refused": refusals,
                      "dry_run": bool(args.dry_run)},
                     ensure_ascii=False, indent=2))
    if updates and not args.dry_run:
        try:
            rb.update_matrix_statuses(lib.ROOT, updates)
        except Exception as exc:
            print("FATAL: matrix update failed: %s" % exc)
            return 4
    if refusals:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
