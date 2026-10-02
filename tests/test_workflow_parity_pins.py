#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract pins for the vanchinh workflow-parity port.

These tests freeze the two behavioral gaps found in the
thuexemayhanoi/vanchinh -> thuexemayhanoi/shop workflow audit, so a
future edit cannot silently regress them:

  - article-batch must end fail-closed: no pending transaction marker
    and no leftover batch lock after a batch run (same postcondition as
    factory-publish-verify; recovery stays a manual factory action).
  - site-quality must run the per-page legacy audit
    (scripts/audit_legacy_pages.py) inside a read-only job.
  - the audit tool must keep sourcing its facts from the canonical
    config (business-facts.json), never hard-coded claims.
"""
import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class WorkflowParityPins(unittest.TestCase):

    def test_article_batch_asserts_no_pending_txn_or_lock(self):
        s = _read(".github/workflows/article-batch.yml")
        self.assertIn("data/batches/txn/txn.json", s)
        self.assertIn("data/batches/*.lock", s)
        # recovery is a manual factory action, not a batch side effect
        self.assertNotIn("factory.mjs --recover", s)

    def test_site_quality_runs_legacy_page_audit_read_only(self):
        s = _read(".github/workflows/site-quality.yml")
        self.assertIn("scripts/audit_legacy_pages.py", s)
        self.assertIn("contents: read", s)
        self.assertNotIn("contents: write", s)
        self.assertNotIn("git push", s)

    def test_legacy_audit_sources_facts_from_canonical_config(self):
        s = _read("scripts/audit_legacy_pages.py")
        self.assertIn("business-facts.json", s)


if __name__ == "__main__":
    unittest.main()
