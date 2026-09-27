import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import article_lib as lib
import requeue_rows as rq


class TestRequeueToolSemantics(unittest.TestCase):
    """Regression test: requeue_updates must be pure and must requeue
    FAIL rows whose article exists at the draft or final path."""

    IDS = ["HD-0034", "HD-0035", "KN-0035"]

    def test_requeue_updates_pure_and_correct(self):
        rows = lib.load_matrix()
        updates, refusals = rq.requeue_updates(rows, self.IDS, lib.ROOT)
        self.assertIsInstance(updates, dict)
        self.assertIsInstance(refusals, list)
        refused_ids = [r.get("article_id") for r in refusals]
        for aid in self.IDS:
            row = next((r for r in rows if r.get("article_id") == aid), None)
            if row is None:
                self.assertIn(aid, refused_ids)
                continue
            status = (row.get("status") or "").strip()
            path = row.get("output_path") or ""
            exists = bool(path) and (
                os.path.isfile(os.path.join(lib.ROOT, path))
                or os.path.isfile(
                    os.path.join(lib.ROOT, rq.rb.draft_rel(path))))
            if status == "FAIL" and exists:
                self.assertIn(aid, updates)
            else:
                self.assertIn(aid, refused_ids)


if __name__ == "__main__":
    unittest.main()
