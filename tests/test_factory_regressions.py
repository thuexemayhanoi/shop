#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the API-free article factory refactor.

Covers the defects found in review:
  - commercial classification independent from intent protection
  - matrix link-target sufficiency (>=3 unique, <=1 commercial required)
  - future planned_date never becomes datePublished
  - quality workflow keeps REAL production paths (no /tmp flattening)
  - publish is batch-scoped; resolved --next batch stays consistent
  - active unfinished batch resumed before a fresh PLANNED batch
  - no API secret / provider architecture anywhere
  - source-policy enforcement (approved official domains only)
  - root hub staging after generate_category_pages
"""
import io
import json
import os
import re
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

HUBS = {"kinhnghiem.html", "antoan.html", "xemay.html",
        "dulich.html", "cungduong.html", "hoidap.html"}
COMMERCIAL = {"index.html", "phoco.html", "hoankiem.html", "banggia.html",
             "ngay.html", "tuan.html", "thang.html", "thutuc.html",
             "uudai.html"}

ARTICLE_HEAD = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>%s</title>
<meta name="description" content="mô tả kiểm thử">
<link rel="canonical" href="https://thuexemayhanoi.github.io/shop/%s">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article"}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList"}</script>
</head>
<body>
<main>
<h1>%s</h1>
<p>%s</p>
</main>
</body>
</html>
"""


def write_article(path, body, head_title="Bài kiểm thử"):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(ARTICLE_HEAD % (head_title, path, head_title, body))
    return path


class RegrBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = lib.load_matrix()
        cls.prod = [r for r in cls.matrix if not lib.is_sample_row(r)]
        cls.ownership = lib.load_ownership()


class CommercialClassificationTests(RegrBase):
    """CRITICAL BUG: all protected_pages were treated as commercial."""

    def test_category_hubs_are_not_commercial(self):
        comm = lib.commercial_pages(self.ownership)
        self.assertFalse(comm & HUBS,
                         "category hubs must never be commercial: %s"
                         % (comm & HUBS))

    def test_commercial_flag_independent_of_protection(self):
        comm = lib.commercial_pages(self.ownership)
        self.assertEqual(comm, COMMERCIAL)
        # hubs are still protected (cannibalization), just not commercial
        protected = {os.path.basename(p["path"])
                     for p in self.ownership["protected_pages"]}
        self.assertTrue(HUBS <= protected)

    def test_explicit_flag_wins_over_role(self):
        own = {"protected_pages": [
            {"path": "index.html", "role": "category-hub", "commercial": True},
            {"path": "kinhnghiem.html", "role": "category-hub",
             "commercial": False},
        ]}
        self.assertEqual(lib.commercial_pages(own), {"index.html"})

    def test_legacy_config_without_flag_falls_back_to_role(self):
        own = {"protected_pages": [
            {"path": "index.html", "role": "homepage"},
            {"path": "kinhnghiem.html", "role": "category-hub"},
        ]}
        self.assertEqual(lib.commercial_pages(own), {"index.html"})

    def test_hub_links_do_not_burn_the_commercial_budget(self):
        tmp = tempfile.mkdtemp()
        try:
            row = dict(self.prod[0])
            row["category"] = "Kinh nghiệm"
            p = write_article(
                os.path.join(tmp, "a.html"),
                '<p>xem <a href="/shop/kinhnghiem.html">cẩm nang kinh nghiệm thuê xe</a> '
                'và <a href="/shop/dulich.html">gợi ý du lịch Hà Nội</a> '
                'và <a href="/shop/cungduong.html">cung đường phượt</a> '
                'chi tiết <a href="/shop/thutuc.html">thủ tục thuê xe máy</a>.</p>')
            art = lib.Article(p)
            li = art.analyze_contextual_links(row, self.ownership)
            # contextual links are stored NORMALIZED (repo-relative)
            self.assertEqual(li["commercial_links"],
                             [("thutuc.html",
                               "thủ tục thuê xe máy")])
        finally:
            subprocess.call(["rm", "-rf", tmp])


class MatrixLinkTargetTests(RegrBase):
    """CRITICAL BUG: rows had <3 unique targets (only 2)."""

    def test_all_production_rows_have_at_least_3_unique_targets(self):
        bad = []
        for r in self.prod:
            targets = {t.strip() for t in
                       (r.get("internal_link_targets") or "").split(";")
                       if t.strip()}
            if len(targets) < 3:
                bad.append(r["article_id"])
        self.assertEqual(bad, [],
                         "%d rows with <3 unique targets, e.g. %s"
                         % (len(bad), bad[:5]))

    def test_no_row_requires_more_than_one_commercial_link(self):
        """Invariant: nc (non-commercial) >= 3 or (nc >= 2 and comm present).
        Never must a row NEED >1 commercial link to reach 3 links."""
        for r in self.prod:
            targets = [t.strip() for t in
                       (r.get("internal_link_targets") or "").split(";")
                       if t.strip()]
            nc = [t for t in targets if t not in COMMERCIAL]
            comm = [t for t in targets if t in COMMERCIAL]
            self.assertGreaterEqual(len(nc), 2, r["article_id"])
            self.assertTrue(len(nc) >= 3 or comm,
                            "row needs a commercial link to reach minimum: %s"
                            % r["article_id"])
            self.assertLessEqual(len(comm), 1, r["article_id"])

    def test_targets_exist_and_parent_hub_included(self):
        for r in self.prod:
            targets = [t.strip() for t in
                       (r.get("internal_link_targets") or "").split(";")
                       if t.strip()]
            comm_target = (r.get("commercial_link_target") or "").strip()
            self.assertIn(r["parent_hub"], targets, r["article_id"])
            for t in targets + ([comm_target] if comm_target else []):
                self.assertTrue(
                    os.path.exists(os.path.join(ROOT, t))
                    or t in COMMERCIAL | HUBS,
                    "row %s target %r missing on disk" % (r["article_id"], t))

    def test_no_duplicate_padded_targets(self):
        for r in self.prod:
            targets = [t.strip() for t in
                       (r.get("internal_link_targets") or "").split(";")
                       if t.strip()]
            self.assertEqual(len(targets), len(set(targets)),
                             r["article_id"])

    def test_commercial_target_is_commercial_class(self):
        for r in self.prod:
            c = (r.get("commercial_link_target") or "").strip()
            if c:
                self.assertIn(c, COMMERCIAL, r["article_id"])


class DatePublishedTests(RegrBase):
    """CRITICAL BUG: future planned_date became datePublished."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.future = [r for r in cls.prod
                      if (r.get("planned_date") or "") > rb.today()]

    def test_future_planned_dates_exist_in_matrix(self):
        self.assertTrue(self.future, "precondition: matrix has future dates")

    def test_context_uses_actual_date_never_planned(self):
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
        for r in self.future[:50]:
            ctx = rb.build_writer_context(r, self.matrix, self.ownership,
                                         facts, rubric, site)
            self.assertEqual(ctx["date_published"], rb.today())
            self.assertNotEqual(ctx["date_published"], r["planned_date"])


class WorkflowFileTests(unittest.TestCase):
    """No AI cron, no secrets, read-only helper; real paths in quality gate."""

    def _read(self, rel):
        with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_article_batch_has_no_cron_no_secrets(self):
        y = self._read(".github/workflows/article-batch.yml")
        self.assertNotIn("schedule:", y)
        self.assertNotIn("cron:", y)
        self.assertNotIn("secrets.", y)
        self.assertNotIn("MISTRAL_API_KEY", y)

    def test_article_batch_is_read_only(self):
        y = self._read(".github/workflows/article-batch.yml")
        self.assertIn("contents: read", y)
        self.assertNotIn("contents: write", y)
        # never writes articles or pushes from CI
        self.assertNotIn("--prepare-agent", y)
        self.assertNotIn("--mark-published", y)
        self.assertNotIn("--publish", y)
        self.assertNotIn("git push", y)

    def test_quality_gate_covers_real_paths(self):
        y = self._read(".github/workflows/article-quality.yml")
        self.assertIn("cam-nang/**", y)
        self.assertNotIn("/tmp/candidates", y)
        self.assertNotIn("cp -", y)

    def test_quality_gate_does_not_flatten_article_directories(self):
        y = self._read(".github/workflows/article-quality.yml")
        # candidates come straight from matrix output_path at real repo paths
        self.assertIn("output_path", y)
        self.assertIn("os.path.isfile", y)

    def test_publish_verify_inputs_never_interpolated_into_shell(self):
        """factory-publish-verify.yml must pass dispatch inputs through
        environment variables and quoted CLI arguments — never by building
        an args string with unquoted ${{ }} expansion (command injection)."""
        y = self._read(".github/workflows/factory-publish-verify.yml")
        self.assertNotIn("$args", y)
        self.assertNotIn("shellcheck disable", y)
        self.assertIn("PUBLISH_IDS: ${{ github.event.inputs.publish_ids }}", y)
        self.assertIn("PUBLISH_DATE: ${{ github.event.inputs.date }}", y)
        self.assertIn('--publish "$publish_ids"', y)
        self.assertIn('--date "$PUBLISH_DATE"', y)
        # non-empty publish_ids enforced inside the step (defence in depth
        # beyond the `if:` gate)
        self.assertIn("publish_ids must be a non-empty", y)


class CumulativeBatchReportTests(unittest.TestCase):
    """The batch report is CUMULATIVE: every reserved member of the batch
    appears, and all counts are derived from the matrix rows of the batch
    (never just the rows of the latest run)."""

    @staticmethod
    def _row(aid, status, score="", notes="", batch="BATCH-X",
             path="cam-nang/x/x.html", sources="no"):
        return {"article_id": aid, "status": status, "score": score,
                "notes": notes, "batch_id": batch, "output_path": path,
                "requires_sources": sources}

    def test_counts_and_members_derive_from_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                self._row("AA-0001", "PUBLISHED", "100"),
                self._row("AA-0002", "PUBLISHED", "96"),
                self._row("AA-0003", "WRITING"),
                self._row("AA-0004", "PLANNED"),
            ]
            rep = rb.build_cumulative_report(
                "BATCH-X", rows, [
                    {"article_id": "AA-0001", "outcome": "PASS",
                     "score": 100, "repair_attempts": 0,
                     "quality_failures": [], "cannibalization_failures": [],
                     "cannibalization_warnings": []},
                ], "2026-09-26T00:00:00", tmp)
            self.assertEqual(len(rep["articles"]), 4)
            self.assertEqual(rep["published"], 2)
            self.assertEqual(rep["writing"], 1)
            self.assertEqual(rep["pass"], 0)
            self.assertEqual(rep["processed"], 3)  # minus 1 PLANNED
            self.assertEqual(rep["written"], 2)     # minus PLANNED/WRITING
            self.assertEqual(rep["average_score"], 98)  # int-normalized (matches Node)
            self.assertEqual(rep["min_score"], 96)
            self.assertEqual(rep["max_score"], 100)
            by_id = {a["article_id"]: a for a in rep["articles"]}
            self.assertEqual(by_id["AA-0003"]["outcome"], "WRITING")
            self.assertEqual(by_id["AA-0004"]["outcome"], "PLANNED")

    def test_run_details_merge_and_prior_report_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "reports", "batches"),
                        exist_ok=True)
            prior = {"batch_id": "BATCH-X", "started_at": "2026-09-01T00:00:00",
                     "writer": "external-agent",
                     "published_commit_sha": "deadbeef",
                     "articles": [{"article_id": "AA-0002",
                                   "cannibalization_warnings": ["w"]}]}
            with io.open(os.path.join(tmp, "reports", "batches",
                                      "BATCH-X.json"), "w",
                        encoding="utf-8") as f:
                json.dump(prior, f)
            # AA-0002 already terminal in the matrix: cumulative report must
            # keep the prior audit SHA and carry the warning over
            rows = [self._row("AA-0002", "PUBLISHED", "96")]
            rep = rb.build_cumulative_report(
                "BATCH-X", rows, [], "2026-09-26T00:00:00", tmp)
            self.assertEqual(rep["published_commit_sha"], "deadbeef")
            self.assertEqual(rep["started_at"], "2026-09-01T00:00:00")
            self.assertEqual(rep["articles"][0]["cannibalization_warnings"],
                             ["w"])
            # repair attempts also derive from ledger notes
            rows2 = [self._row("AA-0003", "REPAIR", notes="repair:2")]
            rep2 = rb.build_cumulative_report(
                "BATCH-X", rows2, [], "2026-09-26T00:00:00", tmp)
            self.assertEqual(rep2["articles"][0]["repair_attempts"], 2)



class SourcePolicyTests(RegrBase):
    def _policy(self):
        return lib.load_source_policy()

    def _article_with_sources(self, body):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.call(["rm", "-rf", tmp]))
        p = write_article(os.path.join(tmp, "a.html"), body)
        return lib.Article(p)

    def test_policy_has_approved_official_domains(self):
        pol = self._policy()
        self.assertIn("chinhphu.vn", pol["approved_source_domains"])
        self.assertGreaterEqual(int(pol["min_approved_urls"]), 1)

    def _requires_row(self):
        for r in self.prod:
            if str(r.get("requires_sources", "")).lower() in ("true", "yes", "1"):
                return dict(r)
        self.fail("no requires_sources production row")

    def test_no_source_section_fails(self):
        row = self._requires_row()
        art = self._article_with_sources("<p>nội dung không có nguồn.</p>")
        fails, approved = lib.source_gate(art, row)
        self.assertTrue(fails)
        self.assertEqual(approved, [])

    def test_heading_without_url_fails(self):
        row = self._requires_row()
        art = self._article_with_sources(
            "<h2>Nguồn tham khảo</h2><p>theo Nghị định 168/2024/NĐ-CP.</p>")
        fails, approved = lib.source_gate(art, row)
        self.assertTrue(any("approved official source" in f for f in fails))

    def test_non_approved_domain_fails(self):
        row = self._requires_row()
        art = self._article_with_sources(
            '<h2>Nguồn tham khảo</h2>'
            '<p><a href="https://blog-xegaiviet.example.com/nghi-dinh-168">'
            'Nghị định 168</a></p>')
        fails, approved = lib.source_gate(art, row)
        self.assertTrue(fails)
        self.assertEqual(approved, [])

    def test_approved_domain_passes(self):
        row = self._requires_row()
        art = self._article_with_sources(
            '<h2>Nguồn tham khảo</h2>'
            '<p><a href="https://vanban.chinhphu.vn/page/nghi-dinh-168-2024">'
            'Nghị định 168/2024/NĐ-CP</a></p>')
        fails, approved = lib.source_gate(art, row)
        self.assertEqual(fails, [])
        self.assertEqual(len(approved), 1)

    def test_approved_subdomain_passes(self):
        row = self._requires_row()
        art = self._article_with_sources(
            '<h2>Nguồn tham khảo</h2>'
            '<p><a href="https://csgt.mt.gov.vn/nghi-dinh-168">thông tin CSGT'
            '</a></p>')
        fails, approved = lib.source_gate(art, row)
        self.assertEqual(fails, [])
        self.assertEqual(len(approved), 1)

    def test_malformed_url_fails(self):
        row = self._requires_row()
        art = self._article_with_sources(
            '<h2>Nguồn tham khảo</h2>'
            '<p><a href="https://">nguồn lỗi</a></p>')
        fails, _ = lib.source_gate(art, row)
        self.assertTrue(any("approved official source" in f or
                            "malformed" in f for f in fails))

    def test_requires_sources_false_not_forced(self):
        row = dict(self.prod[0])
        row["requires_sources"] = "false"
        art = self._article_with_sources("<p>không cần nguồn.</p>")
        fails, _ = lib.source_gate(art, row)
        self.assertEqual(fails, [])

    def test_sample_rows_exempt_from_source_gate(self):
        art = self._article_with_sources("<p>không có nguồn.</p>")
        for r in self.matrix:
            if lib.is_sample_row(r):
                fails, _ = lib.source_gate(art, r)
                self.assertEqual(fails, [])


class BatchResolutionTests(RegrBase):
    def test_next_resumes_active_batch_first(self):
        rows = [dict(r) for r in self.prod]
        # synthetic pre-production state so the test never depends on real
        # batch progress; BATCH-002 has a WRITING row, BATCH-001 all PLANNED
        for r in rows:
            r["status"] = "PLANNED"
        for r in rows:
            if r["batch_id"] == "BATCH-002":
                r["status"] = "WRITING"
                break
        self.assertEqual(rb.active_batch_id(rows), "BATCH-002")
        self.assertEqual(rb.next_batch_id(rows), "BATCH-002")

    def test_fail_blocked_do_not_prevent_next_batch(self):
        rows = [dict(r) for r in self.prod]
        for r in rows:
            if r["batch_id"] == "BATCH-001":
                r["status"] = "FAIL" if r["article_id"].endswith("1") \
                    else "BLOCKED"
        self.assertIsNone(rb.active_batch_id(rows))
        # all BATCH-001 rows are final -> next is the first PLANNED batch
        self.assertEqual(rb.next_batch_id(rows), "BATCH-002")

    def test_publish_scope_is_batch_only(self):
        tmp = tempfile.mkdtemp()
        try:
            b1 = [dict(r) for r in self.prod if r["batch_id"] == "BATCH-001"][:2]
            b2 = [dict(r) for r in self.prod if r["batch_id"] == "BATCH-002"][:2]
            for r in b1 + b2:
                r["status"] = "PASS"
                r["output_path"] = "fixture/%s.html" % r["article_id"]
                p = os.path.join(tmp, r["output_path"])
                os.makedirs(os.path.dirname(p), exist_ok=True)
                io.open(p, "w", encoding="utf-8").write("<html></html>")
            got = rb.select_publish_rows(b1, tmp)
            self.assertEqual([r["batch_id"] for r in got], ["BATCH-001"] * 2)
            got2 = rb.select_publish_rows(b2, tmp)
            self.assertEqual([r["batch_id"] for r in got2], ["BATCH-002"] * 2)
        finally:
            subprocess.call(["rm", "-rf", tmp])

    def test_next_resolved_batch_stays_consistent(self):
        """Once resolved, the SAME batch id is used for prepare, qa, publish
        and mark-published — never a ${bid:-BATCH-001} style default."""
        rows = [dict(r) for r in self.prod]
        for r in rows:
            if r["batch_id"] == "BATCH-001":
                r["status"] = "PUBLISHED"
        self.assertEqual(rb.next_batch_id(rows), "BATCH-002")
        # simulate a full cycle using the resolved id only
        bid = rb.next_batch_id(rows)
        self.assertEqual(bid, "BATCH-002")
        claim = rb.select_claim_rows(rb.batch_rows(rows, bid))
        self.assertEqual(len(claim), 50)
        self.assertTrue(all(r["batch_id"] == "BATCH-002" for r in claim))


class RootHubStagingTests(RegrBase):
    def test_published_by_category_only_published(self):
        import generate_category_pages as gcp
        rows = []
        for r in self.prod[:120]:
            r = dict(r)
            r["status"] = "PUBLISHED" if len(rows) % 2 == 0 else "PASS"
            rows.append(r)
        by_cat = gcp.published_by_category(rows)
        for cat, items in by_cat.items():
            self.assertTrue(all(r["status"] == "PUBLISHED" for r in items))

    def test_hub_block_injection_idempotent(self):
        import generate_category_pages as gcp
        tmp = tempfile.mkdtemp()
        try:
            hub = os.path.join(tmp, "kinhnghiem.html")
            with io.open(hub, "w", encoding="utf-8") as f:
                f.write("<html><body><main>OLD</main></body></html>")
            block = "%s\n<ul><li>card</li></ul>\n%s" % (gcp.START, gcp.END)
            first, injected = gcp.inject_hub_block(hub, block)
            self.assertTrue(injected)
            self.assertEqual(first.count(gcp.START), 1)
            self.assertIn("OLD", first)  # manual content untouched
            # persist, then re-inject: replaces the delimited block,
            # never duplicates it
            with io.open(hub, "w", encoding="utf-8") as f:
                f.write(first)
            second, injected2 = gcp.inject_hub_block(hub, block)
            self.assertFalse(injected2)
            self.assertEqual(second.count(gcp.START), 1)
            self.assertEqual(second, first)
        finally:
            subprocess.call(["rm", "-rf", tmp])

    def test_six_root_hubs_exist_in_repo(self):
        for h in HUBS:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, h)), h)


class NoApiArchitectureTests(unittest.TestCase):
    """The external Mistral agent is the writer; no API layer in repo."""

    def test_no_providers_directory(self):
        self.assertFalse(os.path.isdir(os.path.join(ROOT, "scripts",
                                                    "providers")))

    def test_no_api_key_dependency_in_sources(self):
        banned = ("MISTRAL_API_KEY", "api.mistral.ai", "chat/completions",
                  "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        for name in os.listdir(SCRIPTS):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
                src = f.read()
            for b in banned:
                self.assertNotIn(b, src,
                                 "%s references banned %s" % (name, b))

    def test_matrix_has_published_date_ledger_column(self):
        with io.open(os.path.join(ROOT, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            header = f.readline()
        self.assertIn("published_date", header)


if __name__ == "__main__":
    unittest.main()
