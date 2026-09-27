#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy-gate and compact-footer contracts for the content factory.

Gate invariants (publish deployment safety):
- an article file at its REAL output_path exists IFF the row is PUBLISHED
  (PASS and earlier statuses live in _drafts/, which Jekyll never deploys);
- a draft under _drafts/ never belongs to a PUBLISHED row;
- sitemap.xml carries exactly the PUBLISHED article URLs.

Footer invariants:
- _snippets/footer-compact.html matches what the generator produces from
  the taxonomy (no hand-edited second taxonomy copy);
- every page under cam-nang/ (articles, child hubs, topic index) carries
  the compact footer exactly once.
"""
import csv
import io
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

SNIPPET_PATH = os.path.join(ROOT, "_snippets", "footer-compact.html")
DRAFTS = os.path.join(ROOT, "_drafts")


def read(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def production_rows():
    with io.open(os.path.join(ROOT, "data", "content-matrix.csv"),
                 encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f)
                if not r["article_id"].startswith("SAMPLE")]


class PublishGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = production_rows()

    def test_published_rows_have_public_files(self):
        for r in self.rows:
            if (r["status"] or "").strip() != "PUBLISHED":
                continue
            self.assertTrue(
                os.path.isfile(os.path.join(ROOT, r["output_path"])),
                "PUBLISHED row without public file: %s" % r["article_id"])

    def test_unpublished_rows_have_no_public_file(self):
        leaked = []
        for r in self.rows:
            if (r["status"] or "").strip() == "PUBLISHED":
                continue
            if os.path.isfile(os.path.join(ROOT, r["output_path"])):
                leaked.append(r["article_id"])
        self.assertEqual(leaked, [],
                         "unpublished articles leaked to the deployed tree: "
                         "%s" % leaked)

    def test_drafts_never_hold_published_rows(self):
        if not os.path.isdir(DRAFTS):
            return
        for r in self.rows:
            draft = os.path.join(DRAFTS, r["output_path"])
            if os.path.isfile(draft):
                self.assertNotEqual(
                    (r["status"] or "").strip(), "PUBLISHED",
                    "PUBLISHED row still has a draft file: %s"
                    % r["article_id"])

    def test_sitemap_carries_exactly_published_articles(self):
        import re
        sm = read("sitemap.xml")
        urls = set(re.findall(r"<loc>([^<]*)</loc>", sm))
        published = {
            "https://thuexemayhanoi.github.io/shop/" + r["output_path"]
            for r in self.rows if (r["status"] or "").strip() == "PUBLISHED"}
        missing = sorted(published - urls)
        leaked = sorted(
            u for u in urls
            if u.startswith("https://thuexemayhanoi.github.io/shop/cam-nang/")
            and "/chu-de/" not in u and u not in published)
        self.assertEqual(missing, [], "sitemap missing PUBLISHED articles")
        self.assertEqual(leaked, [],
                         "sitemap carries non-PUBLISHED article URLs")


class CompactFooterTests(unittest.TestCase):
    def test_snippet_matches_generator_output(self):
        run = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "build_footer_snippet.py")],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(run.returncode, 0, run.stderr)
        current = open(SNIPPET_PATH, encoding="utf-8").read()
        with io.open(SNIPPET_PATH, encoding="utf-8") as f:
            onDisk = f.read()
        self.assertEqual(onDisk, current,
                         "_snippets/footer-compact.html diverged from the "
                         "generator; regenerate it (never hand-edit)")

    def test_snippet_has_taxonomy_links_only(self):
        snippet = open(SNIPPET_PATH, encoding="utf-8").read()
        self.assertIn("site-footer-compact", snippet)
        self.assertIn("Xem tất cả chủ đề", snippet)
        self.assertIn('href="/shop/cam-nang/chu-de/"', snippet)
        tax = json.loads(read("data/content-taxonomy.json"))
        for parent in tax["parents"]:
            self.assertIn('href="%s"' % parent["parent_hub"], snippet)
            self.assertIn(parent["parent_title"], snippet)
        self.assertNotIn("child_hub_url", snippet)
        self.assertEqual(snippet.count("<li>"), 6)

    def test_all_cam_nang_pages_carry_footer(self):
        pages = []
        for dirpath, dirnames, fnames in os.walk(os.path.join(ROOT, "cam-nang")):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in fnames:
                if fn.endswith(".html"):
                    pages.append(os.path.join(dirpath, fn))
        self.assertTrue(len(pages) >= 257,
                        "expected at least 257 cam-nang pages, got %d"
                        % len(pages))
        missing = []
        for p in pages:
            with io.open(p, encoding="utf-8") as f:
                html = f.read()
            if html.count('<footer class="site-footer-compact"') != 1:
                missing.append(os.path.relpath(p, ROOT))
        self.assertEqual(missing, [],
                         "cam-nang pages without exactly one compact footer")


if __name__ == "__main__":
    unittest.main()
