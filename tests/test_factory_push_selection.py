#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Push-scope selection regression tests (Simple Production Mode).

Pins the event-driven factory-publish contract of
scripts/factory_push_selection.py:

  * exact two-file NEW push -> claim exactly those ids (no blind claim)
  * a PLANNED row whose file is NOT in the push is NEVER claimed
  * REPAIR push (touched WRITING row) -> scoped QA of exactly that id;
    NEVER claims fresh PLANNED rows
  * a touched already-PASS row publishes directly (never re-QA'd)
  * PUBLISHED-row modifications are IGNORED (never claim/QA/publish)
  * BACKLOG: PLANNED rows with existing files, no touched files ->
    deterministic first-50 by article_id
  * SKIP when nothing to do (tooling-only push / factory state commit
    re-triggering on promoted PUBLISHED files): no work, no recursion
  * REFUSE: > 50 new article files in one push
  * REFUSE: touching active rows of another batch while another batch
    is active
  * the writer's drafts under _drafts/<output_path> map back to the
    matrix output_path (deploy-gate drafts model)

The selector derives truth from lib.ROOT (like run_article_batch), so
the sandbox fixture redirects article_lib.ROOT to a temp repository.
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib                  # noqa: E402
import factory_push_selection as fps       # noqa: E402

HEADER = None  # copied from the real matrix at fixture build time


def _fixture_rows():
    """A minimal deterministic matrix (schema of the real ledger)."""
    rows = [
        # BATCH-001 (active: has WRITING rows)
        ("KN-0001", "PLANNED", "cam-nang/kinh-nghiem/kn-0001.html", "BATCH-001", True),
        ("KN-0002", "PLANNED", "cam-nang/kinh-nghiem/kn-0002.html", "BATCH-001", True),
        ("KN-0003", "PLANNED", "cam-nang/kinh-nghiem/kn-0003.html", "BATCH-001", False),
        ("KN-0004", "WRITING", "cam-nang/kinh-nghiem/kn-0004.html", "BATCH-001", True),
        ("KN-0005", "PASS", "cam-nang/kinh-nghiem/kn-0005.html", "BATCH-001", True),
        ("KN-0006", "PUBLISHED", "cam-nang/kinh-nghiem/kn-0006.html", "BATCH-001", "final"),
        # BATCH-002
        ("HD-0001", "PLANNED", "cam-nang/hoi-dap/hd-0001.html", "BATCH-002", True),
    ]
    return rows


class SelectorTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        t = cls.tmp
        os.makedirs(os.path.join(t, "config"))
        for name in ("article-rubric.json", "business-facts.json",
                     "seo-ownership.json", "site.json"):
            src = os.path.join(ROOT, "config", name)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(t, "config", name))
        os.makedirs(os.path.join(t, "data"))
        with io.open(os.path.join(ROOT, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            header = next(csv.reader(f))
        HEADER = header
        with io.open(os.path.join(t, "data", "content-matrix.csv"), "w",
                     encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for (aid, status, op, batch, has_file) in _fixture_rows():
                r = [""] * len(header)
                r[header.index("article_id")] = aid
                r[header.index("status")] = status
                r[header.index("category")] = "Kinh nghiệm"
                r[header.index("primary_keyword")] = "kw " + aid
                r[header.index("working_title")] = "Title " + aid
                r[header.index("slug")] = aid.lower()
                r[header.index("output_path")] = op
                r[header.index("parent_hub")] = "kinhnghiem.html"
                r[header.index("batch_id")] = batch
                w.writerow(r)
            # sample rows are excluded by the selector
            r = [""] * len(header)
            r[header.index("article_id")] = "SAMPLE-KN-01"
            r[header.index("status")] = "PLANNED"
            r[header.index("output_path")] = "cam-nang/kinh-nghiem/sample.html"
            r[header.index("batch_id")] = "BATCH-001"
            w.writerow(r)
        # article files: drafts for non-published rows, final for published
        for (aid, status, op, batch, has_file) in _fixture_rows():
            if has_file is False:
                continue
            rel = op if has_file == "final" else os.path.join("_drafts", op)
            p = os.path.join(t, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            io.open(p, "w", encoding="utf-8").write(
                "<html><body>%s</body></html>" % aid)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _select(self, added=(), modified=()):
        old = lib.ROOT
        lib.ROOT = self.tmp
        try:
            return fps.select(list(added), list(modified))
        finally:
            lib.ROOT = old

    # ---------------------------------------------------------- NEW mode

    def test_exact_two_file_new_push_claims_exactly_those_ids(self):
        sel = self._select(added=[
            "_drafts/cam-nang/kinh-nghiem/kn-0001.html",
            "_drafts/cam-nang/kinh-nghiem/kn-0002.html",
        ])
        self.assertEqual(sel["mode"], "new")
        self.assertEqual(sel["batch"], "BATCH-001")
        self.assertEqual(sel["claim_ids"], ["KN-0001", "KN-0002"])
        self.assertEqual(sel["qa_ids"], ["KN-0001", "KN-0002"])
        self.assertEqual(sel["publish_ids"], [])
        self.assertTrue(sel["proceed"])
        self.assertIsNone(sel["refuse"])

    def test_no_blind_claim_planned_row_without_pushed_file(self):
        # only kn-0001's draft is in the push; kn-0003 has NO file and
        # kn-0002 (file exists, not in push) is NEVER claimed
        sel = self._select(added=[
            "_drafts/cam-nang/kinh-nghiem/kn-0001.html",
        ])
        self.assertEqual(sel["claim_ids"], ["KN-0001"])
        self.assertNotIn("KN-0002", sel["claim_ids"])
        self.assertNotIn("KN-0003", sel["claim_ids"])

    def test_final_path_also_maps_for_new_push(self):
        # a PLANNED row whose file sits at the FINAL path (pre-promotion
        # backlog) maps through the same output_path
        sel = self._select(added=[
            "cam-nang/kinh-nghiem/kn-0002.html",
        ])
        self.assertEqual(sel["mode"], "new")
        self.assertEqual(sel["claim_ids"], ["KN-0002"])

    # ------------------------------------------------------- REPAIR mode

    def test_repair_push_scopes_qa_to_touched_active_row(self):
        sel = self._select(modified=[
            "_drafts/cam-nang/kinh-nghiem/kn-0004.html",
        ])
        self.assertEqual(sel["mode"], "repair")
        self.assertEqual(sel["qa_ids"], ["KN-0004"])
        self.assertEqual(sel["claim_ids"], [])
        self.assertEqual(sel["publish_ids"], [])

    def test_repair_push_never_claims_fresh_planned_rows(self):
        sel = self._select(modified=[
            "_drafts/cam-nang/kinh-nghiem/kn-0004.html",
            "_drafts/cam-nang/kinh-nghiem/kn-0005.html",
        ])
        self.assertEqual(sel["mode"], "repair")
        self.assertEqual(sel["qa_ids"], ["KN-0004"])
        self.assertEqual(sel["claim_ids"], [])
        # already-PASS row touched -> publish directly, never re-QA'd
        self.assertEqual(sel["publish_ids"], ["KN-0005"])
        self.assertNotIn("KN-0005", sel["qa_ids"])

    def test_new_plus_repair_in_one_push(self):
        sel = self._select(added=[
            "_drafts/cam-nang/kinh-nghiem/kn-0001.html",
        ], modified=[
            "_drafts/cam-nang/kinh-nghiem/kn-0004.html",
        ])
        self.assertEqual(sel["mode"], "new")
        self.assertEqual(sel["claim_ids"], ["KN-0001"])
        self.assertEqual(sel["qa_ids"], ["KN-0001", "KN-0004"])

    def _hide_backlog(self):
        """Temporarily remove the fixture's PLANNED-with-file drafts so a
        push can be asserted to SKIP (no backlog recovery pending)."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            moved = []
            for aid in ("KN-0001", "KN-0002"):
                src = os.path.join(self.tmp, "_drafts", "cam-nang",
                                   "kinh-nghiem", aid.lower() + ".html")
                dst = src + ".hidden"
                if os.path.isfile(src):
                    os.rename(src, dst)
                    moved.append((dst, src))
            try:
                yield
            finally:
                for dst, src in moved:
                    os.rename(dst, src)

        return _ctx()

    # ----------------------------------------------- PUBLISHED-row edits

    def test_published_row_modification_is_ignored(self):
        with self._hide_backlog():
            sel = self._select(modified=[
                "cam-nang/kinh-nghiem/kn-0006.html",
            ])
        self.assertEqual(sel["mode"], "skip")
        self.assertFalse(sel["proceed"])
        self.assertEqual(sel["published_edits"],
                         ["cam-nang/kinh-nghiem/kn-0006.html"])
        self.assertEqual(sel["claim_ids"] + sel["qa_ids"]
                         + sel["publish_ids"], [])

    def test_published_row_edit_never_claims_publishes_or_qas(self):
        # even WITH backlog pending, the PUBLISHED-row edit itself never
        # becomes claim/QA/publish scope (backlog is the only work)
        sel = self._select(modified=[
            "cam-nang/kinh-nghiem/kn-0006.html",
        ])
        self.assertEqual(sel["published_edits"],
                         ["cam-nang/kinh-nghiem/kn-0006.html"])
        self.assertNotIn("KN-0006", sel["claim_ids"])
        self.assertNotIn("KN-0006", sel["qa_ids"])
        self.assertNotIn("KN-0006", sel["publish_ids"])

    # ------------------------------------------------------------ BACKLOG

    def test_backlog_recovery_planned_rows_with_existing_files(self):
        # nothing touched, but PLANNED rows already have draft files
        sel = self._select()
        self.assertEqual(sel["mode"], "backlog")
        self.assertEqual(sel["claim_ids"], ["KN-0001", "KN-0002"])
        self.assertEqual(sel["qa_ids"], ["KN-0001", "KN-0002"])

    # ---------------------------------------------------------------- caps

    def test_refuse_more_than_50_new_article_files(self):
        # 51 DISTINCT new article files in one push -> refuse
        import csv as _csv
        added = []
        for i in range(51):
            aid = "KN-1%03d" % i
            op = "cam-nang/kinh-nghiem/%s.html" % aid.lower()
            dp = os.path.join(self.tmp, "_drafts", op)
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            io.open(dp, "w", encoding="utf-8").write("<html>%s</html>" % aid)
            added.append("_drafts/" + op)
        mp = os.path.join(self.tmp, "data", "content-matrix.csv")
        with io.open(mp, encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        header = rows[0]
        for i in range(51):
            aid = "KN-1%03d" % i
            r = [""] * len(header)
            r[header.index("article_id")] = aid
            r[header.index("status")] = "PLANNED"
            r[header.index("category")] = "Kinh nghiệm"
            r[header.index("primary_keyword")] = "kw " + aid
            r[header.index("slug")] = aid.lower()
            r[header.index("output_path")] = (
                "cam-nang/kinh-nghiem/%s.html" % aid.lower())
            r[header.index("parent_hub")] = "kinhnghiem.html"
            r[header.index("batch_id")] = "BATCH-001"
            rows.append(r)
        with io.open(mp, "w", encoding="utf-8", newline="") as f:
            _csv.writer(f).writerows(rows)
        try:
            sel = self._select(added=added)
            self.assertIsNotNone(sel["refuse"])
            self.assertIn("max 50", sel["refuse"])
            self.assertFalse(sel["proceed"])
        finally:
            # restore the shared fixture (later tests assert SKIP modes
            # that must not see these 51 backlog rows)
            with io.open(mp, "w", encoding="utf-8", newline="") as f:
                _csv.writer(f).writerows(rows[:9])
            for i in range(51):
                op = ("cam-nang/kinh-nghiem/kn-1%03d.html" % i)
                dp = os.path.join(self.tmp, "_drafts", op)
                if os.path.isfile(dp):
                    os.remove(dp)

    def test_refuse_touching_rows_of_another_batch(self):
        # HD-0001 is a PLANNED row of BATCH-002 while BATCH-001 is active
        sel = self._select(added=[
            "_drafts/cam-nang/hoi-dap/hd-0001.html",
        ])
        self.assertIsNotNone(sel["refuse"])
        self.assertIn("active batch", sel["refuse"])
        self.assertFalse(sel["proceed"])

    # ---------------------------------------------------------------- skip

    def test_tooling_only_push_skips_with_no_recursion(self):
        # a factory state commit touches promoted PUBLISHED files only:
        # no claim, no QA, no publish - the workflow exits bounded
        with self._hide_backlog():
            sel = self._select(added=[
                "cam-nang/kinh-nghiem/kn-0006.html",
            ], modified=[
                "data/content-matrix.csv",
                "sitemap.xml",
            ])
        self.assertEqual(sel["mode"], "skip")
        self.assertFalse(sel["proceed"])

    def test_unmapped_article_paths_are_audit_only(self):
        sel = self._select(added=[
            "_drafts/cam-nang/kinh-nghiem/unknown-row.html",
        ])
        self.assertEqual(sel["unmapped_paths"],
                         ["_drafts/cam-nang/kinh-nghiem/unknown-row.html"])
        self.assertIsNone(sel["refuse"])
        self.assertEqual(sel["mode"], "backlog")


class DispatchAndCliTests(unittest.TestCase):
    def test_cli_emits_json_and_exit_3_on_refuse(self):
        import subprocess
        # CLI on the REAL repository: an empty touched list is a clean
        # skip (exit 0) and the output is valid JSON with the contract
        # keys. (The real repo's active batch has no PLANNED rows with
        # files, so this is deterministic: skip or backlog, no refuse.)
        empty = os.path.join(tempfile.mkdtemp(), "empty.txt")
        io.open(empty, "w").close()
        try:
            p = subprocess.run(
                [sys.executable,
                 os.path.join(SCRIPTS, "factory_push_selection.py"),
                 "--added", empty, "--modified", empty],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0)
            out = json.loads(p.stdout)
            for key in ("proceed", "mode", "batch", "claim_ids",
                        "qa_ids", "publish_ids", "refuse"):
                self.assertIn(key, out)
            self.assertIn(out["mode"], ("skip", "backlog"))
            self.assertIsNone(out["refuse"])
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
