#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writer-pipeline unit tests for the API-free factory (NO API, NO provider).

The external Mistral agent is the writer; these tests verify the
deterministic pipeline around it: agent claims rows (--prepare-agent),
files are written at real output paths, --qa gates them, PASS/PUBLISHED
are never rewritten, repair budget is enforced, publish scope is the
resolved batch only, and nothing ever requires MISTRAL_API_KEY.
"""
import io
import json
import os
import re
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
import article_writer as aw
import run_article_batch as rb

_SITE = lib.load_site_config()["site_url"].rstrip("/")


def reset_matrix_to_planned(path):
    """Rewrite a SANDBOX copy of content-matrix.csv with every production
    row reset to PLANNED (published_date cleared), so runner tests
    exercise the claim/publish mechanism itself and stay independent of
    REAL production progress. SAMPLE rows are left untouched."""
    import csv
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


def good_article_html(row, ctx=None, sources_html=""):
    """Deterministic, genuinely passing production article for a matrix row.
    1600-2000 unique Vietnamese words, 4 contextual links (parent hub + 3
    informational pages), full technical HTML. datePublished = the ACTUAL
    date from the writer context (never the future planned_date)."""
    title = row.get("working_title") or row.get("primary_keyword") or "Bài viết"
    pk = row.get("primary_keyword") or ""
    hub = row.get("parent_hub") or "kinhnghiem.html"
    # Informational targets: district/FAQ pages. Category hubs are protected
    # informational pages; NONE of these links is a commercial landing page,
    # so the single commercial-link budget stays untouched.
    others = [("badinh.html", "hướng dẫn thuê xe máy ở Ba Đình"),
              ("caugiay.html", "kinh nghiệm thuê xe tại Cầu Giấy"),
              ("faq.html", "câu hỏi thường gặp về thuê xe máy")][:3]
    out_path = row.get("output_path") or ("cam-nang/%s.html" % row.get("slug", "x"))
    canonical = "%s/%s" % (_SITE, out_path)
    date = (ctx or {}).get("date_published") or row.get("planned_date") \
        or "2026-09-25"
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
    if sources_html:
        paras.append("<h2>Nguồn tham khảo</h2>")
        paras.append(sources_html)
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


APPROVED_SOURCE = ('<p>Xem bản gốc tại <a href='
                  '"https://vanban.chinhphu.vn/?page=nghi-dinh-168-2024-nd-cp">'
                  'Nghị định 168/2024/NĐ-CP</a> trên cổng văn bản Chính phủ.</p>')


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

    def _ctx(self, row):
        return rb.build_writer_context(row, self.matrix, self.ownership,
                                       self.facts, self.rubric, self.site)

    def _write(self, row, ctx=None, sources_html=""):
        path = os.path.join(self.tmp, row["output_path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        io.open(path, "w", encoding="utf-8").write(
            good_article_html(row, ctx, sources_html))
        return path

    def _qa(self, rows, repo_root=None):
        return rb.run_qa_for_batch(rows, self.matrix, self.ownership,
                                   self.facts, self.rubric,
                                   repo_root or self.tmp)


class AgentPipelineTests(PipelineTestCase):
    # KN-0001 has requires_sources=false — safe for generated fixtures.

    def test_written_article_passes_qa(self):
        row = self._row("KN-0001", status="WRITING")
        self._write(row, self._ctx(row))
        updates, articles = self._qa([row])
        self.assertEqual(articles[0]["outcome"], "PASS",
                         articles[0]["quality_failures"])
        self.assertGreaterEqual(articles[0]["score"], 90)
        self.assertEqual(updates["KN-0001"]["status"], "PASS")

    def test_writer_context_carries_full_standard(self):
        row = self._row("KN-0001")
        ctx = self._ctx(row)
        self.assertEqual(ctx["word_standard"]["target_min_words"], 1600)
        self.assertEqual(ctx["word_standard"]["target_max_words"], 2000)
        self.assertEqual(ctx["link_standard"]["contextual_internal_links_min"], 3)
        self.assertEqual(ctx["link_standard"]["contextual_internal_links_max"], 5)
        self.assertTrue(ctx["link_standard"]["parent_hub_link_required"])
        self.assertEqual(ctx["link_standard"]["commercial_links_max"], 1)
        self.assertTrue(ctx["canonical_url"].endswith(row["output_path"]))
        self.assertTrue(ctx["protected_intents"])
        self.assertTrue(ctx["neighbor_topics"])
        # ACTUAL date, never the future planned_date
        self.assertEqual(ctx["date_published"], rb.today())
        self.assertNotEqual(ctx["date_published"], row["planned_date"])

    def test_requires_sources_row_fails_qa_without_sources(self):
        """AT-0001 requires_sources=true: no 'Nguồn tham khảo' section with
        an approved official URL => the source gate FAILS the article."""
        row = self._row("AT-0001", status="WRITING")
        self._write(row, self._ctx(row))  # no sources section
        updates, articles = self._qa([row])
        self.assertEqual(articles[0]["outcome"], "FAIL")
        self.assertTrue(any("approved official source" in f
                            for f in articles[0]["quality_failures"]))
        self.assertEqual(updates["AT-0001"]["status"], "FAIL")

    def test_requires_sources_row_passes_qa_with_approved_source(self):
        row = self._row("AT-0001", status="WRITING")
        self._write(row, self._ctx(row), sources_html=APPROVED_SOURCE)
        updates, articles = self._qa([row])
        self.assertEqual(articles[0]["outcome"], "PASS",
                         articles[0]["quality_failures"])

    def test_pass_and_published_rows_never_rewritten(self):
        row_p = self._row("KN-0001", status="PASS")
        row_pub = self._row("XM-0001", status="PUBLISHED")
        self._write(row_p)
        self._write(row_pub)
        got = rb.select_qa_rows([row_p, row_pub], self.tmp, 50)
        self.assertEqual(got, [])
        # and publishing scope ignores PUBLISHED rows
        self.assertEqual(rb.select_publish_rows([row_p, row_pub], self.tmp),
                         [row_p])

    def test_unwritten_row_isolated_from_written_rows(self):
        written = self._row("KN-0001", status="WRITING")
        unwritten = self._row("XM-0001", status="WRITING")
        self._write(written, self._ctx(written))
        updates, articles = self._qa([written, unwritten])
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["KN-0001"], "PASS")
        self.assertEqual(outcomes["XM-0001"], "NOT_WRITTEN")
        self.assertNotIn("XM-0001", updates)  # stays WRITING, retryable

    def test_fail_does_not_block_pass(self):
        good = self._row("KN-0001", status="WRITING")
        bad = self._row("DL-0001", status="WRITING")
        self._write(good, self._ctx(good))
        path = self._write(bad, self._ctx(bad))
        # wrong-price claim = hard fact-safety FAIL
        html = io.open(path, encoding="utf-8").read().replace(
            "trước khi xuất phát cho chuyến đi an toàn hơn",
            "giá thuê Honda Vision chỉ 300.000đ mỗi ngày rất rẻ", 1)
        io.open(path, "w", encoding="utf-8").write(html)
        updates, articles = self._qa([good, bad])
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["KN-0001"], "PASS")
        self.assertEqual(outcomes["DL-0001"], "FAIL")
        self.assertEqual(updates["DL-0001"]["status"], "FAIL")

    def test_review_repair_then_pass(self):
        """Weak-links draft => REVIEW (repair:1 stamped); after the agent
        rewrites the file, the next QA pass is PASS."""
        row = self._row("KN-0001", status="REVIEW")
        path = self._write(row, self._ctx(row))
        html = io.open(path, encoding="utf-8").read()
        html = re.sub(r'<p>Bạn có thể mở rộng kiến thức.*?</p>', "", html,
                      flags=re.S)
        html = re.sub(r'<p>Nếu bạn cần bổ sung.*?</p>', "", html,
                      flags=re.S)
        io.open(path, "w", encoding="utf-8").write(html)
        updates, articles = self._qa([row])
        self.assertEqual(articles[0]["outcome"], "REVIEW")
        self.assertIn("repair:1", updates["KN-0001"]["notes"])
        # agent repairs: rewrite the file properly
        row = self._row("KN-0001", status="REPAIR")
        row["notes"] = updates["KN-0001"]["notes"]
        self._write(row, self._ctx(row))
        updates2, articles2 = self._qa([row])
        self.assertEqual(articles2[0]["outcome"], "PASS",
                         articles2[0]["quality_failures"])
        self.assertEqual(updates2["KN-0001"]["status"], "PASS")

    def test_review_after_max_repairs_blocked(self):
        """A REVIEW row with repair:2 in its notes (two attempts spent) gets
        ONE final QA pass; still REVIEW => BLOCKED, never published."""
        row = None
        for r in self.matrix:
            if r.get("output_path") == "tests/fixtures/review_weak_links.html":
                row = dict(r)
                break
        self.assertIsNotNone(row)
        row["article_id"] = "ZZ-9001"
        row["status"] = "REVIEW"
        row["notes"] = (row.get("notes") or "") + " repair:2"
        updates, articles = rb.run_qa_for_batch(
            [row], self.matrix, self.ownership, self.facts, self.rubric,
            ROOT)  # repo_root=ROOT: the fixture lives in the real repo
        self.assertEqual(articles[0]["outcome"], "BLOCKED", articles[0])
        self.assertEqual(updates["ZZ-9001"]["status"], "BLOCKED")
        self.assertIn("repair:3", updates["ZZ-9001"]["notes"])
        # BLOCKED is outside the publish scope forever
        self.assertEqual(rb.select_publish_rows([row], ROOT), [])

    def test_publish_scope_is_batch_only(self):
        rows = [self._row(i, status="PASS")
                for i in ("KN-0001", "XM-0001", "DL-0001")]
        for r in rows:
            r["batch_id"] = "BATCH-001"
            self._write(r)
        other = self._row("CD-0001", status="PASS")
        other["batch_id"] = "BATCH-002"
        self._write(other)
        got = rb.select_publish_rows(rows, self.tmp)
        self.assertEqual({r["article_id"] for r in got},
                         {"KN-0001", "XM-0001", "DL-0001"})
        got2 = rb.select_publish_rows([other], self.tmp)
        self.assertEqual([r["batch_id"] for r in got2], ["BATCH-002"])

    def test_partial_batch_publish(self):
        """Some PASS, some FAIL — exactly the PASS rows are publishable."""
        good = self._row("KN-0001", status="WRITING")
        bad = self._row("DL-0001", status="WRITING")
        self._write(good, self._ctx(good))
        path = self._write(bad, self._ctx(bad))
        html = io.open(path, encoding="utf-8").read().replace(
            "trước khi xuất phát cho chuyến đi an toàn hơn",
            "giá thuê Honda Vision chỉ 300.000đ mỗi ngày rất rẻ", 1)
        io.open(path, "w", encoding="utf-8").write(html)
        updates, articles = self._qa([good, bad])
        passed = [a for a in articles if a["outcome"] == "PASS"]
        self.assertEqual(len(passed), 1)
        # simulate the matrix update, then check the publish scope
        good["status"] = updates["KN-0001"]["status"]
        publishable = rb.select_publish_rows([good, bad], self.tmp)
        self.assertEqual([r["article_id"] for r in publishable], ["KN-0001"])

    def test_crash_resume_picks_only_rows_with_files(self):
        """Runner crashed mid-batch: only active rows whose files exist are
        QA-resumed; PASS rows and file-less WRITING rows are untouched."""
        done = self._row("KN-0001", status="PASS")
        half = self._row("DL-0001", status="QA")
        stale = self._row("CD-0001", status="WRITING")
        self._write(done)
        self._write(half, self._ctx(half))
        got = rb.select_qa_rows([done, half, stale], self.tmp, 50)
        self.assertEqual([r["article_id"] for r in got], ["DL-0001"])
        updates, articles = self._qa(got)
        self.assertEqual(articles[0]["outcome"], "PASS")
        self.assertNotIn("KN-0001", updates)
        self.assertNotIn("CD-0001", updates)

    def test_next_resolution_consistency(self):
        """--next resolves ONE batch id; claim/QA/publish all use it."""
        # synthetic pre-production matrix so the test never depends on
        # real production progress
        rows = [dict(r) for r in self.prod]
        for r in rows:
            r["status"] = "PLANNED"
        bid = rb.next_batch_id(rows)
        self.assertEqual(bid, "BATCH-001")
        batch = rb.batch_rows(rows, bid)
        claim = rb.select_claim_rows(batch)
        self.assertEqual(len(claim), 50)
        self.assertTrue(all(r["batch_id"] == bid for r in claim))
        # a resumed active batch wins over a fresh PLANNED one
        rows2 = [dict(r) for r in rows]
        for r in rows2:
            if r["batch_id"] == "BATCH-002":
                r["status"] = "QA"
                break
        self.assertEqual(rb.next_batch_id(rows2), "BATCH-002")

    def test_max_batch_size_capped_at_50(self):
        rows = [dict(r) for r in self.prod[:120]]
        for r in rows:
            r["status"] = "PLANNED"
        self.assertEqual(len(rb.select_claim_rows(rows, 500)), 50)
        self.assertLessEqual(rb.MAX_BATCH_SIZE, 50)

    def test_dry_run_subprocess_changes_nothing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    os.path.join(tmp, "data", "content-matrix.csv"))
        reset_matrix_to_planned(os.path.join(
            tmp, "data", "content-matrix.csv"))
        p = subprocess.run(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, %r)
import run_article_batch as rb, article_lib as lib
lib.ROOT = %r
raise SystemExit(rb.main_func(['--next', '--dry-run']))
""" % (SCRIPTS, tmp)],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=SCRIPTS))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("DRY RUN BATCH-001", p.stdout)
        self.assertIn("50 PLANNED claimable", p.stdout)
        with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            import csv as _csv
            rows = list(_csv.DictReader(f))
        self.assertFalse([r for r in rows if r["status"] == "WRITING"])
        self.assertFalse(os.path.exists(os.path.join(tmp, "data", "batches")))


class NoApiArchitectureTests(PipelineTestCase):
    """The repo contains NO provider layer and NO API-secret dependency."""

    def test_no_providers_directory(self):
        self.assertFalse(os.path.isdir(os.path.join(SCRIPTS, "providers")))

    def test_no_api_key_dependency_in_sources(self):
        banned = ("MISTRAL_API_KEY", "api.mistral.ai", "chat/completions",
                  "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
                src = f.read()
            for b in banned:
                self.assertNotIn(b, src,
                                 "%s references banned %s" % (name, b))

    def test_prepare_agent_subprocess_sandboxed(self):
        """--prepare-agent works with NO secret in the environment and
        writes ONLY inside the sandbox — the real repo matrix is never
        contaminated with WRITING claims."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    os.path.join(tmp, "data", "content-matrix.csv"))
        reset_matrix_to_planned(os.path.join(
            tmp, "data", "content-matrix.csv"))
        real_matrix_path = os.path.join(ROOT, "data",
                                        "content-matrix.csv")
        real_before = io.open(real_matrix_path, encoding="utf-8").read()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MISTRAL", "WRITER", "OPENAI",
                                    "ANTHROPIC"))}
        env["PYTHONPATH"] = SCRIPTS
        p = subprocess.run(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, %r)
import run_article_batch as rb, article_lib as lib
lib.ROOT = %r
raise SystemExit(rb.main_func(['--batch', 'BATCH-001', '--prepare-agent']))
""" % (SCRIPTS, tmp)],
            capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("PREPARED-AGENT BATCH-001", p.stdout)
        self.assertIn("50 articles claimed WRITING", p.stdout)
        manifest = json.load(io.open(
            os.path.join(tmp, "data", "batches", "BATCH-001.json"),
            encoding="utf-8"))
        self.assertEqual(len(manifest["articles"]), 50)
        # SANDBOX: the real repository matrix is byte-identical after the
        # sandbox run (before/after comparison — independent of the real
        # batch legitimately carrying WRITING/PUBLISHED rows)
        real_after = io.open(real_matrix_path, encoding="utf-8").read()
        self.assertEqual(real_after, real_before,
                         "real matrix contaminated by sandbox run")

    def test_writer_not_configured(self):
        with self.assertRaises(aw.WriterNotConfigured):
            aw.write_article({"article_id": "X"}, {})

    def test_writer_cli_exit_5(self):
        p = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "article_writer.py")],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 5)
        self.assertIn("WRITER_NOT_CONFIGURED", p.stdout)


if __name__ == "__main__":
    unittest.main()
