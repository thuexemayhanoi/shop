#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scripts/requeue_rows.py (idempotent, stale-safe requeue)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import requeue_rows as rq


class MergeNoteTests(unittest.TestCase):
    def test_appends_marker_to_empty_notes(self):
        self.assertEqual(rq.merge_repair_note("", 1), "repair:1")

    def test_replaces_existing_marker(self):
        self.assertEqual(rq.merge_repair_note("repair:1", 2), "repair:2")

    def test_keeps_other_notes(self):
        self.assertEqual(rq.merge_repair_note("qa note; repair:1", 2),
                         "qa note; repair:2")
        self.assertEqual(rq.merge_repair_note("qa note", 1),
                         "qa note; repair:1")


class RequeueTests(unittest.TestCase):
    def _row(self, aid="ZZ-0001", status="FAIL", notes="",
             path="tests/fixtures/good.html"):
        return {"article_id": aid, "status": status, "notes": notes,
                "output_path": path}

    def test_fail_row_with_file_is_requeued(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row()], ["ZZ-0001"], ROOT)
        self.assertEqual(refusals, [])
        self.assertEqual(skipped, [])
        self.assertEqual(updates["ZZ-0001"]["status"], "REPAIR")
        self.assertEqual(updates["ZZ-0001"]["notes"], "repair:1")

    def test_budget_exhausted_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(notes="repair:3")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("budget" in r["reason"] for r in refusals))

    def test_pass_status_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(status="PASS")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("PASS" in r["reason"] for r in refusals))

    def test_published_status_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(status="PUBLISHED")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("PUBLISHED" in r["reason"] for r in refusals))

    def test_repair_status_is_idempotent_noop(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(status="REPAIR", notes="repair:2")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertEqual(refusals, [])
        self.assertEqual([s["article_id"] for s in skipped], ["ZZ-0001"])
        self.assertEqual(skipped[0]["reason"],
                         "already REPAIR (idempotent no-op)")

    def test_missing_file_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(path="nope/missing.html")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("missing" in r["reason"] for r in refusals))

    def test_unknown_id_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row()], ["ZZ-9999"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("unknown article_id" in r["reason"]
                            for r in refusals))

    def test_blocked_without_flag_refused(self):
        updates, skipped, refusals = rq.requeue_updates(
            [self._row(status="BLOCKED", notes="repair:3")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("--allow-blocked" in r["reason"]
                            for r in refusals))

    def test_blocked_with_flag_and_precheck_ok_requeued(self):
        row = self._row(status="BLOCKED", notes="repair:3; hard qa fail")
        original = rq.qa_precheck_ok
        rq.qa_precheck_ok = lambda root, path: (True, "precheck ok")
        try:
            updates, skipped, refusals = rq.requeue_updates(
                [row], ["ZZ-0001"], ROOT, allow_blocked=True)
        finally:
            rq.qa_precheck_ok = original
        self.assertEqual(refusals, [])
        self.assertEqual(updates["ZZ-0001"]["status"], "REPAIR")
        self.assertEqual(updates["ZZ-0001"]["notes"], "repair:3; hard qa fail")

    def test_blocked_with_flag_and_precheck_fail_refused(self):
        row = self._row(status="BLOCKED", notes="repair:3")
        original = rq.qa_precheck_ok
        rq.qa_precheck_ok = lambda root, path: (False, "precheck failed: 1 "
                                                  "validation errors, 0 "
                                                  "critical failures")
        try:
            updates, skipped, refusals = rq.requeue_updates(
                [row], ["ZZ-0001"], ROOT, allow_blocked=True)
        finally:
            rq.qa_precheck_ok = original
        self.assertEqual(updates, {})
        self.assertTrue(any("precheck failed" in r["reason"]
                            for r in refusals))

    def test_mixed_stale_and_valid_ids_no_partial_corruption(self):
        rows = [
            self._row(aid="ZZ-0100", status="FAIL"),
            self._row(aid="ZZ-0101", status="PASS"),
            self._row(aid="ZZ-0102", status="PUBLISHED"),
            self._row(aid="ZZ-0103", status="REPAIR", notes="repair:1"),
        ]
        ids = ["ZZ-0100", "ZZ-0101", "ZZ-0102", "ZZ-0103", "ZZ-9999"]
        updates, skipped, refusals = rq.requeue_updates(rows, ids, ROOT)
        self.assertEqual(sorted(updates), ["ZZ-0100"])
        self.assertEqual(updates["ZZ-0100"]["notes"], "repair:1")
        self.assertEqual([s["article_id"] for s in skipped], ["ZZ-0103"])
        refused_ids = sorted(r["article_id"] for r in refusals)
        self.assertEqual(refused_ids, ["ZZ-0101", "ZZ-0102", "ZZ-9999"])


if __name__ == "__main__":
    unittest.main()
