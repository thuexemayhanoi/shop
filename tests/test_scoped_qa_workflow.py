#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused tests for the scoped-QA workflow hardening (2026-09-28).

Covers the approved verification list:
  1. scope selection picks exactly the right articles to check,
  2. a shared-config change triggers FULL,
  3. old QA evidence is invalidated by content / rubric / validator
     changes (never reused for changed content),
  4. progress stays in sync after QA (a QA run creating 5 PASS rows is
     reflected identically in factory-progress.json and the batch report),
  5. word counting counts visible main content only and separates
     not-yet-published rows (new band) from PUBLISHED rows (legacy band),
  6. the publish gate still refuses/blocks bad articles and honours the
     scoped --ids contract.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))
import article_lib as lib  # noqa: E402
import qa_scope  # noqa: E402
import run_article_batch as rb  # noqa: E402

ROOT = lib.ROOT
EVIDENCE_FILE = os.path.join(ROOT, "reports", "article-quality",
                             "qa-evidence.json")


def _draft_rel(row):
    return os.path.join("_drafts", (row.get("output_path") or "").lstrip("/"))


def _first_pass_draft_row(matrix):
    for r in matrix:
        if (r.get("status") or "").strip() == "PASS" \
                and os.path.isfile(os.path.join(ROOT, _draft_rel(r))):
            return r
    return None


class ScopedQATestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.draft_row = _first_pass_draft_row(cls.matrix)
        if cls.draft_row is None:
            raise unittest.SkipTest("no PASS draft row available")


class ScopeSelectionTests(ScopedQATestCase):
    """Verification 1 + 2: exactly the right articles, FULL on shared
    config changes."""

    def test_draft_only_change_selects_only_that_draft(self):
        changed = [_draft_rel(self.draft_row)]
        res = qa_scope.select_scope(changed, self.matrix, ROOT)
        self.assertEqual(res["scope"], "changed")
        self.assertEqual(res["candidates"],
                         [os.path.join(ROOT, _draft_rel(self.draft_row))])

    def test_report_only_change_has_no_candidates(self):
        res = qa_scope.select_scope(
            ["reports/batches/factory-progress.json",
             "reports/batches/BATCH-010.md"], self.matrix, ROOT)
        self.assertEqual(res["scope"], "changed")
        self.assertEqual(res["candidates"], [])
        self.assertEqual(res["checked"], [])

    def test_published_article_change_selects_it(self):
        pub = next(r for r in self.matrix if r["status"] == "PUBLISHED")
        res = qa_scope.select_scope([pub["output_path"]], self.matrix, ROOT)
        self.assertEqual(res["scope"], "changed")
        self.assertEqual(res["candidates"],
                         [os.path.join(ROOT, pub["output_path"])])

    def test_draft_and_published_changes_select_both(self):
        pub = next(r for r in self.matrix if r["status"] == "PUBLISHED")
        res = qa_scope.select_scope([_draft_rel(self.draft_row),
                                     pub["output_path"]], self.matrix, ROOT)
        self.assertEqual(res["scope"], "changed")
        self.assertEqual(len(res["candidates"]), 2)

    def _assert_full(self, changed):
        res = qa_scope.select_scope(changed, self.matrix, ROOT)
        self.assertEqual(res["scope"], "full", changed)
        # FULL covers every production row with a written file
        self.assertEqual(res["candidates"], qa_scope.full_candidates(
            self.matrix, ROOT))
        self.assertGreater(len(res["candidates"]), 100)

    def test_engine_change_forces_full(self):
        self._assert_full(["scripts/score_article.py"])

    def test_rubric_change_forces_full(self):
        self._assert_full(["config/article-rubric.json"])

    def test_business_facts_change_forces_full(self):
        self._assert_full(["config/business-facts.json"])

    def test_shared_template_change_forces_full(self):
        self._assert_full(["_snippets/footer-compact.html"])

    def test_gate_workflow_change_forces_full(self):
        self._assert_full([".github/workflows/article-quality.yml"])

    def test_force_full_disables_evidence_reuse(self):
        res = qa_scope.select_scope([], self.matrix, ROOT, force_full=True)
        self.assertEqual(res["scope"], "full")
        self.assertEqual(res["reason"], "manual FULL re-validation")
        self.assertEqual(res["reused"], [])  # a manual FULL revalidates all


class EvidenceTests(ScopedQATestCase):
    """Verification 3: QA evidence reuse and invalidation."""

    def setUp(self):
        self._backup = None
        if os.path.isfile(EVIDENCE_FILE):
            with io.open(EVIDENCE_FILE, encoding="utf-8") as f:
                self._backup = f.read()
            os.remove(EVIDENCE_FILE)

    def tearDown(self):
        if self._backup is not None:
            os.makedirs(os.path.dirname(EVIDENCE_FILE), exist_ok=True)
            with io.open(EVIDENCE_FILE, "w", encoding="utf-8") as f:
                f.write(self._backup)
        elif os.path.isfile(EVIDENCE_FILE):
            os.remove(EVIDENCE_FILE)

    def _record_draft_evidence(self, row):
        path = os.path.join(ROOT, _draft_rel(row))
        entry = {
            "article_id": row["article_id"],
            "content_sha256": qa_scope.file_sha256(path),
            "config_sha256": qa_scope.config_sha256(ROOT),
            "validator_version": lib.VALIDATOR_VERSION,
            "status": "PASS",
            "score": 96,
            "path": _draft_rel(row),
            "last_checked": "2026-09-28",
        }
        qa_scope.record_evidence(ROOT, [entry])
        return path, entry

    def test_pass_evidence_is_reusable(self):
        path, _e = self._record_draft_evidence(self.draft_row)
        stored = qa_scope.load_evidence(ROOT)[self.draft_row["article_id"]]
        self.assertTrue(qa_scope.evidence_is_reusable(stored, path))

    def test_changed_content_invalidates_evidence(self):
        # verification: "QA cũ bị vô hiệu khi nội dung đổi" — a modified
        # file (different content hash) must never reuse the old verdict
        path, _e = self._record_draft_evidence(self.draft_row)
        stored = dict(qa_scope.load_evidence(ROOT)[
            self.draft_row["article_id"]])
        stored["content_sha256"] = "0" * 64  # hash no longer matches file
        self.assertFalse(qa_scope.evidence_is_reusable(stored, path))

    def test_changed_config_invalidates_evidence(self):
        # a rubric/business-facts change rotates config_sha256 -> stale
        path, _e = self._record_draft_evidence(self.draft_row)
        stored = dict(qa_scope.load_evidence(ROOT)[
            self.draft_row["article_id"]])
        self.assertFalse(qa_scope.evidence_is_reusable(stored, path,
                                                       cfg_sha="f" * 64))

    def test_validator_version_change_invalidates_evidence(self):
        path, _e = self._record_draft_evidence(self.draft_row)
        stored = dict(qa_scope.load_evidence(ROOT)[
            self.draft_row["article_id"]])
        stored["validator_version"] = "1999-01-01.0"
        self.assertFalse(qa_scope.evidence_is_reusable(stored, path))

    def test_non_pass_evidence_never_reusable(self):
        path = os.path.join(ROOT, _draft_rel(self.draft_row))
        self.assertFalse(qa_scope.evidence_is_reusable(
            {"status": "REVIEW", "content_sha256": qa_scope.file_sha256(path),
             "config_sha256": qa_scope.config_sha256(ROOT),
             "validator_version": lib.VALIDATOR_VERSION}, path))

    def test_record_evidence_ignores_non_matrix_ids(self):
        # synthetic test ids must never leave reusable evidence behind
        qa_scope.record_evidence(ROOT, [{
            "article_id": "ZZ-9999",
            "content_sha256": "a" * 64,
            "config_sha256": qa_scope.config_sha256(ROOT),
            "validator_version": lib.VALIDATOR_VERSION,
            "status": "PASS", "score": 100, "path": "x",
            "last_checked": "2026-09-28",
        }])
        self.assertNotIn("ZZ-9999", qa_scope.load_evidence(ROOT))
        self.assertFalse(qa_scope.is_matrix_article("ZZ-9999"))
        self.assertTrue(qa_scope.is_matrix_article(
            next(r for r in self.matrix if r["status"] == "PUBLISHED")
            ["article_id"]))

    def test_scope_reuses_matching_evidence(self):
        path, _e = self._record_draft_evidence(self.draft_row)
        res = qa_scope.select_scope([_draft_rel(self.draft_row)],
                                     self.matrix, ROOT)
        self.assertEqual(res["scope"], "changed")
        self.assertIn(path, res["reused"])
        self.assertEqual(res["checked"], [])


class ProgressSyncTests(ScopedQATestCase):
    """Verification 4: QA tạo 5 PASS → báo cáo tổng và báo cáo batch cùng
    phản ánh 5 PASS (counts regenerated from the matrix, never patched)."""

    def _fixture_row(self, fixture, article_id):
        row = None
        for r in self.matrix:
            if r["output_path"] == "tests/fixtures/" + fixture:
                row = dict(r)
                break
        if row is None:
            row = dict(next(r for r in self.matrix
                           if lib.is_sample_row(r)))
        row["article_id"] = article_id
        row["status"] = "WRITING"
        row["output_path"] = "tests/fixtures/" + fixture
        row["notes"] = ""
        return row

    def test_qa_five_pass_syncs_progress_and_batch_report(self):
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        rows = [self._fixture_row("good.html", "QT-000%d" % i)
                for i in range(1, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            # QA reads fixtures from the real repo (ZZ-style ids never
            # leave evidence behind); reports are regenerated into tmp
            updates, articles = rb.run_qa_for_batch(
                rows, self.matrix, ownership, facts, rubric, ROOT)
            self.assertEqual(
                {a["outcome"] for a in articles}, {"PASS"})
            self.assertEqual(len(updates), 5)
            # matrix truth after the QA mutation: 5 PASS
            matrix_truth = [dict(r) for r in rows]
            for r in matrix_truth:
                r["status"] = "PASS"
            report = rb.build_cumulative_report(
                "BATCH-QT", matrix_truth, articles, "2026-09-28T00:00:00",
                tmp)
            rb.write_report(tmp, report)
            self.assertEqual(report["pass"], 5)
            self.assertEqual(report["writing"], 0)
            # progress ledger regenerated from the same matrix truth
            progress = {
                "QT-0001": "PASS", "QT-0002": "PASS", "QT-0003": "PASS",
                "QT-0004": "PASS", "QT-0005": "PASS",
            }
            full_matrix = list(matrix_truth) + [
                {"article_id": "QT-100%d" % i, "status": "WRITING",
                 "batch_id": "BATCH-QT", "output_path": "x%d.html" % i,
                 "category": "Xe máy", "notes": ""}
                for i in range(1, 46)]
            rb.write_factory_progress(tmp, full_matrix)
            with io.open(os.path.join(tmp, "reports", "batches",
                                     "factory-progress.json"),
                         encoding="utf-8") as f:
                prog = json.load(f)
            # BOTH reports reflect the same 5 PASS / 45 WRITING truth
            self.assertEqual(prog["pass"], 5)
            self.assertEqual(prog["writing"], 45)
            self.assertEqual(report["pass"], prog["pass"])
            # schema-2 SHA semantics: the report records the INPUT sha
            # it was generated from (source_head_sha), never an
            # unstable self-referential "this commit contains this file"
            # claim; the legacy matrix_commit_sha field is gone.
            self.assertNotIn("matrix_commit_sha", prog)
            self.assertIn("source_head_sha", prog)
            self.assertEqual(prog.get("schema_version"), 2)
            self.assertRegex(
                prog.get("generated") or "",
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+07:00$")

    def test_progress_counts_never_hand_patched(self):
        # counts derive from the matrix rows, not from the previous file
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"article_id": "QT-2001", "status": "PUBLISHED",
                     "batch_id": "BATCH-QT", "output_path": "a.html",
                     "category": "Xe máy", "notes": ""},
                    {"article_id": "QT-2002", "status": "WRITING",
                     "batch_id": "BATCH-QT", "output_path": "b.html",
                     "category": "Xe máy", "notes": ""}]
            os.makedirs(os.path.join(tmp, "reports", "batches"),
                        exist_ok=True)
            with io.open(os.path.join(tmp, "reports", "batches",
                                      "factory-progress.json"),
                         "w", encoding="utf-8") as f:
                json.dump({"pass": 999, "writing": 999}, f)  # stale junk
            rb.write_factory_progress(tmp, rows)
            with io.open(os.path.join(tmp, "reports", "batches",
                                      "factory-progress.json"),
                         encoding="utf-8") as f:
                prog = json.load(f)
            self.assertEqual(prog["pass"], 0)
            self.assertEqual(prog["writing"], 1)
            self.assertEqual(prog["published"], 1)


class WordCountingTests(unittest.TestCase):
    """Verification 5: word counting is main-content-only and the length
    band separates not-yet-published rows from PUBLISHED rows."""

    def test_jsonld_menu_footer_words_excluded(self):
        d = tempfile.mkdtemp()
        try:
            body = " ".join("t%d" % i for i in range(499))
            html = (
                '<html lang="vi"><head><title>t</title>'
                '<script type="application/ld+json">'
                '{"@type":"BreadcrumbList","itemListElement":[{"x":1}]'
                "}</script>"
                '<link rel="canonical" href="x.html"></head><body>'
                '<article><h1>H1</h1><p>%s</p></article>'
                '<nav><a href="kinhnghiem.html">menu word</a></nav>'
                '<footer><p>footer word</p></footer>'
                '<div class="chatbot">chatbot word</div>'
                "</body></html>" % body)
            p = os.path.join(d, "wc.html")
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(html)
            art = lib.Article(p)
            # 499 filler tokens + the single H1 word = 500 main words;
            # JSON-LD, menu, footer and chatbot words never count
            self.assertEqual(len(art.main_content_words), 500)
        finally:
            shutil.rmtree(d)

    def test_new_band_applies_only_to_unpublished_rows(self):
        # unpublished: 2500 words satisfied; published: legacy FAIL
        for status, expected_fail in (("WRITING", False),
                                      ("PUBLISHED", True)):
            d = tempfile.mkdtemp()
            try:
                body = " ".join("t%d" % i for i in range(2499))
                html = ('<html lang="vi"><head><title>t</title>'
                        '<link rel="canonical" href="x.html"></head><body>'
                        '<article><h1>H1</h1><p>%s</p></article>'
                        "</body></html>" % body)
                p = os.path.join(d, "wc.html")
                with io.open(p, "w", encoding="utf-8") as f:
                    f.write(html)
                art = lib.Article(p)
                row = {"article_id": "QT-3001", "status": status,
                       "category": "Xe máy", "primary_keyword": "k",
                       "slug": "qt-3001",
                       "output_path": "cam-nang/xe-may/qt-3001.html",
                       "parent_hub": "xemay.html"}
                fails, flags, _w, metrics = \
                    lib.evaluate_production_standard(
                        art, row, lib.load_rubric(), lib.load_ownership())
                self.assertEqual(
                    any("length" in f for f in fails), expected_fail,
                    (status, fails, flags))
                if status == "WRITING":
                    self.assertIn("1600-3000", metrics["word_count_band"])
                else:
                    self.assertIn("legacy", metrics["word_count_band"])
            finally:
                shutil.rmtree(d)


class PublishGateScopeTests(ScopedQATestCase):
    """Verification 6: the publish gate keeps refusing bad articles and
    honours the scoped --ids contract (never re-scans the other
    published articles)."""

    def _gate(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/gate_published_articles.py", *args],
            cwd=ROOT, capture_output=True, text=True)

    def test_gate_refuses_non_published_ids(self):
        # a genuinely not-yet-published row (WRITING/PASS/PLANNED): the
        # scoped gate must refuse the whole scope, not silently skip rows
        non_pub = next(r for r in self.matrix
                       if r["status"] not in ("PUBLISHED", "SAMPLE")
                       and not r["article_id"].startswith("SAMPLE"))
        p = self._gate("--ids", non_pub["article_id"])
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("GATE REFUSED", p.stdout)

    def test_gate_ids_contract_in_workflow(self):
        y = io.open(os.path.join(ROOT, ".github", "workflows",
                                "factory-operator.yml"),
                    encoding="utf-8").read()
        # publish op: scoped gate on the published ids only
        self.assertIn('gate_published_articles.py --ids "$ids"', y)
        # publish op no longer re-shells/re-scans every published article
        self.assertNotIn("python3 scripts/apply_article_shell.py\n"
                          "          python3 scripts/gate_published_"
                          "articles.py", y)
        # batch-end FULL audit still exists
        self.assertIn("Batch-end FULL audit", y)
        self.assertIn("BATCH-COMPLETE", y)
        # one-command-at-a-time guard exists
        self.assertIn("superseded by a newer push", y)

    def test_evidence_cache_persists_as_workflow_artifact(self):
        # reports/article-quality/ is gitignored, so the evidence cache
        # must round-trip through workflow artifacts or reuse would be
        # lost between CI runs (every run cold). Both workflows restore
        # it before any gate and save it afterwards, non-fatally.
        for wf in ("article-quality.yml", "factory-operator.yml"):
            y = io.open(os.path.join(ROOT, ".github", "workflows", wf),
                        encoding="utf-8").read()
            self.assertIn("Restore QA evidence cache", y)
            self.assertIn("Save QA evidence cache", y)
            self.assertIn("download-artifact@v4", y)
            self.assertIn("upload-artifact@v4", y)
            self.assertIn("name: qa-evidence", y)
            self.assertIn("qa-evidence.json", y)
        q = io.open(os.path.join(ROOT, ".github", "workflows",
                                "article-quality.yml"),
                    encoding="utf-8").read()
        self.assertIn("Record PASS evidence for the checked candidates", q)

    def test_publish_gate_still_blocks_non_pass_rows(self):
        # the transaction-level publish gate (factory.mjs) keeps refusing
        # non-PASS rows — unchanged by scoping
        p = subprocess.run(
            ["node", "scripts/js/factory.mjs", "--publish", "KN-0001"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("PASS", (p.stderr or "") + (p.stdout or ""))


if __name__ == "__main__":
    unittest.main()