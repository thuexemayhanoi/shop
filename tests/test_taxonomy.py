#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taxonomy tests: canonical taxonomy + map consistency, writer manifest
taxonomy merge, child hub page wiring."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib
import run_article_batch as rb
import taxonomy_lib as tlib
import validate_taxonomy as vt


class TaxonomyRepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.prod = [r for r in cls.matrix if not lib.is_sample_row(r)]
        cls.tax = tlib.load_taxonomy()
        cls.mapping = tlib.load_taxonomy_map()

    def test_taxonomy_files_exist(self):
        self.assertTrue(self.tax)
        self.assertTrue(self.mapping)

    def test_every_production_row_mapped_exactly_once(self):
        ids = {r["article_id"] for r in self.prod}
        self.assertEqual(set(self.mapping), ids)
        self.assertEqual(len(self.mapping), 2000)

    def test_six_parents_56_children(self):
        self.assertEqual(len(self.tax["parents"]), 6)
        children = [c for p in self.tax["parents"]
                    for c in p["children"]]
        self.assertEqual(len(children), 56)
        self.assertEqual(len({c["child_id"] for c in children}), 56)
        self.assertEqual(len({c["child_slug"] for c in children}), 56)
        self.assertEqual(len({c["child_hub_url"] for c in children}), 56)

    def test_child_hub_url_pattern(self):
        for p in self.tax["parents"]:
            for c in p["children"]:
                self.assertEqual(
                    c["child_hub_url"],
                    "/shop/cam-nang/chu-de/%s.html" % c["child_slug"])
                self.assertEqual(
                    c["child_slug"], c["child_id"].lower().replace("_", "-"))

    def test_no_orphan_child_cluster(self):
        used = {m["child_id"] for m in self.mapping.values()}
        defined = {c["child_id"] for p in self.tax["parents"]
                   for c in p["children"]}
        self.assertFalse(defined - used, "orphan child clusters")

    def test_child_parent_agrees_with_matrix_category(self):
        parent_by_id = {p["parent_id"]: p["parent_title"]
                        for p in self.tax["parents"]}
        child_parent = {}
        for p in self.tax["parents"]:
            for c in p["children"]:
                child_parent[c["child_id"]] = p["parent_id"]
        for r in self.prod:
            e = self.mapping[r["article_id"]]
            self.assertEqual(child_parent[e["child_id"]], e["parent_id"])
            self.assertEqual(
                parent_by_id[e["parent_id"]], r["category"])

    def test_article_counts_reconcile(self):
        counts = {}
        for r in self.prod:
            cid = self.mapping[r["article_id"]]["child_id"]
            counts[cid] = counts.get(cid, 0) + 1
        for p in self.tax["parents"]:
            for c in p["children"]:
                self.assertEqual(c["article_count"],
                                 counts.get(c["child_id"], 0))

    def test_validate_taxonomy_passes(self):
        self.assertEqual(vt.validate(self.matrix), [])

    def test_validate_taxonomy_cli_exit_zero(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "validate_taxonomy.py")],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_writer_manifest_carries_taxonomy(self):
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
        row = next(r for r in self.prod if r["article_id"] == "KN-0002")
        ctx = rb.build_writer_context(row, self.matrix, ownership, facts,
                                      rubric, site, ROOT)
        tax = ctx["taxonomy"]
        self.assertEqual(tax["parent_id"], "KINH_NGHIEM")
        self.assertEqual(tax["child_cluster"], "KN_HONDA_WAVE")
        self.assertEqual(tax["child_hub"],
                         "/shop/cam-nang/chu-de/kn-honda-wave.html")
        self.assertTrue(ctx["link_standard"]["child_hub_link_recommended"])

    def test_child_hub_files_exist_and_list_published_only(self):
        hub_dir = os.path.join(ROOT, "cam-nang", "chu-de")
        self.assertTrue(os.path.isdir(hub_dir))
        for p in self.tax["parents"]:
            for c in p["children"]:
                f = os.path.join(hub_dir, c["child_slug"] + ".html")
                self.assertTrue(os.path.exists(f), f)
        self.assertTrue(os.path.exists(
            os.path.join(hub_dir, "index.html")))
        # every child hub is self-canonical and has exactly one H1
        for p in self.tax["parents"]:
            for c in p["children"]:
                f = os.path.join(hub_dir, c["child_slug"] + ".html")
                text = open(f, encoding="utf-8").read()
                self.assertEqual(text.count("<h1>"), 1)
                self.assertIn(
                    '<link rel="canonical" href="https://'
                    'thuexemayhanoi.github.io/shop/cam-nang/chu-de/%s.html">'
                    % c["child_slug"], text)
                # live article links only for PUBLISHED rows of this cluster
                pub = {r["article_id"] for r in self.prod
                       if r["status"] == "PUBLISHED"
                       and self.mapping[r["article_id"]]["child_id"]
                       == c["child_id"]}
                linked = set()
                for seg in text.split("/"):
                    parts = seg.split("-")
                    if (len(parts) >= 2
                            and parts[0] in ("kn", "at", "xm", "dl", "cd",
                                             "hd")
                            and parts[1].isdigit()):
                        linked.add(("%s-%s" % (parts[0], parts[1])).upper())
                self.assertEqual(linked, pub)

    def test_sitemap_contains_child_hubs(self):
        text = open(os.path.join(ROOT, "sitemap.xml"), encoding="utf-8").read()
        self.assertIn("/cam-nang/chu-de/", text)
        for p in self.tax["parents"]:
            for c in p["children"]:
                self.assertIn(c["child_slug"] + ".html</loc>", text)

    def test_no_cross_repo_urls_in_taxonomy(self):
        raw = open(os.path.join(ROOT, "data", "content-taxonomy.json"),
                   encoding="utf-8").read()
        for bad in ("/blog/", "/aichatbot/", "vanchinh"):
            self.assertNotIn(bad, raw)


class TaxonomyLibFallbackTests(unittest.TestCase):
    def test_empty_dir_degrades_gracefully(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tlib.load_taxonomy(d), {})
            self.assertEqual(tlib.load_taxonomy_map(d), {})
            self.assertEqual(tlib.writer_taxonomy_fields("KN-0001", d), None)
            self.assertEqual(tlib.child_index({}), {})


if __name__ == "__main__":
    unittest.main()
