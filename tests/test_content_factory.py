#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Content-factory tests: 2000-row matrix, 40x50 batches, batch runner
behaviour, publish policy, resume safety, writer gate."""
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib
import run_article_batch as rb
import validate_content_matrix as vcm

FIXTURES = os.path.join(HERE, "fixtures")


class FactoryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.prod = [r for r in cls.matrix if not lib.is_sample_row(r)]
        cls.samples = [r for r in cls.matrix if lib.is_sample_row(r)]


class MatrixTests(FactoryTestCase):
    def test_exactly_2000_production_rows(self):
        self.assertEqual(len(self.prod), 2000)

    def test_samples_not_counted_in_production(self):
        self.assertEqual(len(self.samples), 8)
        self.assertEqual(len(self.prod) + len(self.samples), len(self.matrix))

    def test_exactly_40_batches_of_50(self):
        batches = {}
        for r in self.prod:
            batches.setdefault(r["batch_id"], []).append(r)
        self.assertEqual(len(batches), 40)
        for bid, rows in batches.items():
            self.assertEqual(len(rows), 50, bid)
        self.assertEqual(sorted(batches)[0], "BATCH-001")
        self.assertEqual(sorted(batches)[-1], "BATCH-040")

    def test_no_duplicate_ids_slugs_paths_keywords(self):
        for f in ("article_id", "slug", "output_path", "primary_keyword",
                  "working_title"):
            vals = [r[f] for r in self.prod]
            self.assertEqual(len(vals), len(set(vals)), f)

    def test_valid_categories_and_hubs(self):
        for r in self.prod:
            self.assertIn(r["category"], lib.CATEGORIES)
            self.assertEqual(r["parent_hub"], lib.CATEGORIES[r["category"]])

    def test_production_ids_match_pattern(self):
        import re
        pat = re.compile(r"^[A-Z]{2}-\d{4}$")
        for r in self.prod:
            self.assertTrue(pat.match(r["article_id"]), r["article_id"])

    def test_no_protected_intent_conflicts(self):
        ownership = lib.load_ownership()
        protected = []
        for p in ownership["protected_pages"]:
            intents = p.get("primary_intents", [])
            if isinstance(intents, str):
                intents = [intents]
            for i in intents:
                protected.append(i if isinstance(i, str) else " ".join(i))
        prot_norm = {tuple(lib.norm_tokens(p)) for p in protected if p}
        for r in self.prod:
            kw = tuple(lib.norm_tokens(r["primary_keyword"]))
            self.assertNotIn(kw, prot_norm, r["article_id"])
            self.assertEqual((r.get("protected_intent_conflict") or "").strip().lower(),
                             "no", r["article_id"])

    def test_legal_topics_require_sources(self):
        flagged = [r for r in self.prod
                   if (r.get("requires_sources") or "").lower() == "true"]
        self.assertGreater(len(flagged), 50)
        for r in flagged:
            self.assertTrue((r.get("source_notes") or "").strip(),
                            r["article_id"])

    def test_validate_content_matrix_passes(self):
        errors, warnings = vcm.validate(self.matrix, lib.load_ownership())
        self.assertEqual(errors, [])

    def test_validate_content_matrix_detects_shortfall(self):
        broken = [r for r in self.prod if not lib.is_sample_row(r)][:1999]
        errors, _ = vcm.validate(broken + self.samples, lib.load_ownership())
        self.assertTrue(any("production rows" in e for e in errors))


class BatchSelectionTests(FactoryTestCase):
    def test_select_claim_rows_max_50(self):
        rows = self.prod[:120]
        for r in rows:
            r["status"] = "PLANNED"
        self.assertEqual(len(rb.select_claim_rows(rows, 50)), 50)
        self.assertEqual(len(rb.select_claim_rows(rows, 200)), 50)  # capped

    def test_select_claim_rows_skips_non_planned(self):
        rows = self.prod[:60]
        for r in rows[:20]:
            r["status"] = "PASS"
        for r in rows[20:40]:
            r["status"] = "PUBLISHED"
        for r in rows[40:]:
            r["status"] = "PLANNED"
        claimed = rb.select_claim_rows(rows, 50)
        self.assertEqual(len(claimed), 20)
        self.assertTrue(all(r["status"] == "PLANNED" for r in claimed))

    def test_resume_skips_pass_and_published(self):
        tmp = tempfile.mkdtemp()
        try:
            rows = []
            for i, st in enumerate(["PASS", "PUBLISHED", "WRITING", "QA", "PLANNED", "REVIEW"]):
                r = dict(self.prod[i])
                r["status"] = st
                r["output_path"] = "tests/fixtures/good.html" if st in ("WRITING", "QA", "REVIEW") else "nope.html"
                rows.append(r)
            got = rb.select_qa_rows(rows, ROOT, 50)
            self.assertEqual([r["status"] for r in got], ["WRITING", "QA", "REVIEW"])
        finally:
            shutil.rmtree(tmp)

    def test_resume_never_touches_pass(self):
        rows = [dict(self.prod[0])]
        rows[0]["status"] = "PASS"
        self.assertEqual(rb.select_qa_rows(rows, ROOT, 50), [])

    def test_batch_rows_and_next(self):
        b1 = rb.batch_rows(self.matrix, "BATCH-001")
        self.assertEqual(len(b1), 50)
        self.assertTrue(all(r["batch_id"] == "BATCH-001" for r in b1))
        self.assertEqual(rb.next_batch_id(self.matrix), "BATCH-001")
        done = [dict(r) for r in self.prod]
        for r in done:
            r["status"] = "PUBLISHED"
        self.assertIsNone(rb.next_batch_id(done + self.samples))


class PublishPolicyTests(FactoryTestCase):
    def _qa_env(self):
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        return ownership, facts, rubric

    def _row_for_fixture(self, fixture, article_id):
        """Production-style row whose output_path is a fixture file."""
        matches = [r for r in self.matrix
                   if r["output_path"] == "tests/fixtures/" + fixture]
        if matches:
            row = dict(matches[0])
        else:
            # fixture without its own matrix row: synthesize from a sample row
            row = dict(self.samples[0])
            row["primary_keyword"] = "giá thuê Honda Vision"
        row["article_id"] = article_id
        row["status"] = "WRITING"
        row["output_path"] = "tests/fixtures/" + fixture
        return row

    def test_pass_article_is_publishable(self):
        ownership, facts, rubric = self._qa_env()
        row = self._row_for_fixture("good.html", "ZZ-9999")
        updates, articles = rb.run_qa_for_batch([row], self.matrix, ownership,
                                               facts, rubric, ROOT)
        self.assertEqual(articles[0]["outcome"], "PASS")
        self.assertEqual(updates["ZZ-9999"]["status"], "PASS")

    def test_fail_article_not_published(self):
        ownership, facts, rubric = self._qa_env()
        row = self._row_for_fixture("fail_vision_price.html", "ZZ-9998")
        updates, articles = rb.run_qa_for_batch([row], self.matrix, ownership,
                                               facts, rubric, ROOT)
        self.assertEqual(articles[0]["outcome"], "FAIL")
        self.assertEqual(updates["ZZ-9998"]["status"], "FAIL")

    def test_review_article_not_published(self):
        ownership, facts, rubric = self._qa_env()
        row = self._row_for_fixture("review_weak_links.html", "ZZ-9997")
        updates, articles = rb.run_qa_for_batch([row], self.matrix, ownership,
                                               facts, rubric, ROOT)
        self.assertEqual(articles[0]["outcome"], "REVIEW")
        self.assertNotEqual(updates["ZZ-9997"]["status"], "PASS")
        self.assertNotEqual(updates["ZZ-9997"]["status"], "PUBLISHED")

    def test_one_fail_does_not_block_pass(self):
        ownership, facts, rubric = self._qa_env()
        rows = [self._row_for_fixture("good.html", "ZZ-0001"),
                self._row_for_fixture("fail_vision_price.html", "ZZ-0002"),
                self._row_for_fixture("good2.html", "ZZ-0003")]
        updates, articles = rb.run_qa_for_batch(rows, self.matrix, ownership,
                                               facts, rubric, ROOT)
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["ZZ-0001"], "PASS")
        self.assertEqual(outcomes["ZZ-0002"], "FAIL")
        self.assertEqual(outcomes["ZZ-0003"], "PASS")
        # the PASS articles are still publishable
        self.assertEqual(updates["ZZ-0001"]["status"], "PASS")
        self.assertEqual(updates["ZZ-0003"]["status"], "PASS")

    def test_review_after_max_repairs_blocked(self):
        row = dict(self.prod[0])
        row["article_id"] = "ZZ-9000"
        row["status"] = "REVIEW"
        row["notes"] = "repair:2"  # two attempts already recorded
        n = rb.repair_attempts(row["notes"])
        self.assertEqual(n, 2)
        self.assertEqual(rb.note_repair("", 3), "repair:3")
        # orchestrator policy: attempts+1 >= MAX -> BLOCKED
        self.assertLess(rb.MAX_REPAIR_ATTEMPTS, 4)


def reset_matrix_to_planned(path):
    """Rewrite a SANDBOX copy of content-matrix.csv with every production
    row reset to PLANNED (published_date cleared), so runner tests
    exercise the claim/publish mechanism itself and stay independent of
    REAL production progress. SAMPLE rows are left untouched."""
    with io.open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames)
        rows = list(reader)
    for r in rows:
        if lib.is_sample_row(r):
            continue
        r["status"] = "PLANNED"
        if "published_date" in r:
            r["published_date"] = ""
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class RunnerCLITests(FactoryTestCase):
    """CLI smoke tests against a sandbox copy of the repo data dir."""

    def _sandbox(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"), os.path.join(tmp, "config"))
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    os.path.join(tmp, "data", "content-matrix.csv"))
        reset_matrix_to_planned(os.path.join(tmp, "data",
                                             "content-matrix.csv"))
        return tmp

    def test_prepare_agent_claims_50_writing_and_manifest(self):
        """--prepare-agent claims exactly the batch's PLANNED rows as
        WRITING and writes the deterministic agent manifest — with NO API,
        NO provider and NO secrets. Rows are claimed (WRITING) so the
        external agent knows exactly which files to write; the manifest
        carries the full per-article production context."""
        tmp = self._sandbox()
        env = dict(os.environ, PYTHONPATH=SCRIPTS)
        code = subprocess.call(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, %r)
import run_article_batch as rb, article_lib as lib
lib.ROOT = %r
rb.main_func(['--batch', 'BATCH-001', '--prepare-agent'])
""" % (SCRIPTS, tmp)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            manifest = os.path.join(tmp, "data", "batches", "BATCH-001.json")
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(manifest))
            data = json.load(io.open(manifest, encoding="utf-8"))
            self.assertEqual(len(data["articles"]), 50)
            wc = data["articles"][0]
            # full writer context per article
            self.assertEqual(wc["word_standard"]["target_min_words"], 1600)
            self.assertEqual(wc["word_standard"]["target_max_words"], 2000)
            self.assertEqual(wc["link_standard"]["contextual_internal_links_min"], 3)
            self.assertEqual(wc["link_standard"]["contextual_internal_links_max"], 5)
            self.assertEqual(wc["link_standard"]["commercial_links_max"], 1)
            self.assertTrue(wc["link_standard"]["parent_hub_link_required"])
            self.assertTrue(wc["canonical_url"].endswith(wc["output_path"]))
            # datePublished = ACTUAL date, never the future planned_date
            self.assertNotEqual(wc["date_published"], wc.get("planned_date"))
            self.assertEqual(wc["date_published"], rb.today())
            with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                         encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            writing = [r for r in rows if r["status"] == "WRITING"]
            self.assertEqual(len(writing), 50)
            self.assertTrue(all(r["batch_id"] == "BATCH-001" for r in writing))
        finally:
            shutil.rmtree(tmp)

    def test_prepare_agent_needs_no_secret(self):
        """prepare-agent must work with a scrubbed environment: no
        MISTRAL_API_KEY, no WRITER_PROVIDER, no provider modules."""
        tmp = self._sandbox()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MISTRAL", "WRITER", "OPENAI", "ANTHROPIC"))}
        env["PYTHONPATH"] = SCRIPTS
        code = subprocess.call(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, %r)
import run_article_batch as rb, article_lib as lib
lib.ROOT = %r
rb.main_func(['--batch', 'BATCH-001', '--prepare-agent'])
""" % (SCRIPTS, tmp)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(
                tmp, "data", "batches", "BATCH-001.json")))
        finally:
            shutil.rmtree(tmp)


class WriterTests(unittest.TestCase):
    def test_writer_not_configured(self):
        import article_writer as aw
        env = dict(os.environ)
        env.pop("WRITER_PROVIDER", None)
        with self.assertRaises(aw.WriterNotConfigured):
            aw.write_article({"article_id": "X"}, {})

    def test_writer_cli_exit_5(self):
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "article_writer.py")],
                           capture_output=True, env=dict(os.environ, WRITER_PROVIDER=""),
                           text=True)
        self.assertEqual(p.returncode, 5)
        self.assertIn("WRITER_NOT_CONFIGURED", p.stdout)


class SitemapTests(FactoryTestCase):
    def test_sitemap_keeps_current_urls(self):
        sys.path.insert(0, SCRIPTS)
        import generate_sitemap as gs
        existing = gs.current_urls(os.path.join(ROOT, "sitemap.xml"))
        self.assertGreater(len(existing), 10)
        # Regenerate inside a sandbox: every URL currently in sitemap.xml
        # must survive, and every PUBLISHED article must be included —
        # regardless of how far real production has progressed.
        published = gs.published_article_urls(
            self.matrix, site_url_base=lib.load_site_config()["site_url"])
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "data"))
            shutil.copytree(os.path.join(ROOT, "config"),
                            os.path.join(tmp, "config"))
            shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                        os.path.join(tmp, "data", "content-matrix.csv"))
            shutil.copy(os.path.join(ROOT, "sitemap.xml"),
                        os.path.join(tmp, "sitemap.xml"))
            code = subprocess.call(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, %r)
import generate_sitemap as gs, article_lib as lib
lib.ROOT = %r
raise SystemExit(gs.main())
""" % (SCRIPTS, tmp)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(code, 0)
            merged = gs.current_urls(os.path.join(tmp, "sitemap.xml"))
            self.assertTrue(set(existing) <= set(merged),
                            "legacy URLs dropped by regeneration")
            self.assertTrue(set(published) <= set(merged),
                            "PUBLISHED article URLs missing from sitemap")
        finally:
            shutil.rmtree(tmp, True)

    def test_sitemap_includes_only_published(self):
        sys.path.insert(0, SCRIPTS)
        import generate_sitemap as gs
        rows = [dict(self.prod[0])]
        rows[0]["status"] = "PLANNED"
        self.assertEqual(gs.published_article_urls(rows), [])
        rows[0]["status"] = "PUBLISHED"
        self.assertEqual(gs.published_article_urls(rows),
                         ["/" + rows[0]["output_path"]])


if __name__ == "__main__":
    unittest.main()
