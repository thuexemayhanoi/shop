#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scripts/requeue_rows.py (FAIL -> REPAIR requeue, budget enforced)."""
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
    def _row(self, status="FAIL", notes="", path="tests/fixtures/good.html"):
        return {"article_id": "ZZ-0001", "status": status, "notes": notes,
                "output_path": path}

    def test_fail_row_with_file_is_requeued(self):
        updates, refusals = rq.requeue_updates([self._row()], ["ZZ-0001"], ROOT)
        self.assertEqual(refusals, [])
        self.assertEqual(updates["ZZ-0001"]["status"], "REPAIR")
        self.assertEqual(updates["ZZ-0001"]["notes"], "repair:1")

    def test_budget_exhausted_refused(self):
        updates, refusals = rq.requeue_updates(
            [self._row(notes="repair:3")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("budget" in r["reason"] for r in refusals))

    def test_non_fail_status_refused(self):
        updates, refusals = rq.requeue_updates(
            [self._row(status="PASS")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("not FAIL" in r["reason"] for r in refusals))

    def test_missing_file_refused(self):
        updates, refusals = rq.requeue_updates(
            [self._row(path="nope/missing.html")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(any("missing" in r["reason"] for r in refusals))

    def test_unknown_id_refused(self):
        updates, refusals = rq.requeue_updates([self._row()], ["ZZ-9999"], ROOT)
        self.assertEqual(updates, {})
        self.assertTrue(refusals)

    def test_second_requeue_increments_then_exhausts(self):
        updates, _ = rq.requeue_updates([self._row(notes="repair:2")],
                                        ["ZZ-0001"], ROOT)
        self.assertEqual(updates["ZZ-0001"]["notes"], "repair:3")
        updates2, refusals = rq.requeue_updates(
            [self._row(notes="repair:3")], ["ZZ-0001"], ROOT)
        self.assertEqual(updates2, {})
        self.assertTrue(refusals)


if __name__ == "__main__":
    unittest.main()
