#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production-standard tests: 1,600–2,000 word rule, 3–5 contextual-link rule,
anchor checks, exclusions, base-path /shop/ enforcement, sitemap status rules
and workflow concurrency policy."""
import io
import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib
import generate_category_index as gci
import generate_sitemap as gsm


def synth_article(words, links=(), wrap="article", extra=""):
    """Build a temp HTML article with an exact main-content word count.
    (The H1 contributes one word, so filler uses words-1 tokens.)"""
    body_words = " ".join("t%d" % i for i in range(max(words - 1, 0)))
    link_html = "".join('<p>đoạn văn <a href="%s">%s</a> tự nhiên.</p>' % l
                        for l in links)
    html = ("<html lang=\"vi\"><head><title>t</title>"
            "<meta name=\"description\" content=\"d\">"
            "<link rel=\"canonical\" href=\"x.html\"></head><body>"
            "<%s><h1>H1</h1><p>%s</p>%s%s</%s></body></html>"
            % (wrap, body_words, link_html, extra, wrap))
    d = tempfile.mkdtemp()
    p = os.path.join(d, "synth-%d.html" % words)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(html)
    return lib.Article(p), d


PROD_ROW = {
    "article_id": "AT-9001",
    "status": "WRITING",
    "category": "An toàn",
    "primary_keyword": "an toàn",
    "slug": "at-9001",
    "output_path": "cam-nang/an-toan/at-9001.html",
    "parent_hub": "antoan.html",
}


class WordCountTests(unittest.TestCase):
    def setUp(self):
        self.rubric = lib.load_rubric()
        self.ownership = lib.load_ownership()

    def _eval(self, n):
        art, d = synth_article(n)
        try:
            return lib.evaluate_production_standard(art, PROD_ROW, self.rubric,
                                                     self.ownership)
        finally:
            shutil.rmtree(d)

    def assertEligible(self, n):
        fails, flags, warns, metrics = self._eval(n)
        self.assertEqual([f for f in fails if "length" in f], [], n)
        self.assertEqual([f for f in flags if "word" in f], [], n)

    def assertReview(self, n):
        fails, flags, warns, metrics = self._eval(n)
        self.assertTrue(any("word" in f for f in flags), n)
        self.assertEqual([f for f in fails if "length" in f], [], n)

    def assertFail(self, n):
        fails, flags, warns, metrics = self._eval(n)
        self.assertTrue(any("length" in f for f in fails), n)

    def test_word_boundaries(self):
        for n in (1600, 1800, 2000):
            self.assertEligible(n)
        self.assertReview(1599)
        self.assertReview(2001)
        self.assertFail(1199)
        self.assertFail(2301)

    def test_word_count_is_body_only(self):
        """Nav/footer/breadcrumb boilerplate must not inflate the count."""
        art, d = synth_article(1700, extra=(
            "<nav><a href=\"kinhnghiem.html\">menu</a></nav>"
            "<footer><a href=\"faq.html\">footer link</a></footer>"
            "<div class=\"breadcrumb\"><a href=\"antoan.html\">breadcrumb</a></div>"))
        try:
            self.assertEqual(len(art.main_content_words), 1700)
        finally:
            shutil.rmtree(d)

    def test_sample_rows_exempt(self):
        art, d = synth_article(400)
        try:
            row = dict(PROD_ROW, article_id="SAMPLE-KN-09", notes="SAMPLE fixture")
            fails, flags, warns, metrics = lib.evaluate_production_standard(
                art, row, self.rubric, self.ownership)
            self.assertEqual(fails + flags, [])
        finally:
            shutil.rmtree(d)


class ContextualLinkTests(unittest.TestCase):
    def setUp(self):
        self.rubric = lib.load_rubric()
        self.ownership = lib.load_ownership()

    def _links(self, n, hub=False):
        links = [("kinhnghiem.html", "kinh nghiệm")]
        if hub:
            links.append(("antoan.html", "hướng dẫn lái xe an toàn"))
        for i in range(n):
            links.append(("cam-nang/xe-may/xm-000%d.html" % i,
                          "cách chọn xe máy phù hợp"))
        return links

    def _eval(self, n, hub=False):
        art, d = synth_article(1700, links=self._links(n, hub))
        try:
            return lib.evaluate_production_standard(art, PROD_ROW, self.rubric,
                                                     self.ownership)
        finally:
            shutil.rmtree(d)

    def test_link_counts_3_4_5_valid(self):
        for n in (1, 2, 3):  # 1 base + hub + n => 3,4,5 total
            fails, flags, warns, metrics = self._eval(n, hub=True)
            self.assertEqual([f for f in flags if "contextual internal links" in f],
                             [], n)

    def test_link_count_2_review(self):
        fails, flags, warns, metrics = self._eval(0, hub=True)  # 2 total
        self.assertTrue(any("only 2 contextual internal links" in f for f in flags))

    def test_link_count_6_review(self):
        fails, flags, warns, metrics = self._eval(4, hub=True)  # 6 total
        self.assertTrue(any("(maximum 5)" in f for f in flags))

    def test_zero_links_never_pass(self):
        art, d = synth_article(1700)
        try:
            fails, flags, warns, metrics = lib.evaluate_production_standard(
                art, PROD_ROW, self.rubric, self.ownership)
            self.assertTrue(any("zero contextual internal links" in f for f in flags))
        finally:
            shutil.rmtree(d)

    def test_nav_footer_breadcrumb_links_excluded(self):
        links = [("antoan.html", "hướng dẫn lái xe an toàn"),
                 ("kinhnghiem.html", "kinh nghiệm"),
                 ("cam-nang/xe-may/xm-0001.html", "cách chọn xe máy phù hợp")]
        art, d = synth_article(1700, links=links, extra=(
            "<nav><a href=\"nav-x.html\">menu</a></nav>"
            "<footer><a href=\"footer-x.html\">footer</a></footer>"
            "<div class=\"breadcrumb\"><a href=\"bc-x.html\">breadcrumb</a></div>"
            "<a href=\"https://external.example.com/x\">external</a>"))
        try:
            self.assertEqual(len(art.contextual_links), 3)
        finally:
            shutil.rmtree(d)

    def test_parent_hub_detection(self):
        art, d = synth_article(1700, links=self._links(2, hub=True))
        try:
            li = art.analyze_contextual_links(PROD_ROW, self.ownership)
            self.assertTrue(li["parent_hub_present"])
            self.assertEqual(li["parent_hub"], "antoan.html")
        finally:
            shutil.rmtree(d)

    def test_missing_parent_hub_review(self):
        art, d = synth_article(1700, links=self._links(4, hub=False))
        try:
            fails, flags, warns, metrics = lib.evaluate_production_standard(
                art, PROD_ROW, self.rubric, self.ownership)
            self.assertTrue(any("parent category hub not contextually linked" in f
                                 for f in flags))
        finally:
            shutil.rmtree(d)

    def test_duplicate_anchors_detected(self):
        links = [("antoan.html", "hướng dẫn lái xe an toàn"),
                 ("kinhnghiem.html", "kinh nghiệm"),
                 ("cam-nang/xe-may/xm-0001.html", "kinh nghiệm"),
                 ("cam-nang/xe-may/xm-0002.html", "cách chọn xe máy phù hợp")]
        art, d = synth_article(1700, links=links)
        try:
            li = art.analyze_contextual_links(PROD_ROW, self.ownership)
            self.assertEqual(li["duplicate_anchor_count"], 1)
        finally:
            shutil.rmtree(d)

    def test_generic_anchors_warned(self):
        links = [("antoan.html", "hướng dẫn lái xe an toàn"),
                 ("kinhnghiem.html", "xem thêm"),
                 ("cam-nang/xe-may/xm-0001.html", "cách chọn xe máy phù hợp"),
                 ("cam-nang/xe-may/xm-0002.html", "kinh nghiệm")]
        art, d = synth_article(1700, links=links)
        try:
            li = art.analyze_contextual_links(PROD_ROW, self.ownership)
            self.assertIn("xem thêm", [a.lower() for a in li["generic_anchors"]])
        finally:
            shutil.rmtree(d)

    def test_repeated_commercial_anchor_strong_review(self):
        links = [("antoan.html", "hướng dẫn lái xe an toàn"),
                 ("kinhnghiem.html", "kinh nghiệm"),
                 ("thutuc.html", "thuê xe máy Hà Nội"),
                 ("phoco.html", "thuê xe máy Hà Nội")]
        art, d = synth_article(1700, links=links)
        try:
            fails, flags, warns, metrics = lib.evaluate_production_standard(
                art, PROD_ROW, self.rubric, self.ownership)
            self.assertTrue(any("repeated exact-match commercial anchor" in f
                                for f in flags))
            self.assertTrue(any("commercial landing-page links" in f for f in flags))
        finally:
            shutil.rmtree(d)

    def test_broken_link_fail(self):
        art, d = synth_article(1700, links=[("no-such-page-xyz.html", "link hỏng")])
        try:
            self.assertTrue(art.broken_internal_links())
        finally:
            shutil.rmtree(d)


class SeoStructureTests(unittest.TestCase):
    def test_heading_structure_reports_skips(self):
        art, d = synth_article(1700, extra="<h3>skip</h3><h2>ok</h2>")
        try:
            hs = art.heading_structure()
            self.assertEqual(hs["levels"], [1, 3, 2])
            self.assertTrue(any("skip" in p for p in hs["problems"]))
        finally:
            shutil.rmtree(d)

    def test_fixtures_have_schema_breadcrumb(self):
        art = lib.Article(os.path.join(HERE, "fixtures", "good.html"))
        self.assertTrue(art.has_article_schema)
        self.assertTrue(art.has_breadcrumb)


class BasePathTests(unittest.TestCase):
    def test_site_config(self):
        site = lib.load_site_config()
        self.assertEqual(site["origin"], "https://thuexemayhanoi.github.io")
        self.assertEqual(site["baseurl"], "/shop")
        self.assertEqual(site["site_url"], "https://thuexemayhanoi.github.io/shop")

    def test_category_index_links_use_shop_base(self):
        rows = [dict(PROD_ROW, output_path="cam-nang/an-toan/at-0001-x.html",
                     working_title="Tiêu đề", status="PUBLISHED")]
        page = gci.render_page("An toàn", rows, 1, 1, "antoan.html", "/shop")
        self.assertIn('href="/shop/cam-nang/an-toan/at-0001-x.html"', page)
        self.assertIn('href="/shop/antoan.html"', page)
        self.assertNotIn('href="/cam-nang/', page)
        self.assertNotIn('href="/antoan.html"', page)

    def test_category_index_no_root_only_links(self):
        rows = [dict(PROD_ROW, output_path="cam-nang/an-toan/at-0001-x.html",
                     working_title="Tiêu đề", status="PUBLISHED")]
        for base in ("/shop", "https://thuexemayhanoi.github.io/shop"):
            page = gci.render_page("An toàn", rows, 1, 1, "antoan.html", base)
            self.assertNotIn('href="/cam-nang/', page)

    def test_sitemap_article_urls_use_shop_base(self):
        rows = [dict(PROD_ROW, status="PUBLISHED")]
        urls = gsm.published_article_urls(rows, "https://thuexemayhanoi.github.io/shop")
        self.assertEqual(urls,
                         ["https://thuexemayhanoi.github.io/shop/cam-nang/an-toan/at-9001.html"])
        self.assertNotIn("https://thuexemayhanoi.github.io/cam-nang/", urls[0])

    def test_sitemap_status_rules(self):
        excluded = ["PLANNED", "WRITING", "QA", "REVIEW", "FAIL", "BLOCKED", "PASS"]
        for st in excluded:
            urls = gsm.published_article_urls([dict(PROD_ROW, status=st)],
                                             "https://thuexemayhanoi.github.io/shop")
            self.assertEqual(urls, [], st)
        urls = gsm.published_article_urls([dict(PROD_ROW, status="PUBLISHED")],
                                         "https://thuexemayhanoi.github.io/shop")
        self.assertEqual(len(urls), 1)
        self.assertIn("https://thuexemayhanoi.github.io/shop/", urls[0])

    def test_generators_forbidden_patterns_absent(self):
        row = dict(PROD_ROW, output_path="cam-nang/an-toan/at-0001-x.html",
                   working_title="Tiêu đề", status="PUBLISHED")
        page = gci.render_page("An toàn", [row], 1, 2, "antoan.html", "/shop")
        self.assertNotIn('href="/cam-nang/', page)
        self.assertNotIn('https://thuexemayhanoi.github.io/cam-nang/', page)


class ConcurrencyTests(unittest.TestCase):
    def test_workflow_has_global_concurrency(self):
        p = os.path.join(ROOT, ".github", "workflows", "article-batch.yml")
        text = io.open(p, encoding="utf-8").read()
        self.assertIn("concurrency:", text)
        self.assertIn("group: article-batch-production", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_no_cron_anywhere(self):
        for wf in os.listdir(os.path.join(ROOT, ".github", "workflows")):
            text = io.open(os.path.join(ROOT, ".github", "workflows", wf),
                           encoding="utf-8").read()
            self.assertNotIn("cron:", "%s has cron" % wf)


class MatrixStillPlannedTests(unittest.TestCase):
    def test_all_production_rows_planned(self):
        rows = [r for r in lib.load_matrix() if not lib.is_sample_row(r)]
        self.assertEqual(len(rows), 2000)
        statuses = set(r.get("status") for r in rows)
        self.assertEqual(statuses, {"PLANNED"})


if __name__ == "__main__":
    unittest.main()
