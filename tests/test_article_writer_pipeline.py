#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writer-pipeline unit tests (NO real API calls — mock provider only).

Covers: writer called once per article, max-50, correct context, output
path, per-article isolation, PASS/PUBLISHED never rewritten, REVIEW repair
loop (max 3, BLOCKED after), FAIL never published, partial batch publish,
crash/resume idempotence, missing secret safe stop, provider timeout."""
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "providers"))

import article_lib as lib
import article_writer as aw
import run_article_batch as rb

_SITE = lib.load_site_config()["site_url"].rstrip("/")

_WORD_BANK = [
    "thuê xe máy", "mũ bảo hiểm", "kiểm tra xe", "giấy tờ tùy thân",
    "đi trong phố cổ", "lộ trình dài", "bảo dưỡng xe", "ánh sáng xe",
    "khoảng cách an toàn", "biển báo đường", "trời mưa", "đường trơn",
    "giữ khoảng cách", "đề phòng", "quan sát", "chuyển hướng",
    "dừng nghỉ", "trạm dừng", "đổ xăng", "vòng xoay hẹp",
]
_SENT_TAIL = [
    "trước khi xuất phát cho chuyến đi an toàn hơn",
    "khi di chuyển trong đô thị đông đúc",
    "để tránh những rủi ro không đáng có trên đường",
    "trong suốt hành trình khám phá thành phố",
    "giúp bạn chủ động hơn trong mọi tình huống",
    "là kinh nghiệm thực tế từ nhiều khách thuê xe",
    "khi thời tiết thay đổi bất ngờ trong ngày",
    "trong điều kiện giao thông Hà Nội",
]


def _pad_description(row):
    base = (row.get("working_title") or "Thuê xe máy Hà Nội") + \
        " — hướng dẫn chi tiết, kinh nghiệm thực tế và lưu ý quan trọng cho khách thuê."
    return base[:170]


def good_article_html(row, ctx=None):
    """Deterministic, genuinely passing production article for a matrix row.
    1600-2000 unique Vietnamese words, 4 contextual links (parent hub + 3
    others), full technical HTML structure. No prices, no unverified facts."""
    title = row.get("working_title") or row.get("primary_keyword") or "Bài viết"
    pk = row.get("primary_keyword") or ""
    hub = row.get("parent_hub") or "kinhnghiem.html"
    # Non-protected informational targets: district/FAQ pages. All category
    # hubs are protected commercial pages, so ONLY the parent hub may be
    # linked (commercial_links_max = 1).
    others = [("badinh.html", "hướng dẫn thuê xe máy ở Ba Đình"),
              ("caugiay.html", "kinh nghiệm thuê xe tại Cầu Giấy"),
              ("faq.html", "câu hỏi thường gặp về thuê xe máy")][:3]
    out_path = row.get("output_path") or ("cam-nang/%s.html" % row.get("slug", "x"))
    canonical = "%s/%s" % (_SITE, out_path)
    date = row.get("planned_date") or "2026-09-25"
    cat = row.get("category") or "Kinh nghiệm"

    def _wc(html_fragment):
        text = re.sub(r"<[^>]+>", " ", html_fragment)
        return len([w for w in text.split() if w])

    paras = []
    intro = ("<p>%s Bài viết này tổng hợp %s thành các phần rõ ràng, "
             "được viết cho khách hàng đang tìm hiểu %s.</p>"
             % (pk.capitalize(), pk, pk))
    paras.append(intro)
    n = 0
    s_idx = 0
    link_para_1 = ('<p>Bạn có thể mở rộng kiến thức qua <a href="%s">'
                   'cẩm nang chuyên mục của Mr Tú</a>, hoặc tham khảo '
                   '<a href="%s">%s</a> và <a href="%s">%s</a> trước '
                   'khi lên lộ trình.</p>'
                   % (hub, others[0][0], others[0][1],
                      others[1][0], others[1][1]))
    link_para_2 = ('<p>Nếu bạn cần bổ sung thông tin, xem thêm '
                   '<a href="%s">%s</a> do biên tập viên biên soạn.</p>'
                   % (others[2][0], others[2][1]))
    target = 1700
    while _wc("".join(paras)) < target:
        s_idx += 1
        paras.append("<h2>Phần %d — kinh nghiệm thực tế khi thuê xe</h2>"
                     % s_idx)
        for k in range(2):
            n += 1
            tail = _SENT_TAIL[(s_idx + k) % len(_SENT_TAIL)]
            bank = _WORD_BANK[(n * 3) % len(_WORD_BANK)]
            bank2 = _WORD_BANK[(n * 7 + 5) % len(_WORD_BANK)]
            pkbit = pk if n % 12 == 0 else "chuyến đi"
            paras.append(
                "<p>Điểm %d: khi %s ở Hà Nội, bạn nên %s (%s) %s, đặc biệt "
                "là %s — nhóm %d khách thuê đã trao đổi với tiệm về điều "
                "này và hầu hết đều đồng ý rằng việc %s trở nên thuận lợi "
                "hơn nhiều sau khi nắm được mẹo thứ %d.</p>"
                % (n, pkbit, bank, bank2, tail, bank, n, bank, n))
            if n == 4:
                paras.append(link_para_1)
            if n == 12:
                paras.append(link_para_2)
    body = "\n".join(paras)
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta name="author" content="Mr Tú">
<meta property="article:published_time" content="{date}">

<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":"{title}","author":{{"@type":"Person","name":"Mr Tú"}},"datePublished":"{date}"}}
</script>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Trang chủ","item":"/shop/"}},{{"@type":"ListItem","position":2,"name":"{cat}","item":"/shop/{hub}"}},{{"@type":"ListItem","position":3,"name":"{title}","item":"{canonical}"}}]}}
</script>
</head>
<body>
<main>
<h1>{title}</h1>

{body}

</main>
</body>
</html>""".format(title=title, desc=_pad_description(row), canonical=canonical,
                  date=date, cat=cat, hub=hub, body=body)


class FakeProvider(object):
    """Mock writer. Records calls; per-article behavior is configurable."""

    name = "fake"

    def __init__(self, fail_write_ids=(), raise_type=None, repair_html=None,
                 never_repair=False):
        self.calls = []
        self.contexts = []
        self.fail_write_ids = set(fail_write_ids)
        self.raise_type = raise_type or RuntimeError
        self.repair_html = repair_html
        self.never_repair = never_repair

    def is_configured(self):
        return True

    def write_article(self, row, ctx):
        self.calls.append(("write", row["article_id"]))
        self.contexts.append(ctx)
        if row["article_id"] in self.fail_write_ids:
            raise self.raise_type("provider boom for %s" % row["article_id"])
        return good_article_html(row, ctx)

    def repair_article(self, row, ctx, html, qa_report):
        self.calls.append(("repair", row["article_id"]))
        if self.never_repair:
            return html  # unchanged -> QA verdict stays REVIEW
        if self.repair_html is not None:
            return self.repair_html(row, ctx)
        # default repair: return a genuinely fixed article
        return good_article_html(row, ctx)


class PipelineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.ownership = lib.load_ownership()
        cls.facts = lib.load_business_facts()
        cls.rubric = lib.load_rubric()
        cls.site = lib.load_site_config()
        cls.prod = [r for r in cls.matrix if not lib.is_sample_row(r)]
        cls.by_id = {r["article_id"]: r for r in cls.prod}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # article output paths live under the tmp root, but link targets
        # (category hubs) resolve against the real repo root as designed.
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _row(self, article_id, status="PLANNED"):
        row = dict(self.by_id[article_id])
        row["status"] = status
        row["output_path"] = "cam-nang-test/%s.html" % row["slug"]
        return row

    def _qa_env(self):
        return self.matrix, self.ownership, self.facts, self.rubric


class WriterPipelineTests(PipelineTestCase):
    # KN-0001 has requires_sources=false — safe for generated fixtures.

    def test_writer_called_once_and_output_written_to_correct_path(self):
        row = self._row("KN-0001")
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(provider.calls, [("write", "KN-0001")])
        out = os.path.join(self.tmp, row["output_path"])
        self.assertTrue(os.path.isfile(out), "article not written to output_path")
        self.assertEqual(entry["outcome"], "PASS", entry)
        self.assertEqual(updates["KN-0001"]["status"], "PASS")
        self.assertGreaterEqual(entry["score"], 90)

    def test_writer_receives_full_context(self):
        row = self._row("KN-0001")
        provider = FakeProvider()
        rb.process_article(row, *self._qa_env(), repo_root=self.tmp,
                           provider=provider, site=self.site)
        ctx = provider.contexts[0]
        for key in ("article_id", "category", "working_title", "primary_keyword",
                    "search_intent", "output_path", "parent_hub",
                    "protected_intents", "business_facts", "approved_price_data",
                    "unapproved_models", "deposit_wording", "target_min_words",
                    "target_max_words", "contextual_internal_links_min",
                    "contextual_internal_links_max", "commercial_links_max",
                    "url_base", "neighbor_topics", "canonical_url"):
            self.assertIn(key, ctx, "writer context missing %s" % key)
        self.assertEqual(ctx["target_min_words"], 1600)
        self.assertEqual(ctx["target_max_words"], 2000)
        self.assertEqual(ctx["article_id"], "KN-0001")
        # unverified owner facts must never reach the writer
        self.assertNotIn("requires_owner_confirmation", ctx["business_facts"])
        self.assertTrue(ctx["neighbor_topics"])

    def test_one_writer_error_does_not_kill_batch(self):
        rows = [self._row(i) for i in
                ("KN-0001", "XM-0001", "DL-0001", "CD-0001")]
        provider = FakeProvider(fail_write_ids={"XM-0001"})
        updates, articles, guard = rb.run_writer_pipeline(
            rows, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["KN-0001"], "PASS")
        self.assertEqual(outcomes["DL-0001"], "PASS")
        self.assertEqual(outcomes["CD-0001"], "PASS")
        self.assertEqual(outcomes["XM-0001"], "PROVIDER_ERROR")
        # failed row returns safely to PLANNED (retryable), others PASS
        self.assertEqual(updates["XM-0001"]["status"], "PLANNED")
        self.assertEqual(guard.errors, 1)

    def test_pass_not_rewritten(self):
        row = self._row("KN-0001", status="PASS")
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(entry["outcome"], "SKIP_PASS_PUBLISHED")
        self.assertEqual(provider.calls, [])  # never called
        self.assertEqual(updates, {})

    def test_published_not_rewritten(self):
        row = self._row("KN-0001", status="PUBLISHED")
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(entry["outcome"], "SKIP_PASS_PUBLISHED")
        self.assertEqual(provider.calls, [])
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, row["output_path"])))

    def test_review_invokes_repair_and_passes(self):
        # KN-0002 also requires_sources=false? use KN-0001 with a broken
        # first draft, then the repair returns a good article.
        row = self._row("KN-0001")
        path = os.path.join(self.tmp, row["output_path"])
        os.makedirs(os.path.dirname(path))
        # craft a REVIEW-grade draft: too few contextual links
        broken = good_article_html(row)
        import re as _re
        broken = _re.sub(r'<p>Bạn có thể mở rộng kiến thức.*?</p>', "", broken,
                         flags=_re.S)
        broken = _re.sub(r'<p>Nếu bạn cần bổ sung.*?</p>', "", broken,
                         flags=_re.S)
        io.open(path, "w", encoding="utf-8").write(broken)
        row["status"] = "QA"
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(entry["outcome"], "PASS", entry)
        self.assertIn(("repair", "KN-0001"), provider.calls)
        self.assertGreaterEqual(entry["repair_attempts"], 1)

    def test_repair_max_3_then_blocked(self):
        row = self._row("KN-0001")
        path = os.path.join(self.tmp, row["output_path"])
        os.makedirs(os.path.dirname(path))
        import re as _re
        broken = good_article_html(row)
        broken = _re.sub(r'<a href="[^"]+">', "<em>",
                         broken).replace("</a>", "</em>")
        io.open(path, "w", encoding="utf-8").write(broken)
        row["status"] = "REVIEW"
        provider = FakeProvider(never_repair=True)  # repair never fixes
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(entry["outcome"], "BLOCKED")
        # writer asked to repair exactly MAX_REPAIR_ATTEMPTS times
        repairs = [c for c in provider.calls if c[0] == "repair"]
        self.assertEqual(len(repairs), rb.MAX_REPAIR_ATTEMPTS)
        self.assertEqual(updates["KN-0001"]["status"], "BLOCKED")

    def test_fail_never_published(self):
        row = self._row("KN-0001")
        # a wrong-price article is a hard fact-safety FAIL
        path = os.path.join(self.tmp, row["output_path"])
        os.makedirs(os.path.dirname(path))
        html = good_article_html(row).replace(
            "trước khi xuất phát cho chuyến đi an toàn hơn",
            "giá thuê Honda Vision chỉ 300.000đ mỗi ngày rất rẻ", 1)
        assert "300.000đ" in html
        io.open(path, "w", encoding="utf-8").write(html)
        row["status"] = "QA"
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        self.assertEqual(entry["outcome"], "FAIL")
        self.assertEqual(updates["KN-0001"]["status"], "FAIL")
        self.assertNotEqual(updates["KN-0001"]["status"], "PUBLISHED")

    def test_partial_batch_publishing(self):
        """43-style: some PASS, some FAIL/PROVIDER_ERROR — PASS still pass."""
        ids = ["KN-0001", "XM-0001", "DL-0001", "CD-0001", "KN-0002", "HD-0001"]
        rows = [self._row(i) for i in ids]
        provider = FakeProvider(fail_write_ids={"XM-0001"})
        updates, articles, guard = rb.run_writer_pipeline(
            rows, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        passed = [a for a in articles if a["outcome"] == "PASS"]
        self.assertGreater(len(passed), 0, "at least some must PASS")
        stats = rb.summarize(articles)
        self.assertEqual(stats["pass"], len(passed))
        self.assertEqual(stats["provider_errors"], 1)
        # publishable = exactly the PASS articles
        publishable = [k for k, v in updates.items() if v.get("status") == "PASS"]
        self.assertEqual(sorted(publishable),
                         sorted(a["article_id"] for a in passed))

    def test_max_batch_size_50(self):
        rows = [dict(r) for r in self.prod[:120]]
        for r in rows:
            r["status"] = "PLANNED"
        self.assertEqual(len(rb.select_claim_rows(rows, 500)), 50)
        self.assertLessEqual(rb.MAX_BATCH_SIZE, 50)

    def test_crash_resume_idempotent(self):
        """Runner crashes after writing 2 files; resume finishes the rest
        without duplicates and never rewrites completed PASS files."""
        ids = ["KN-0001", "DL-0001", "CD-0001"]
        rows = [self._row(i) for i in ids]
        # simulate crash: first article already written + PASS, second
        # written but stuck in QA, third not started (stale WRITING).
        for row in rows:
            os.makedirs(os.path.dirname(
                os.path.join(self.tmp, row["output_path"])), exist_ok=True)
        io.open(os.path.join(self.tmp, rows[0]["output_path"]), "w",
                encoding="utf-8").write(good_article_html(rows[0]))
        io.open(os.path.join(self.tmp, rows[1]["output_path"]), "w",
                encoding="utf-8").write(good_article_html(rows[1]))
        rows[0]["status"] = "PASS"
        rows[1]["status"] = "QA"
        rows[2]["status"] = "WRITING"  # claimed, file never written
        resume = rb.select_resume_rows(rows, self.tmp, 50)
        stale = rb.select_stale_rows(rows, self.tmp, 50)
        self.assertEqual([r["article_id"] for r in resume], ["DL-0001"])
        self.assertEqual([r["article_id"] for r in stale], ["CD-0001"])
        provider = FakeProvider()
        updates, articles, guard = rb.run_writer_pipeline(
            resume + stale, *self._qa_env(), repo_root=self.tmp,
            provider=provider, site=self.site)
        # PASS row untouched; the other two completed; exactly one write call
        write_ids = [c[1] for c in provider.calls if c[0] == "write"]
        self.assertNotIn("KN-0001", write_ids)
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["DL-0001"], "PASS")
        self.assertEqual(outcomes["CD-0001"], "PASS")
        # no duplicate files: each path exists exactly once (by construction)
        for row in rows:
            self.assertTrue(os.path.isfile(
                os.path.join(self.tmp, row["output_path"])))

    def test_missing_secret_safe_stop(self):
        """Provider selected but key absent: rows stay PLANNED, nothing
        fabricated."""
        env = {"WRITER_PROVIDER": "mistral"}  # no MISTRAL_API_KEY
        from providers import load_configured_provider
        provider = load_configured_provider(env)
        self.assertIsNotNone(provider)
        self.assertFalse(provider.is_configured())
        row = self._row("KN-0001")
        ctx = rb.build_writer_context(row, self.matrix, self.ownership,
                                      self.facts, self.rubric, self.site,
                                      self.tmp)
        with self.assertRaises(aw.WriterSecretMissing):
            provider.write_article(row, ctx)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, row["output_path"])))

    def test_no_provider_selected_is_null(self):
        provider = aw.get_provider()
        from providers import load_configured_provider
        self.assertIsNone(load_configured_provider({}))
        self.assertIsInstance(provider, aw._NullProvider)
        with self.assertRaises(aw.WriterNotConfigured):
            provider.write_article({"article_id": "X"}, {})

    def test_provider_timeout_handled(self):
        rows = [self._row("KN-0001"), self._row("DL-0001")]
        provider = FakeProvider(fail_write_ids={"KN-0001"},
                                raise_type=TimeoutError)
        updates, articles, guard = rb.run_writer_pipeline(
            rows, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site)
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["KN-0001"], "PROVIDER_ERROR")
        self.assertEqual(outcomes["DL-0001"], "PASS")
        self.assertEqual(updates["KN-0001"]["status"], "PLANNED")

    def test_guard_stops_new_articles_when_errors_spike(self):
        guard = rb._Guard()
        for i in range(10):
            guard.note_attempt()
        for i in range(rb.PROVIDER_ERROR_FLOOR + 1):
            guard.note_error()
        self.assertTrue(guard.should_stop())

    def test_guard_does_not_trip_on_small_error_count(self):
        guard = rb._Guard()
        for i in range(10):
            guard.note_attempt()
        guard.note_error()
        self.assertFalse(guard.should_stop())

    def test_concurrency_bounded(self):
        self.assertLessEqual(rb.MAX_CONCURRENCY, 3)
        rows = [self._row(i) for i in ("KN-0001", "DL-0001", "CD-0001")]
        provider = FakeProvider()
        updates, articles, guard = rb.run_writer_pipeline(
            rows, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site, concurrency=rb.MAX_CONCURRENCY)
        self.assertEqual(len([a for a in articles if a["outcome"] == "PASS"]), 3)

    def test_dry_run_writes_nothing(self):
        row = self._row("KN-0001")
        provider = FakeProvider()
        updates, entry = rb.process_article(
            row, *self._qa_env(), repo_root=self.tmp, provider=provider,
            site=self.site, dry_run=True)
        self.assertEqual(entry["outcome"], "WOULD_WRITE")
        self.assertEqual(provider.calls, [])
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, row["output_path"])))


class WriterContextTests(PipelineTestCase):
    def test_context_matches_mission_requirements(self):
        row = self.by_id["KN-0001"]
        ctx = rb.build_writer_context(row, self.matrix, self.ownership,
                                      self.facts, self.rubric, self.site,
                                      ROOT)
        self.assertEqual(ctx["url_base"], _SITE)
        self.assertEqual(ctx["baseurl"], "/shop")
        self.assertIn("2.000.000", ctx["deposit_wording"])
        self.assertTrue(ctx["protected_intents"])
        self.assertEqual(ctx["commercial_link_target"], "thutuc.html")
        self.assertTrue(ctx["neighbor_topics"])
        self.assertNotIn("requires_owner_confirmation", ctx["business_facts"])


if __name__ == "__main__":
    unittest.main()
