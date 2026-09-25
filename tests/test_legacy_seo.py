#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy root-page SEO tests (pass 2).

Covers: 1 H1 per page, heading hierarchy, title/meta/canonical presence,
broken local links, JSON-LD validity, stale business-claim patterns
(including lienhe.html), homepage ownership links, and specialist-page
intent retention. Reuses the patterns in scripts/audit_legacy_pages.py.
"""
import glob
import io
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import audit_legacy_pages as audit

SITE = "https://thuexemayhanoi.github.io/shop/"
PAGES = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.html")))


def read(name):
    with io.open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TestH1AndHeadings(unittest.TestCase):
    def test_exactly_one_h1_per_page(self):
        for p in PAGES:
            t = audit.strip_noise(read(p))
            h1s = re.findall(r"<h1[^>]*>", t, re.I)
            self.assertEqual(len(h1s), 1, "%s has %d H1 tags" % (p, len(h1s)))

    def test_no_hidden_or_duplicate_h1(self):
        for p in PAGES:
            t = read(p)
            hidden = re.findall(r"<h1[^>]*(display\s*:\s*none|visibility\s*:\s*hidden)", t, re.I)
            self.assertFalse(hidden, "%s has a hidden H1" % p)

    def test_no_heading_hierarchy_skips(self):
        for p in PAGES:
            t = audit.strip_noise(read(p))
            prev = 0
            for m in re.finditer(r"<(h[1-6])[^>]*>", t, re.I):
                lvl = int(m.group(1)[1])
                self.assertTrue(prev == 0 or lvl <= prev + 1,
                                "%s: H%d -> H%d skip" % (p, prev, lvl))
                prev = lvl


class TestMetaAndCanonical(unittest.TestCase):
    def test_title_meta_canonical_present(self):
        for p in PAGES:
            t = audit.strip_noise(read(p))
            title = re.search(r"<title[^>]*>", t, re.I)
            meta = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', t, re.I)
            canonical = re.search(r'rel="canonical"\s+href="([^"]*)"', t, re.I)
            self.assertIsNotNone(title, "%s missing title" % p)
            self.assertIsNotNone(meta, "%s missing meta description" % p)
            self.assertGreaterEqual(len(meta.group(1).strip()), 50,
                                   "%s meta description too short" % p)
            self.assertIsNotNone(canonical, "%s missing canonical" % p)
            self.assertNotIn("noindex", t.lower().replace("x", "x")
                             if False else t, "%s accidental noindex" % p)

    def test_self_canonical_except_nhap(self):
        for p in PAGES:
            t = read(p)
            can = re.search(r'rel="canonical"\s+href="([^"]*)"', t, re.I).group(1)
            if p == "nhap.html":
                self.assertEqual(can.rstrip("/"), SITE.rstrip("/"),
                                 "nhap.html should keep homepage canonical")
            elif p == "index.html":
                self.assertEqual(can.rstrip("/"), SITE.rstrip("/"),
                                 "index.html must self-canonical")
            else:
                self.assertTrue(can.rstrip("/").endswith("/" + p),
                                "%s canonical points to %s" % (p, can))

    def test_unique_titles(self):
        titles = {}
        for p in PAGES:
            t = audit.strip_noise(read(p))
            m = re.search(r"<title[^>]*>([\s\S]*?)</title>", t, re.I)
            titles.setdefault(m.group(1).strip(), []).append(p)
        dups = {k: v for k, v in titles.items() if len(v) > 1}
        self.assertFalse(dups, "duplicate titles: %s" % dups)


class TestLinksAndSchema(unittest.TestCase):
    def test_no_broken_local_links(self):
        texts = audit.collect_texts(PAGES)
        for p in PAGES:
            res = audit.audit_page(os.path.join(ROOT, p), texts, set(PAGES))
            self.assertEqual(res["broken_links"], [], "%s broken links: %s" % (p, res["broken_links"]))

    def test_valid_jsonld(self):
        for p in PAGES:
            for blk in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>',
                                  read(p), re.I):
                json.loads(blk)  # raises on invalid

    def test_no_fake_review_schema(self):
        for p in PAGES:
            for blk in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>',
                                  read(p), re.I):
                data = json.loads(blk)
                self.assertNotIn("AggregateRating", json.dumps(data), "%s has fake rating schema" % p)


class TestStaleClaims(unittest.TestCase):
    def test_no_stale_business_claims(self):
        texts = audit.collect_texts(PAGES)
        for p in PAGES:
            res = audit.audit_page(os.path.join(ROOT, p), texts, set(PAGES))
            self.assertEqual(res["business_fact_flags"], [],
                             "%s stale claims: %s" % (p, res["business_fact_flags"]))

    def test_deposit_wording_consistent(self):
        for p in PAGES:
            t = audit.visible(read(p))
            for bad in ("miễn cọc", "không cần cọc", "không phải cọc", "giảm cọc"):
                self.assertNotIn(bad.lower(), t.lower(), "%s claims %r" % (p, bad))


class TestContactPage(unittest.TestCase):
    def test_lienhe_clean(self):
        raw = read("lienhe.html")
        clean = audit.strip_noise(raw)
        segments = [audit.visible(raw)]
        for attr in ("description",):
            segments.append(" ".join(re.findall(
                r'(?:name|property)="%s"\s+content="([^"]*)"' % attr, clean)))
        seg = "\n".join(segments).lower()
        for bad in ("24/7", "15 phút", "15p", "17 phúc tân",
                    "cứu hộ 24", "hotline 24", "phản hồi trong vòng 24h"):
            self.assertNotIn(bad.lower(), seg, "lienhe contains %r" % bad)
        self.assertIn("081.665.9199", raw)
        vis = audit.visible(raw)
        self.assertLessEqual(len(vis.split()), 750, "lienhe too bloated")
        self.assertGreaterEqual(len(vis.split()), 350, "lienhe too thin")

    def test_lienhe_useful_sections(self):
        t = read("lienhe.html")
        self.assertIn("Thông Tin Nên Gửi Khi Liên Hệ", t)
        self.assertIn("Xác Nhận Giá Và Điều Kiện Thuê", t)
        self.assertIn("2.000.000 – 5.000.000đ", t)


class TestHomepageAndSpecialists(unittest.TestCase):
    def test_homepage_coverage(self):
        t = audit.strip_noise(read("index.html"))
        vis = audit.visible(read("index.html")).lower()
        self.assertIn("thuê xe máy hà nội", vis)
        self.assertIn("phố cổ", vis)
        self.assertIn("hoàn kiếm", vis)
        self.assertIn("giá thuê", vis)
        main = re.search(r"<main[\s\S]*?</main>", read("index.html"), re.I).group(0)
        for target in ("phoco.html", "hoankiem.html", "banggia.html"):
            self.assertIn(target, main, "homepage missing contextual link to %s" % target)

    def test_specialist_intents_retained(self):
        checks = {
            "phoco.html": ["phố cổ"],
            "hoankiem.html": ["hoàn kiếm"],
            "banggia.html": ["giá thuê xe máy"],
        }
        for p, kws in checks.items():
            t = audit.visible(read(p)).lower()
            title = re.search(r"<title[^>]*>([\s\S]*?)</title>",
                              read(p), re.I).group(1).lower()
            for kw in kws:
                self.assertIn(kw, title, "%s title lost intent %r" % (p, kw))
                self.assertIn(kw, t, "%s body lost intent %r" % (p, kw))


if __name__ == "__main__":
    unittest.main()
