#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Four-layer reliability suite (milestone 3 of the hardening).

Hermetic, deterministic tests for the RELIABILITY layer (L4) of the
content factory:

  * full sandbox lifecycle  prepare -> write -> scoped QA -> requeue ->
                           chunk-complete -> publish scope -> mark-published
  * verifier invariants    scripts/verify_factory_state.py flags every
                           injected failure (matrix, leaks, txn, sitemap,
                           hubs, schema-1 report, stale counts) and stays
                           green on an unmodified production-shaped tree
  * transaction cleanliness no pending txn marker after deterministic
                           python operations; a marker is detected and
                           reported (fail-closed, never silently ignored)
  * report schema 2        schema_version=2, Hanoi (+07:00) timestamps,
                           source_head_sha semantics (INPUT tree, never a
                           self-referential "this commit contains me")
  * health evaluation      scripts/factory_health.py verdicts are earned
                           by evidence (RECOVERY_REQUIRED / LOCKED /
                           READY_FOR_* / WAITING_FOR_WRITER / BLOCKED /
                           COMPLETE / NO_PROGRESS / HEALTHY)
  * writer lock            atomic O_EXCL acquisition, 20-process
                           contention -> EXACTLY ONE winner, stale-lock
                           reclaim serialized by the recovery guard,
                           CAS-like ownership (one-writer invariant)
  * failure injection      corrupt reports/lock files never crash the
                           deterministic tooling; they are reported
  * kill switch            production mutations refused, safety
                           operations still available

No network, no AI, no secrets. Every sandbox is a temp directory; the
real repository tree is never mutated (fixture-based QA reads the real
tests/fixtures/ files, whose evidence output is gitignored).
"""
import csv
import datetime
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

import article_lib as lib                      # noqa: E402
import run_article_batch as rb                 # noqa: E402
import verify_factory_state as vfs             # noqa: E402
import factory_health as fh                    # noqa: E402
import requeue_rows as rq                      # noqa: E402

HANOI_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+07:00$")
HUBS = sorted(lib.CATEGORIES.values())
FIXTURES = os.path.join(HERE, "fixtures")


def load_matrix_rows(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_matrix_rows(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def reset_matrix_to_planned(path, writing_batch=None):
    rows = load_matrix_rows(path)
    for r in rows:
        if lib.is_sample_row(r):
            continue
        if writing_batch and r["batch_id"] == writing_batch:
            r["status"] = "WRITING"
        else:
            r["status"] = "PLANNED"
        r["published_date"] = ""
    write_matrix_rows(path, rows)


def set_status(path, article_id, status, notes=None):
    rows = load_matrix_rows(path)
    for r in rows:
        if r.get("article_id") == article_id:
            r["status"] = status
            if notes is not None:
                r["notes"] = notes
    write_matrix_rows(path, rows)


class ReliabilityTestCase(unittest.TestCase):
    """Sandbox with the REAL config + matrix (statuses reset per test)."""

    def _sandbox(self, writing_batch=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        matrix = os.path.join(tmp, "data", "content-matrix.csv")
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    matrix)
        reset_matrix_to_planned(matrix, writing_batch)
        return tmp

    def _run(self, tmp, argv):
        """run_article_batch CLI with lib.ROOT redirected to the sandbox."""
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            return rb.main_func(argv)
        finally:
            lib.ROOT = old

    def _matrix(self, tmp):
        return load_matrix_rows(
            os.path.join(tmp, "data", "content-matrix.csv"))

    def _write_draft(self, tmp, row, content=None):
        """Writer-side draft at _drafts/<output_path> (deploy gate)."""
        rel = rb.draft_rel(row["output_path"])
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(content or
                    ("<html lang='vi'><head><title>%s</title></head>"
                     "<body><h1>%s</h1></body></html>"
                     % (row["article_id"], row["article_id"])))
        return p

    def _write_final(self, tmp, row, content=None):
        p = os.path.join(tmp, row["output_path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(content or "<html><body>x</body></html>")
        return p

    def _batch_ids(self, tmp, batch, n=5):
        return [r["article_id"] for r in
                rb.batch_rows(self._matrix(tmp), batch)[:n]]

    def _progress(self, tmp):
        with io.open(os.path.join(tmp, "reports", "batches",
                                  "factory-progress.json"),
                     encoding="utf-8") as f:
            return json.load(f)


# ---------------------------------------------------------------------------
# Hanoi timezone + source_head_sha semantics (schema 2)
# ---------------------------------------------------------------------------

class HanoiTimezoneTests(unittest.TestCase):
    def test_now_vn_iso_is_timezone_aware_hanoi(self):
        self.assertRegex(rb.now_vn_iso(), r"^\d{4}-\d{2}-\d{2}T"
                                        r"\d{2}:\d{2}:\d{2}\+07:00$")

    def test_hanoi_clock_is_utc_plus_seven(self):
        hanoi = datetime.timezone(datetime.timedelta(hours=7),
                                   "+07:00")
        utc = datetime.datetime.now(datetime.timezone.utc)
        vn = rb.now_vn()
        self.assertEqual(vn.utcoffset(),
                         datetime.timedelta(hours=7))
        delta = abs((vn - utc.astimezone(hanoi)).total_seconds())
        self.assertLess(delta, 5)   # same instant, Hanoi wall time

    def test_today_is_the_hanoi_date(self):
        expected = (datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=7))).date())
        self.assertEqual(rb.today(), expected.isoformat())

    def test_report_timestamps_use_hanoi_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "reports", "batches"))
            rb.write_factory_progress(
                tmp, [{"article_id": "AA-0001", "status": "PLANNED",
                       "batch_id": "BATCH-A", "output_path": "a.html",
                       "category": "Xe máy", "notes": ""}])
            prog = json.load(io.open(
                os.path.join(tmp, "reports", "batches",
                             "factory-progress.json"), encoding="utf-8"))
            self.assertRegex(prog["generated"], HANOI_RE)


class SourceHeadShaTests(unittest.TestCase):
    """Schema-2 SHA semantics: the report records the INPUT tree sha
    (never an unstable self-referential 'this commit contains me')."""

    def test_github_sha_env_wins(self):
        old = os.environ.get("GITHUB_SHA")
        os.environ["GITHUB_SHA"] = "a" * 40
        try:
            self.assertEqual(rb.source_head_sha(), "a" * 40)
        finally:
            if old is None:
                del os.environ["GITHUB_SHA"]
            else:
                os.environ["GITHUB_SHA"] = old

    def test_without_env_returns_none_or_full_sha(self):
        old = os.environ.pop("GITHUB_SHA", None)
        try:
            sha = rb.source_head_sha()
        finally:
            if old is not None:
                os.environ["GITHUB_SHA"] = old
        # no .git in this sandbox (or a real checkout): either None or a
        # full 40-hex rev-parse result — never a partial/fabricated value
        self.assertTrue(sha is None or re.fullmatch(r"[0-9a-f]{40}", sha))

    def test_progress_records_source_head_sha_never_matrix_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "reports", "batches"))
            old = os.environ.pop("GITHUB_SHA", None)
            try:
                _, prog = rb.write_factory_progress(
                    tmp, [{"article_id": "AA-0001", "status": "PLANNED",
                           "batch_id": "BATCH-A", "output_path": "a.html",
                           "category": "Xe máy", "notes": ""}])
            finally:
                if old is not None:
                    os.environ["GITHUB_SHA"] = old
            self.assertIn("source_head_sha", prog)
            self.assertNotIn("matrix_commit_sha", prog)
            self.assertEqual(prog["schema_version"], 2)


# ---------------------------------------------------------------------------
# Full sandbox lifecycle (prepare -> write -> QA -> requeue -> publish)
# ---------------------------------------------------------------------------

class SandboxLifecycleTests(ReliabilityTestCase):

    def test_full_chunk_lifecycle(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        ids = self._batch_ids(tmp, "BATCH-001", 5)
        rows = {r["article_id"]: r for r in
                rb.batch_rows(self._matrix(tmp), "BATCH-001")}

        # 1. prepare-next (chunked writer mode): manifest + checkpoint
        code = self._run(tmp, ["--batch", "BATCH-001",
                               "--next-chunk", "5"])
        self.assertEqual(code, rb.EXIT_OK)
        manifest = json.load(io.open(
            os.path.join(tmp, "data", "batches", "BATCH-001-chunk.json"),
            encoding="utf-8"))
        self.assertEqual([a["article_id"] for a in manifest["articles"]],
                         ids)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches",
                         "writer-checkpoint.json"), encoding="utf-8"))
        self.assertEqual(cp["current_chunk_ids"], ids)

        # 2. writer writes drafts for the first three ids
        for i in ids[:3]:
            self._write_draft(tmp, rows[i])

        # 3. scoped QA of the written ids: stub content fails QA -> the
        #    FAIL outcome is RECORDED per article (exit 3, isolated rows)
        code = self._run(tmp, ["--batch", "BATCH-001", "--ids",
                               ",".join(ids[:3]), "--qa"])
        self.assertEqual(code, rb.EXIT_FAILS)
        by_id = {r["article_id"]: r for r in self._matrix(tmp)}
        for i in ids[:3]:
            self.assertEqual(by_id[i]["status"], "FAIL")
        # untouched rows stay WRITING (per-article isolation)
        for i in ids[3:]:
            self.assertEqual(by_id[i]["status"], "WRITING")

        # 4. checkpoint reflects QA truth: QA'd ids left pending_qa
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches",
                         "writer-checkpoint.json"), encoding="utf-8"))
        self.assertEqual(cp["pending_qa_ids"], ids[3:])
        self.assertEqual(cp["last_completed_step"], "qa-completed")

        # 5. cumulative batch report regenerated from matrix truth
        report = json.load(io.open(
            os.path.join(tmp, "reports", "batches", "BATCH-001.json"),
            encoding="utf-8"))
        self.assertEqual(report["fail"], 3)
        self.assertEqual(report["writing"], 47)
        self.assertRegex(report["finished_at"], HANOI_RE)
        # progress report regenerated in the SAME run (state sync)
        prog = self._progress(tmp)
        self.assertEqual(prog["fail"], 3)
        self.assertEqual(prog["writing"], 47)
        self.assertEqual(prog["active_batch"], "BATCH-001")

        # 6. chunk-complete: the FAIL rows are terminal for the chunk
        code = self._run(tmp, ["--batch", "BATCH-001", "--chunk-complete",
                               "--ids", ",".join(ids[:3])])
        self.assertEqual(code, rb.EXIT_OK)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches",
                         "writer-checkpoint.json"), encoding="utf-8"))
        self.assertEqual(sorted(cp["completed_ids"]), sorted(ids[:3]))
        self.assertEqual(cp["current_chunk_ids"], ids[3:])
        tp = json.load(io.open(
            os.path.join(tmp, "reports", "batches",
                         "factory-throughput.json"), encoding="utf-8"))
        self.assertEqual(tp["batches"]["BATCH-001"]["articles_written"], 3)
        self.assertEqual(tp["batches"]["BATCH-001"]["chunks_completed"], 1)

        # 7. requeue the FAIL rows -> REPAIR (idempotent, budget-aware)
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            code = rq.main(["--ids", ",".join(ids[:3])])
        finally:
            lib.ROOT = old
        self.assertEqual(code, 0)
        by_id = {r["article_id"]: r for r in self._matrix(tmp)}
        for i in ids[:3]:
            self.assertEqual(by_id[i]["status"], "REPAIR")
            self.assertIn("repair:1", by_id[i]["notes"])
        # requeue is idempotent: REPAIR rows are skipped, never touched
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            code = rq.main(["--ids", ",".join(ids[:3])])
        finally:
            lib.ROOT = old
        self.assertEqual(code, 0)
        by_id = {r["article_id"]: r for r in self._matrix(tmp)}
        for i in ids[:3]:
            self.assertEqual(by_id[i]["status"], "REPAIR")

        # 8. publish scope: only PASS rows of THIS batch, whole-scope
        #    refusal on a non-PASS id
        set_status(os.path.join(tmp, "data", "content-matrix.csv"),
                   ids[3], "PASS")
        self._write_draft(tmp, rows[ids[3]])
        code = self._run(tmp, ["--batch", "BATCH-001", "--publish",
                               "--ids", ids[3]])
        self.assertEqual(code, rb.EXIT_OK)
        code = self._run(tmp, ["--batch", "BATCH-001", "--publish",
                               "--ids", "%s,%s" % (ids[3], ids[4])])
        self.assertEqual(code, rb.EXIT_USAGE)   # ids[4] is WRITING

        # 9. mark-published flips the PASS row (file verified present)
        code = self._run(tmp, ["--batch", "BATCH-001", "--mark-published"])
        self.assertEqual(code, rb.EXIT_OK)
        by_id = {r["article_id"]: r for r in self._matrix(tmp)}
        self.assertEqual(by_id[ids[3]]["status"], "PUBLISHED")
        self.assertEqual(by_id[ids[3]]["published_date"], rb.today())

        # 10. transaction cleanliness: deterministic python operations
        #     never leave a pending transaction marker behind
        self.assertFalse(os.path.exists(
            os.path.join(tmp, "data", "batches", "txn", "txn.json")))

    def test_prepare_next_claims_planned_rows(self):
        tmp = self._sandbox()
        code = self._run(tmp, ["--next", "--prepare-agent"])
        self.assertEqual(code, rb.EXIT_OK)
        m = self._matrix(tmp)
        writing = [r for r in m if r["status"] == "WRITING"]
        self.assertEqual(len(writing), rb.MAX_BATCH_SIZE)
        manifest = json.load(io.open(
            os.path.join(tmp, "data", "batches", "BATCH-001.json"),
            encoding="utf-8"))
        self.assertEqual(len(manifest["articles"]), rb.MAX_BATCH_SIZE)
        # datePublished handed to the writer is the ACTUAL date
        for a in manifest["articles"]:
            self.assertEqual(a["date_published"], rb.today())

    def test_kill_switch_pauses_production_but_not_safety(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        cfg = os.path.join(tmp, "config", "content-factory.json")
        with io.open(cfg, "w", encoding="utf-8") as f:
            json.dump({"enabled": False}, f)
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--next-chunk", "5"]),
            rb.EXIT_USAGE)
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--ids", "KN-0001",
                           "--qa"]),
            rb.EXIT_USAGE)
        # safety operations stay available while paused
        self.assertEqual(
            self._run(tmp, ["--writer-lock-status"]), rb.EXIT_OK)
        self.assertEqual(
            self._run(tmp, ["--checkpoint", "--batch", "BATCH-001"]),
            rb.EXIT_OK)


class QaOutcomeTests(ReliabilityTestCase):
    """QA verdicts, per-article isolation and the repair budget."""

    @staticmethod
    def _fixture_row(fixture, article_id):
        matrix = lib.load_matrix()
        row = None
        for r in matrix:
            if r["output_path"] == "tests/fixtures/" + fixture:
                row = dict(r)
                break
        if row is None:
            row = dict(next(r for r in matrix if lib.is_sample_row(r)))
        row["article_id"] = article_id
        row["status"] = "WRITING"
        row["output_path"] = "tests/fixtures/" + fixture
        row["notes"] = ""
        return row

    def _qa(self, rows):
        return rb.run_qa_for_batch(
            rows, lib.load_matrix(), lib.load_ownership(),
            lib.load_business_facts(), lib.load_rubric(), ROOT)

    def test_pass_fail_review_are_recorded_per_article(self):
        rows = [self._fixture_row("good.html", "ZZ-9001"),
                self._fixture_row("fail_vision_price.html", "ZZ-9002"),
                self._fixture_row("review_weak_links.html", "ZZ-9003")]
        updates, articles = self._qa(rows)
        outcomes = {a["article_id"]: a["outcome"] for a in articles}
        self.assertEqual(outcomes["ZZ-9001"], "PASS")
        self.assertEqual(outcomes["ZZ-9002"], "FAIL")
        self.assertEqual(outcomes["ZZ-9003"], "REVIEW")
        self.assertEqual(updates["ZZ-9001"]["status"], "PASS")
        self.assertEqual(updates["ZZ-9002"]["status"], "FAIL")
        self.assertEqual(updates["ZZ-9003"]["status"], "REPAIR")

    def test_review_row_exhausting_budget_becomes_blocked(self):
        row = self._fixture_row("review_weak_links.html", "ZZ-9011")
        row["notes"] = "repair:2"   # two attempts used
        updates, articles = self._qa([row])
        self.assertEqual(articles[0]["outcome"], "BLOCKED")
        self.assertEqual(updates["ZZ-9011"]["status"], "BLOCKED")
        self.assertIn("repair:3", updates["ZZ-9011"]["notes"])

    def test_scoped_qa_exit_codes(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        ids = self._batch_ids(tmp, "BATCH-001", 2)
        rows = {r["article_id"]: r for r in
                rb.batch_rows(self._matrix(tmp), "BATCH-001")}
        # unknown id -> usage error, nothing mutated
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--ids", "ZZ-9999",
                           "--qa"]),
            rb.EXIT_USAGE)
        # unwritten id -> usage error
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--ids", ids[0],
                           "--qa"]),
            rb.EXIT_USAGE)
        # written stub -> FAIL recorded, exit 3 (legitimate result)
        self._write_draft(tmp, rows[ids[0]])
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--ids", ids[0],
                           "--qa"]),
            rb.EXIT_FAILS)
        # PASS rows are never re-QA'd
        set_status(os.path.join(tmp, "data", "content-matrix.csv"),
                   ids[0], "PASS")
        self.assertEqual(
            self._run(tmp, ["--batch", "BATCH-001", "--ids", ids[0],
                           "--qa"]),
            rb.EXIT_USAGE)


# ---------------------------------------------------------------------------
# Verifier invariants (scripts/verify_factory_state.py)
# ---------------------------------------------------------------------------

class VerifierRealStateTests(unittest.TestCase):
    """Green baseline on a production-shaped tree, then failure
    injection: every injected defect must be DETECTED (fail-closed)."""

    @classmethod
    def setUpClass(cls):
        cls.golden = tempfile.mkdtemp()
        g = cls.golden
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(g, "config"))
        os.makedirs(os.path.join(g, "data"))
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    os.path.join(g, "data", "content-matrix.csv"))
        shutil.copy(os.path.join(ROOT, "sitemap.xml"),
                    os.path.join(g, "sitemap.xml"))
        shutil.copytree(os.path.join(ROOT, "cam-nang"),
                        os.path.join(g, "cam-nang"))
        os.makedirs(os.path.join(g, "reports", "batches"))
        for name in os.listdir(os.path.join(ROOT, "reports", "batches")):
            if name.endswith(".json"):
                shutil.copy(
                    os.path.join(ROOT, "reports", "batches", name),
                    os.path.join(g, "reports", "batches", name))
        for hub in HUBS:
            shutil.copy(os.path.join(ROOT, hub), os.path.join(g, hub))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.golden, True)

    def _copy(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.rmtree(tmp)
        shutil.copytree(self.golden, tmp, symlinks=True)
        return tmp

    def _matrix_path(self, tmp):
        return os.path.join(tmp, "data", "content-matrix.csv")

    def test_green_baseline_and_read_only(self):
        tmp = self._copy()
        before = sorted(os.walk(tmp).__next__()[2])
        problems, ok = vfs.verify(tmp)
        self.assertEqual(problems, [])
        self.assertTrue(ok)
        # read-only: the verifier never mutates the tree
        after = sorted(os.walk(tmp).__next__()[2])
        self.assertEqual(before, after)

    def test_duplicate_matrix_id_detected(self):
        tmp = self._copy()
        rows = load_matrix_rows(self._matrix_path(tmp))
        prod = [r for r in rows if not lib.is_sample_row(r)]
        prod[1]["article_id"] = prod[0]["article_id"]
        write_matrix_rows(self._matrix_path(tmp), rows)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate" in p for p in problems))

    def test_unknown_status_detected(self):
        tmp = self._copy()
        rows = load_matrix_rows(self._matrix_path(tmp))
        prod = [r for r in rows if not lib.is_sample_row(r)]
        prod[0]["status"] = "DONE?"
        write_matrix_rows(self._matrix_path(tmp), rows)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("unknown status" in p for p in problems))

    def test_unpublished_public_leak_detected(self):
        tmp = self._copy()
        rows = load_matrix_rows(self._matrix_path(tmp))
        pub = next(r for r in rows
                   if r["status"] == "PUBLISHED"
                   and not lib.is_sample_row(r))
        pub["status"] = "WRITING"   # file still at the public path
        write_matrix_rows(self._matrix_path(tmp), rows)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("unpublished public leak" in p for p in problems))

    def test_published_missing_file_detected(self):
        tmp = self._copy()
        rows = load_matrix_rows(self._matrix_path(tmp))
        pub = next(r for r in rows
                   if r["status"] == "PUBLISHED"
                   and not lib.is_sample_row(r))
        os.remove(os.path.join(tmp, pub["output_path"]))
        del rows
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("missing its public file" in p
                            for p in problems))

    def test_pending_transaction_detected(self):
        tmp = self._copy()
        tdir = os.path.join(tmp, "data", "batches", "txn")
        os.makedirs(tdir)
        with io.open(os.path.join(tdir, "txn.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"state": "PENDING"}, f)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("pending transaction marker" in p
                            for p in problems))
        # health evaluator agrees: recovery comes before everything
        verdict = fh.evaluate(tmp)
        self.assertEqual(verdict["status"], "RECOVERY_REQUIRED")

    def test_schema_one_report_rejected(self):
        tmp = self._copy()
        p = os.path.join(tmp, "reports", "batches",
                         "factory-progress.json")
        prog = json.load(io.open(p, encoding="utf-8"))
        prog["matrix_commit_sha"] = "0" * 40   # legacy schema-1 field
        prog.pop("source_head_sha", None)
        prog["schema_version"] = 1
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(prog, f)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("matrix_commit_sha" in p2 for p2 in problems))
        self.assertTrue(any("source_head_sha" in p2 for p2 in problems))
        self.assertTrue(any("schema_version != 2" in p2 for p2 in problems))

    def test_stale_report_counts_detected(self):
        tmp = self._copy()
        p = os.path.join(tmp, "reports", "batches",
                         "factory-progress.json")
        prog = json.load(io.open(p, encoding="utf-8"))
        prog["pass"] = 999999   # hand-patched lie
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(prog, f)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("stale or hand-patched" in p2 for p2 in problems))

    def test_non_hanoi_timestamp_detected(self):
        tmp = self._copy()
        p = os.path.join(tmp, "reports", "batches",
                         "factory-progress.json")
        prog = json.load(io.open(p, encoding="utf-8"))
        prog["generated"] = "2026-09-30T10:00:00+00:00"
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(prog, f)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("Hanoi timestamp" in p2 for p2 in problems))

    def test_corrupt_progress_report_detected(self):
        tmp = self._copy()
        p = os.path.join(tmp, "reports", "batches",
                         "factory-progress.json")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("not valid JSON" in p2 for p2 in problems))

    def test_sitemap_leak_detected(self):
        tmp = self._copy()
        rows = load_matrix_rows(self._matrix_path(tmp))
        pub = next(r for r in rows
                   if r["status"] == "PUBLISHED"
                   and not lib.is_sample_row(r))
        pub["status"] = "FAIL"
        write_matrix_rows(self._matrix_path(tmp), rows)
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("leaked" in p and "sitemap" in p
                            for p in problems))

    def test_missing_hub_detected(self):
        tmp = self._copy()
        os.remove(os.path.join(tmp, HUBS[0]))
        problems, ok = vfs.verify(tmp)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in p and HUBS[0] in p
                            for p in problems))

    def test_cli_exit_contract(self):
        tmp = self._copy()
        self.assertEqual(vfs.main_func(["--repo-root", tmp]), 0)
        rows = load_matrix_rows(self._matrix_path(tmp))
        prod = next(r for r in rows
                    if not lib.is_sample_row(r)
                    and r["status"] == "PUBLISHED")
        os.remove(os.path.join(tmp, prod["output_path"]))
        self.assertEqual(vfs.main_func(["--repo-root", tmp]), 1)
        # usage error: argparse exits with status 2 (fail-closed)
        with self.assertRaises(SystemExit) as ctx:
            vfs.main_func(["--repo-root", tmp, "--op", "nonsense"])
        self.assertEqual(ctx.exception.code, 2)


class VerifierPostconditionTests(unittest.TestCase):
    """Op-specific postconditions on a minimal sandbox (fail-closed: a
    green tool exit is NOT production success)."""

    def _mini(self, rows):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        os.makedirs(os.path.join(tmp, "data"))
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), rows)
        # empty article namespace in the sitemap + empty hub blocks
        with io.open(os.path.join(tmp, "sitemap.xml"), "w",
                     encoding="utf-8") as f:
            f.write("<?xml version='1.0'?>\n<urlset></urlset>\n")
        for hub in HUBS:
            with io.open(os.path.join(tmp, hub), "w", encoding="utf-8") as f:
                f.write("<!-- ARTICLE-LIST:START -->"
                       "<!-- ARTICLE-LIST:END -->\n")
        os.makedirs(os.path.join(tmp, "reports", "batches"))
        return tmp

    @staticmethod
    def _row(aid, status, batch="BATCH-A", path="cam-nang/a/%s.html",
             cat="Xe máy"):
        return {"article_id": aid, "status": status, "batch_id": batch,
                "output_path": path % aid.lower(), "category": cat,
                "notes": "", "slug": aid.lower(),
                "published_date": ""}

    def _sync_progress(self, tmp, rows):
        rb.write_factory_progress(tmp, rows)

    def test_qa_postcondition_written_row_must_be_recorded(self):
        rows = [self._row("AA-0001", "WRITING"),
                self._row("AA-0002", "WRITING")]
        tmp = self._mini(rows)
        self._sync_progress(tmp, rows)
        # the writer already wrote AA-0001 (as a DRAFT, deploy gate)
        # but QA did not record it
        p = os.path.join(tmp, rb.draft_rel(rows[0]["output_path"]))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8").write("x")
        problems, ok = vfs.verify(tmp, op="qa", batch_id="BATCH-A")
        self.assertFalse(ok)
        self.assertTrue(any("AA-0001" in p2 for p2 in problems))
        # after the QA mutation the same tree verifies green
        rows[0]["status"] = "FAIL"
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), rows)
        self._sync_progress(tmp, rows)
        problems, ok = vfs.verify(tmp, op="qa", batch_id="BATCH-A")
        self.assertEqual(problems, [])
        self.assertTrue(ok)

    def test_publish_postcondition(self):
        rows = [self._row("AA-0001", "PUBLISHED"),
                self._row("AA-0002", "PASS")]
        tmp = self._mini(rows)
        self._sync_progress(tmp, rows)
        p = os.path.join(tmp, rb.draft_rel(rows[1]["output_path"]))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8").write("x")
        p = os.path.join(tmp, rows[0]["output_path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8").write("x")
        # publish without ids is refused
        problems, ok = vfs.verify(tmp, op="publish")
        self.assertFalse(ok)
        # AA-0002 was in the publish scope but never flipped
        problems, ok = vfs.verify(tmp, op="publish", ids=["AA-0002"])
        self.assertFalse(ok)
        self.assertTrue(any("AA-0002 is still PASS" in p2
                            for p2 in problems))
        # published target must exist in the sitemap AND its category hub
        base = json.load(io.open(os.path.join(tmp, "config", "site.json"),
                                 encoding="utf-8"))["site_url"].rstrip("/")
        with io.open(os.path.join(tmp, "sitemap.xml"), "a",
                     encoding="utf-8") as f:
            f.write("<url><loc>%s/%s</loc></url>\n"
                    % (base, rows[0]["output_path"]))
        hub = os.path.join(tmp, lib.CATEGORIES[rows[0]["category"]])
        with io.open(hub, "w", encoding="utf-8") as f:
            f.write("<!-- ARTICLE-LIST:START --><a href=\"%s\">a</a>"
                    "<!-- ARTICLE-LIST:END -->\n" % rows[0]["output_path"])
        problems, ok = vfs.verify(tmp, op="publish", ids=["AA-0001"])
        self.assertEqual(problems, [])
        self.assertTrue(ok)

    def test_requeue_postcondition(self):
        rows = [self._row("AA-0001", "REPAIR"),
                self._row("AA-0002", "PLANNED")]
        tmp = self._mini(rows)
        self._sync_progress(tmp, rows)
        problems, ok = vfs.verify(tmp, op="requeue", ids=["AA-0001"])
        self.assertFalse(ok)
        self.assertTrue(any("requeue did not happen" in p2
                            for p2 in problems))
        problems, ok = vfs.verify(tmp, op="requeue", ids=["AA-0002"])
        self.assertEqual(problems, [])
        self.assertTrue(ok)

    def test_prepare_next_postcondition(self):
        rows = [self._row("AA-0001", "PLANNED"),
                self._row("AA-0002", "PLANNED")]
        tmp = self._mini(rows)
        self._sync_progress(tmp, rows)
        problems, ok = vfs.verify(tmp, op="prepare-next")
        self.assertFalse(ok)
        self.assertTrue(any("claim did not happen" in p2
                            for p2 in problems))
        rows[0]["status"] = "WRITING"
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), rows)
        self._sync_progress(tmp, rows)
        problems, ok = vfs.verify(tmp, op="prepare-next")
        self.assertEqual(problems, [])
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Health evaluation (scripts/factory_health.py)
# ---------------------------------------------------------------------------

class HealthEvaluationTests(unittest.TestCase):

    def _mini(self, rows, lock=None, txn=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), rows)
        os.makedirs(os.path.join(tmp, "data", "batches"), exist_ok=True)
        if lock is not None:
            with io.open(os.path.join(tmp, "data", "batches",
                                      "writer-lock.json"), "w",
                         encoding="utf-8") as f:
                json.dump(lock, f)
        if txn is not None:
            os.makedirs(os.path.join(tmp, "data", "batches", "txn"))
            with io.open(os.path.join(tmp, "data", "batches", "txn",
                                      "txn.json"), "w",
                         encoding="utf-8") as f:
                json.dump(txn, f)
        return tmp

    @staticmethod
    def _row(aid, status, path="cam-nang/a/%s.html"):
        return {"article_id": aid, "status": status, "batch_id": "BATCH-A",
                "output_path": path % aid.lower(), "category": "Xe máy",
                "notes": ""}

    def _touch(self, tmp, row, draft=True):
        rel = (rb.draft_rel(row["output_path"]) if draft
               else row["output_path"])
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8").write("x")

    def test_waiting_for_writer_is_never_stalled(self):
        tmp = self._mini([self._row("AA-0001", "PLANNED"),
                         self._row("AA-0002", "WRITING")])
        self.assertEqual(fh.evaluate(tmp)["status"],
                         "WAITING_FOR_WRITER")

    def test_ready_for_qa_when_written(self):
        row = self._row("AA-0001", "WRITING")
        tmp = self._mini([row])
        self.assertEqual(fh.evaluate(tmp)["status"], "WAITING_FOR_WRITER")
        self._touch(tmp, row)
        verdict = fh.evaluate(tmp)
        self.assertEqual(verdict["status"], "READY_FOR_QA")
        self.assertEqual(verdict["details"]["ready_for_qa_ids"],
                         ["AA-0001"])

    def test_ready_for_publish_beats_ready_for_qa(self):
        row = self._row("AA-0001", "PASS")
        row2 = self._row("AA-0002", "WRITING")
        tmp = self._mini([row, row2])
        self._touch(tmp, row)
        self._touch(tmp, row2)
        verdict = fh.evaluate(tmp)
        self.assertEqual(verdict["status"], "READY_FOR_PUBLISH")
        self.assertEqual(verdict["details"]["ready_for_publish_ids"],
                         ["AA-0001"])

    def test_fresh_lock_is_locked_but_stale_lock_is_not(self):
        rows = [self._row("AA-0001", "PLANNED")]
        now = rb.now_vn()
        fresh = {"writer_session": "session-A",
                 "updated_at": now.isoformat(timespec="seconds")}
        tmp = self._mini(rows, lock=fresh)
        self.assertEqual(fh.evaluate(tmp)["status"], "LOCKED")
        stale = dict(fresh, updated_at=(
            now - datetime.timedelta(
                minutes=rb.WRITER_LOCK_TTL_MINUTES + 5)
        ).isoformat(timespec="seconds"))
        tmp = self._mini(rows, lock=stale)
        verdict = fh.evaluate(tmp)
        # a stale lock is reclaimable: waiting proceeds (never "stalled")
        self.assertEqual(verdict["status"], "WAITING_FOR_WRITER")
        self.assertFalse(verdict["details"]["writer_lock_fresh"])

    def test_txn_recovery_required_beats_everything(self):
        row = self._row("AA-0001", "PASS")
        tmp = self._mini([row], lock={"writer_session": "session-A",
                                     "updated_at":
                                     rb.now_vn().isoformat(
                                         timespec="seconds")},
                         txn={"state": "PENDING"})
        self._touch(tmp, row)
        self.assertEqual(fh.evaluate(tmp)["status"], "RECOVERY_REQUIRED")

    def test_blocked_and_complete_verdicts(self):
        tmp = self._mini([self._row("AA-0001", "FAIL")])
        self.assertEqual(fh.evaluate(tmp)["status"], "BLOCKED")
        tmp = self._mini([self._row("AA-0001", "PUBLISHED")])
        self.assertEqual(fh.evaluate(tmp)["status"], "COMPLETE")

    def test_no_progress_must_be_earned_by_evidence(self):
        row = self._row("AA-0001", "WRITING")
        tmp = self._mini([row])
        self._touch(tmp, row)
        snap_path = os.path.join(tmp, "snapshot.json")
        self.assertEqual(fh.main_func(["--repo-root", tmp,
                                       "--snapshot", snap_path]), 0)
        snap = json.load(io.open(snap_path, encoding="utf-8"))
        # nothing changed since the snapshot + actionable backlog ->
        # the operation that claimed to do work did NOT move the state
        verdict = fh.evaluate(tmp, compare_snapshot=snap)
        self.assertEqual(verdict["status"], "NO_PROGRESS")
        # real semantic progress (status flip) -> HEALTHY
        row["status"] = "REVIEW"
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), [row])
        verdict = fh.evaluate(tmp, compare_snapshot=snap)
        self.assertEqual(verdict["status"], "HEALTHY")

    def test_fingerprint_ignores_report_timestamps(self):
        row = self._row("AA-0001", "WRITING")
        tmp = self._mini([row])
        fp1, _ = fh.fingerprint(tmp)
        os.makedirs(os.path.join(tmp, "reports", "batches"))
        with io.open(os.path.join(tmp, "reports", "batches",
                                  "factory-progress.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"schema_version": 2, "generated":
                       rb.now_vn_iso(), "pass": 999}, f)
        fp2, _ = fh.fingerprint(tmp)
        self.assertEqual(fp1, fp2)   # report churn is never "progress"
        row["status"] = "PASS"
        write_matrix_rows(os.path.join(tmp, "data",
                                       "content-matrix.csv"), [row])
        fp3, _ = fh.fingerprint(tmp)
        self.assertNotEqual(fp1, fp3)   # semantic change IS progress

    def test_corrupt_lock_never_crashes_health(self):
        tmp = self._mini([self._row("AA-0001", "PLANNED")])
        with io.open(os.path.join(tmp, "data", "batches",
                                  "writer-lock.json"), "w",
                     encoding="utf-8") as f:
            f.write("{broken")
        verdict = fh.evaluate(tmp)
        self.assertEqual(verdict["status"], "WAITING_FOR_WRITER")
        self.assertIsNone(verdict["details"]["writer_lock"])

    def test_health_is_read_only(self):
        row = self._row("AA-0001", "WRITING")
        tmp = self._mini([row])
        self._touch(tmp, row)
        before = set(os.listdir(os.path.join(tmp, "data")))
        fh.evaluate(tmp)
        fh.evaluate(tmp, compare_snapshot={"fingerprint": "x"})
        self.assertEqual(before, set(os.listdir(os.path.join(tmp, "data"))))


# ---------------------------------------------------------------------------
# Writer lock: atomicity, contention, stale reclaim, one-writer invariant
# ---------------------------------------------------------------------------

LOCK_WORKER = (
    "import json,sys\n"
    "sys.path.insert(0,%r)\n"
    "import run_article_batch as rb\n"
    "ok,lock=rb.acquire_writer_lock(%r,%r,%r)\n"
    "print(json.dumps({'acquired':bool(ok),'session':%r,"
    "'owner':(lock or {}).get('writer_session')}))\n"
)


class WriterLockContentionTests(unittest.TestCase):

    def _sandbox(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def test_twenty_processes_exactly_one_winner(self):
        tmp = self._sandbox()
        procs = []
        for i in range(20):
            session = "writer-%02d" % i
            procs.append(subprocess.Popen(
                [sys.executable, "-c",
                 LOCK_WORKER % (SCRIPTS, tmp, "BATCH-001", session,
                                session)],
                stdout=subprocess.PIPE))
        results = []
        for p in procs:
            out, _ = p.communicate(timeout=60)
            results.append(json.loads(out.decode("utf-8").strip()
                                      .splitlines()[-1]))
        winners = [r for r in results if r["acquired"]]
        self.assertEqual(len(winners), 1)
        winner = winners[0]["session"]
        # every loser read the winner's lock (they know who owns it)
        for r in results:
            if not r["acquired"]:
                self.assertEqual(r["owner"], winner)
        # the surviving lock file belongs to the winner (schema 2)
        with io.open(os.path.join(tmp, "data", "batches",
                                  "writer-lock.json"),
                     encoding="utf-8") as f:
            lock = json.load(f)
        self.assertEqual(lock["writer_session"], winner)
        self.assertEqual(lock["schema_version"], 2)
        self.assertTrue(lock.get("token"))
        self.assertEqual(lock["batch"], "BATCH-001")

    def test_one_writer_invariant_fresh_foreign_lock_refused(self):
        tmp = self._sandbox()
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertTrue(ok)
        ok2, lock2 = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertFalse(ok2)
        self.assertEqual(lock2["writer_session"], "session-A")
        # release is ownership-safe: a foreign session cannot free it
        self.assertFalse(rb.release_writer_lock(tmp, "session-B"))
        self.assertTrue(rb.release_writer_lock(tmp, "session-A"))
        self.assertIsNone(rb.writer_lock_status(tmp)[0])


class StaleLockReclaimTests(unittest.TestCase):
    """Serialized stale-lock reclaim: the recovery guard + CAS-like
    token checks guarantee a reclaim race can never clobber a fresh
    owner's lock."""

    def _sandbox(self, stale_lock=True):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if stale_lock:
            now = rb.now_vn()
            old = now - datetime.timedelta(
                minutes=rb.WRITER_LOCK_TTL_MINUTES + 5)
            rb.acquire_writer_lock(tmp, "BATCH-001", "session-old",
                                   now=old)
            lock, fresh = rb.writer_lock_status(tmp, now=now)
            self.assertIsNotNone(lock)
            self.assertFalse(fresh)
        return tmp

    def _guard_hold(self, tmp, age_minutes=0):
        gp = rb.writer_recovery_path(tmp)
        ts = rb.now_vn() - datetime.timedelta(minutes=age_minutes)
        with io.open(gp, "w", encoding="utf-8") as f:
            f.write(ts.isoformat(timespec="seconds"))
        return gp

    def test_second_reclaimer_waits_for_the_guard(self):
        tmp = self._sandbox()
        gp = self._guard_hold(tmp)   # reclaimer A holds the guard
        with io.open(os.path.join(tmp, "data", "batches",
                                  "writer-lock.json"),
                     encoding="utf-8") as f:
            before = f.read()
        # reclaimer B must NOT touch the stale lock while A is active
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertFalse(ok)
        with io.open(os.path.join(tmp, "data", "batches",
                                  "writer-lock.json"),
                     encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        os.remove(gp)
        # with the guard free, the same stale lock IS reclaimable
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertTrue(ok)
        self.assertEqual(lock["writer_session"], "session-B")

    def test_reclaim_race_never_clobbers_the_new_owner(self):
        tmp = self._sandbox()
        # reclaimer B wins the reclaim...
        ok, lock_b = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertTrue(ok)
        token_b = lock_b["token"]
        # ...reclaimer C (who saw the SAME stale lock) arrives late:
        # B's lock is FRESH now, so C must refuse, never delete it
        ok, lock_c = rb.acquire_writer_lock(tmp, "BATCH-001", "session-C")
        self.assertFalse(ok)
        self.assertEqual(lock_c["writer_session"], "session-B")
        with io.open(os.path.join(tmp, "data", "batches",
                                  "writer-lock.json"),
                     encoding="utf-8") as f:
            lock = json.load(f)
        self.assertEqual(lock["writer_session"], "session-B")
        self.assertEqual(lock["token"], token_b)

    def test_crashed_reclaimer_guard_does_not_deadlock(self):
        tmp = self._sandbox()
        self._guard_hold(tmp, age_minutes=rb.WRITER_RECOVERY_TTL_MINUTES + 1)
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertTrue(ok)
        self.assertEqual(lock["writer_session"], "session-B")

    def test_cas_replace_only_with_the_right_token(self):
        tmp = self._sandbox(stale_lock=False)
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertTrue(ok)
        lp = rb.writer_lock_path(tmp)
        self.assertFalse(rb._cas_replace_lock(lp, "wrong-token",
                                              dict(lock, head="h2")))
        with io.open(lp, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["token"], lock["token"])
        self.assertTrue(rb._cas_replace_lock(lp, lock["token"],
                                              dict(lock, head="h2")))
        with io.open(lp, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["head"], "h2")

    def test_same_session_heartbeat_cannot_clobber_a_takeover(self):
        tmp = self._sandbox(stale_lock=False)
        ok, lock_a = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertTrue(ok)
        # simulate a takeover: session-B reclaims a (stale) lock and
        # installs its own token while session-A was merely heartbeating
        ok, lock_b = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertFalse(ok)   # A's lock is fresh: no takeover yet
        # force the takeover by expiring A's lock, then B reclaims
        now = rb.now_vn() + datetime.timedelta(
            minutes=rb.WRITER_LOCK_TTL_MINUTES + 5)
        ok, lock_b = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B",
                                            now=now)
        self.assertTrue(ok)
        # A's stale heart-beat must NOT replace B's fresh lock
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertFalse(ok)
        self.assertEqual(lock["writer_session"], "session-B")


class TransactionCleanlinessTests(unittest.TestCase):

    def test_txn_marker_detection_end_to_end(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"),
                    os.path.join(tmp, "data", "content-matrix.csv"))
        # clean tree: no marker, verify + health both green on txn
        problems, ok = vfs.verify(tmp)
        self.assertTrue(any("sitemap" in p for p in problems))
        # (the minimal sandbox lacks sitemap/hubs; txn must NOT be among
        #  the problems)
        self.assertFalse(any("transaction" in p for p in problems))
        self.assertNotEqual(fh.evaluate(tmp)["status"],
                            "RECOVERY_REQUIRED")
        # inject a pending marker: verify fails-closed, health demands
        # recovery BEFORE any other verdict
        tdir = os.path.join(tmp, "data", "batches", "txn")
        os.makedirs(tdir)
        with io.open(os.path.join(tdir, "txn.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"state": "PENDING", "ids": ["AA-0001"]}, f)
        problems, ok = vfs.verify(tmp)
        self.assertTrue(any("pending transaction marker" in p
                            for p in problems))
        self.assertFalse(ok)
        self.assertEqual(fh.evaluate(tmp)["status"], "RECOVERY_REQUIRED")
        # corrupt marker is STILL a recovery problem (never ignored)
        with io.open(os.path.join(tdir, "txn.json"), "w",
                     encoding="utf-8") as f:
            f.write("{broken")
        problems, _ = vfs.verify(tmp)
        self.assertTrue(any("pending transaction marker" in p
                            for p in problems))
        self.assertEqual(fh.evaluate(tmp)["status"], "RECOVERY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
