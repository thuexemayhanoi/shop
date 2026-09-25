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
        # local targets include EVERY .html file committed in the repo —
        # factory hubs legitimately link to published cam-nang articles,
        # so the file set must grow with production, not stay legacy-only
        local_files = set(PAGES)
        for dirpath, _dirs, files in os.walk(ROOT):
            if os.path.relpath(dirpath, ROOT).startswith("."):
                continue
            for f in files:
                if f.endswith(".html"):
                    local_files.add(os.path.relpath(
                        os.path.join(dirpath, f), ROOT).replace(os.sep, "/"))
        texts = audit.collect_texts(PAGES)
        for p in PAGES:
            res = audit.audit_page(os.path.join(ROOT, p), texts, local_files)
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



class TestConfigAwareFactSafety(unittest.TestCase):
    """Pass 3: config-aware fact-safety gate for unverified owner facts.

    config/business-facts.json keeps opening_hours, support_hours,
    delivery_or_pickup and late_return_policy as null (unverified). While a
    field is null, hard claims about it must FAIL the gate; neutral
    conditional wording must PASS.
    """

    def test_unverified_fields_stay_null(self):
        conf = audit.load_owner_confirmation()
        for field in ("opening_hours", "support_hours",
                      "delivery_or_pickup", "late_return_policy"):
            self.assertIsNone(conf.get(field),
                              "%s must stay null until owner-confirmed" % field)

    def test_unverified_opening_hours_claims_fail(self):
        conf = audit.load_owner_confirmation()
        for text in ("8h-17h", "8h–17h", "giờ mở cửa",
                     "Cửa hàng đang mở (8h-17h)", "08:00 – 17:00"):
            self.assertIn("unverified_opening_hours",
                          audit.fact_safety_flags(text, conf), text)

    def test_unverified_support_hours_claims_fail(self):
        conf = audit.load_owner_confirmation()
        for text in ("Hỗ trợ 24/7", "Hỗ trợ Online 24/7", "phản hồi siêu tốc"):
            self.assertIn("unverified_support_hours",
                          audit.fact_safety_flags(text, conf), text)

    def test_unverified_delivery_claims_fail(self):
        conf = audit.load_owner_confirmation()
        for text in ("Giao xe tận sảnh khách sạn theo lịch hẹn trong giờ mở cửa.",
                     "Mr Tú hỗ trợ giao xe tận nơi khu vực Long Biên.",
                     "Giao xe nhanh tại Nguyễn Trãi.",
                     "Chi nhánh Long Biên giúp giao xe phía bên kia sông Hồng."):
            self.assertIn("unverified_delivery",
                          audit.fact_safety_flags(text, conf), text)

    def test_conditional_delivery_wording_passes(self):
        conf = audit.load_owner_confirmation()
        for text in ("Liên hệ để xác nhận khả năng giao/nhận xe tại khu vực của bạn.",
                     "Vui lòng liên hệ trước để sắp xếp.",
                     "Giao/nhận xe theo thỏa thuận với Mr Tú."):
            self.assertEqual(audit.fact_safety_flags(text, conf), [], text)

    def test_unverified_late_return_claims_fail(self):
        conf = audit.load_owner_confirmation()
        for text in ("Trả xe trễ tính thêm phí theo giờ",
                     "Trả xe muộn sẽ tính phí phụ thu 20.000đ - 30.000đ/giờ.",
                     "phí phạt quá giờ"):
            self.assertIn("unverified_late_return",
                          audit.fact_safety_flags(text, conf), text)

    def test_conditional_late_return_wording_passes(self):
        conf = audit.load_owner_confirmation()
        for text in ("Nếu cần gia hạn, vui lòng liên hệ trước để xác nhận điều kiện áp dụng.",
                     "Nếu cần gia hạn hoặc thay đổi thời gian trả xe, vui lòng liên hệ trước để xác nhận điều kiện áp dụng."):
            self.assertEqual(audit.fact_safety_flags(text, conf), [], text)

    def test_hard_hours_not_excused_by_conditional_wording(self):
        conf = audit.load_owner_confirmation()
        text = "Liên hệ Mr Tú (giờ mở cửa 8h-17h) hoặc xem bảng giá."
        self.assertIn("unverified_opening_hours",
                      audit.fact_safety_flags(text, conf))

    def test_zero_fact_safety_flags_on_all_root_pages(self):
        conf = audit.load_owner_confirmation()
        for p in PAGES:
            raw = read(p)
            self.assertEqual(audit.fact_safety_flags(raw, conf), [],
                             "%s contains hard claims about unverified facts" % p)

    def test_status_widget_neutral_everywhere(self):
        for p in PAGES:
            raw = read(p)
            self.assertNotIn("Cửa hàng đang mở", raw,
                             "%s status widget asserts unverified open state" % p)
            self.assertNotIn("Ngoài giờ mở cửa", raw,
                             "%s status widget asserts unverified hours" % p)
            self.assertNotIn("hours >= 8 && hours < 17", raw,
                             "%s infers open/closed from unverified hours" % p)

    def test_phone_preserved(self):
        for p in ("index.html", "lienhe.html", "hoankiem.html"):
            self.assertIn("081.665.9199", read(p), "%s lost the trusted phone" % p)


if __name__ == "__main__":
    unittest.main()
