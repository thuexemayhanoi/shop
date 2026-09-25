#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Content-factory quality-gate test suite.

Invokes the real validator, cannibalization checker and scorer logic
from scripts/article_lib.py / scripts/score_article.py against the
fixtures in tests/fixtures/. No network, no AI, deterministic.
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
FIX = os.path.join(HERE, "fixtures")

sys.path.insert(0, SCRIPTS)
import article_lib as lib  # noqa: E402
import score_article as scorer  # noqa: E402


def load_article(name):
    return lib.Article(os.path.join(FIX, name))


def run_score(name):
    """Run the full scoring pipeline for a fixture; return the result dict."""
    article = load_article(name)
    matrix = lib.load_matrix()
    ownership = lib.load_ownership()
    facts = lib.load_business_facts()
    rubric = lib.load_rubric()
    row = lib.find_matrix_row(article, matrix)
    result = scorer.score_article(article, matrix, ownership, facts, rubric)
    return {
        "article": article,
        "row": row,
        "score": result[0],
        "status": result[1],
        "sections": result[2],
        "failures": result[3],
        "warnings": result[4],
        "recommendations": result[5],
        "review_flags": result[6],
    }


def run_cli(script, name):
    """Run a gate script as a subprocess; return its exit code."""
    p = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), os.path.join(FIX, name)],
        capture_output=True, text=True)
    return p.returncode


class GateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.ownership = lib.load_ownership()
        cls.facts = lib.load_business_facts()
        cls.rubric = lib.load_rubric()


class ConfigTests(GateTestCase):
    def test_configs_load(self):
        self.assertTrue(len(self.rubric["sections"]) >= 9)
        self.assertEqual(sum(self.rubric["sections"].values()), 100)
        self.assertIn("approved_models", self.facts or {})

    def test_thresholds(self):
        th = self.rubric["thresholds"]
        self.assertEqual(th["PASS"]["min"], 90)
        self.assertEqual(th["REVIEW"]["min"], 80)
        self.assertEqual(th["FAIL"]["max"], 79)

    def test_business_facts_prices(self):
        models = self.facts["approved_models"]
        self.assertEqual(models["vision"]["daily"], 200000)
        self.assertEqual(models["wave"]["week"], 700000)
        self.assertEqual(models["airblade"]["monthMin"], 1500000)

    def test_ownership_protects_commercial_pages(self):
        paths = [p["path"] for p in self.ownership["protected_pages"]]
        for must in ("index.html", "phoco.html", "hoankiem.html", "banggia.html"):
            self.assertIn(must, paths)

    def test_matrix_schema_and_samples(self):
        hdr = [r.keys() for r in self.matrix][0] if self.matrix else []
        for col in ("article_id", "status", "primary_keyword", "slug", "output_path"):
            self.assertIn(col, hdr)
        self.assertTrue(all(r["article_id"].startswith("SAMPLE") for r in self.matrix))

    def test_matrix_no_duplicate_production_ids(self):
        ids = [r["article_id"] for r in self.matrix]
        self.assertEqual(len(ids), len(set(ids)))


class PassArticleTests(GateTestCase):
    def test_good_pass(self):
        r = run_score("good.html")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["failures"], [])
        self.assertGreaterEqual(r["score"], 90)

    def test_good2_pass(self):
        r = run_score("good2.html")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["failures"], [])

    def test_good_cli_exit_zero(self):
        self.assertEqual(run_cli("score_article.py", "good.html"), lib.EXIT_PASS)
        self.assertEqual(run_cli("validate_article.py", "good.html"), 0)
        self.assertEqual(run_cli("check_cannibalization.py", "good.html"), lib.EXIT_PASS)


class ReviewArticleTests(GateTestCase):
    def test_similar_title_review(self):
        r = run_score("review_similar_title.html")
        self.assertEqual(r["status"], "REVIEW")
        self.assertEqual(r["failures"], [])
        self.assertTrue(any("similar title" in f for f in r["review_flags"]))

    def test_weak_links_review(self):
        r = run_score("review_weak_links.html")
        self.assertEqual(r["status"], "REVIEW")
        self.assertTrue(any("parent" in f or "hub" in f for f in r["review_flags"]),
                        msg=str(r["review_flags"]))

    def test_no_sources_review(self):
        r = run_score("review_no_sources.html")
        self.assertEqual(r["status"], "REVIEW")
        self.assertTrue(any("source" in f for f in r["review_flags"]),
                        msg=str(r["review_flags"]))

    def test_review_cli_exit_two(self):
        self.assertEqual(run_cli("score_article.py", "review_weak_links.html"),
                         lib.EXIT_REVIEW)


class FailArticleTests(GateTestCase):
    def _assert_fail(self, name, must_contain=None):
        r = run_score(name)
        self.assertEqual(r["status"], "FAIL", msg=name)
        if must_contain:
            self.assertTrue(any(must_contain in f for f in r["failures"]),
                            msg="%s :: %s" % (name, r["failures"]))

    def test_missing_h1(self):
        self._assert_fail("fail_no_h1.html", "H1")

    def test_two_h1(self):
        self._assert_fail("fail_two_h1.html", "H1")

    def test_missing_canonical(self):
        self._assert_fail("fail_no_canonical.html", "canonical")

    def test_wrong_canonical(self):
        self._assert_fail("fail_wrong_canonical.html", "canonical")

    def test_protected_intent(self):
        self._assert_fail("fail_protected_intent.html", "phoco.html")

    def test_vision_wrong_price(self):
        self._assert_fail("fail_vision_price.html")

    def test_ebike_wrong_price(self):
        self._assert_fail("fail_ebike_price.html")

    def test_lead_invented_price(self):
        self._assert_fail("fail_lead_price.html")

    def test_50cc_invented_price(self):
        self._assert_fail("fail_50cc_price.html")

    def test_stale_deposit(self):
        self._assert_fail("fail_deposit.html")

    def test_broken_internal_link(self):
        self._assert_fail("fail_broken_link.html")

    def test_duplicate_primary_keyword(self):
        self._assert_fail("fail_dup_keyword.html", "duplicate primary keyword")

    def test_placeholder_text(self):
        self._assert_fail("fail_placeholder.html")

    def test_fail_cli_exit_three(self):
        self.assertEqual(run_cli("score_article.py", "fail_vision_price.html"),
                         lib.EXIT_FAIL)


class ValidatorTests(GateTestCase):
    def _errors(self, name):
        return lib.validate_article(load_article(name), self.matrix,
                                    self.ownership, self.facts, self.rubric)

    def test_good_validates(self):
        self.assertEqual(self._errors("good.html"), [])

    def test_missing_h1_hard_error(self):
        self.assertTrue(any("H1" in e for e in self._errors("fail_no_h1.html")))

    def test_missing_canonical_hard_error(self):
        self.assertTrue(any("canonical" in e for e in self._errors("fail_no_canonical.html")))

    def test_validator_cli(self):
        self.assertEqual(run_cli("validate_article.py", "fail_no_h1.html"), 1)


class CannibalizationTests(GateTestCase):
    def _can(self, name):
        return lib.check_cannibalization(load_article(name), self.ownership,
                                         self.matrix, self.facts)

    def test_protected_intent_conflict(self):
        failures, warnings, review = self._can("fail_protected_intent.html")
        self.assertTrue(any("phoco.html" in f for f in failures))

    def test_duplicate_keyword_conflict(self):
        failures, warnings, review = self._can("fail_dup_keyword.html")
        self.assertTrue(any("duplicate primary keyword" in f for f in failures))

    def test_good_no_conflict(self):
        failures, warnings, review = self._can("good.html")
        self.assertEqual(failures, [])

    def test_can_cli_exit_codes(self):
        self.assertEqual(run_cli("check_cannibalization.py", "fail_protected_intent.html"),
                         lib.EXIT_FAIL)


if __name__ == "__main__":
    unittest.main()
