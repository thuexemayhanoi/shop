#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chunked writer mode tests: next-chunk selection, scoped QA, resume-safe
checkpoint, writer lock, grouped publish scope, throughput counters and
kill-switch/scheduled-flag preservation."""
import csv
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib
import run_article_batch as rb


def reset_matrix_to_planned(path, writing_batch=None):
    with io.open(path, encoding="utf-8") as f:
        rd = csv.DictReader(f)
        header = list(rd.fieldnames)
        rows = list(rd)
    for r in rows:
        if lib.is_sample_row(r):
            continue
        if writing_batch and r["batch_id"] == writing_batch:
            r["status"] = "WRITING"
        else:
            r["status"] = "PLANNED"
        r["published_date"] = ""
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class ChunkedWriterTestCase(unittest.TestCase):
    """Sandbox with a planned matrix; lib.ROOT is redirected per test via a
    subprocess-free trick: the pure helpers take repo_root explicitly."""

    def _sandbox(self, writing_batch=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        matrix = os.path.join(tmp, "data", "content-matrix.csv")
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"), matrix)
        reset_matrix_to_planned(matrix, writing_batch)
        return tmp

    def _write_stub(self, tmp, row):
        p = os.path.join(tmp, row["output_path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write("<html><body><h1>stub %s</h1></body></html>"
                    % row["article_id"])
        return p

    def _run(self, tmp, argv):
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            code = rb.main_func(argv)
        finally:
            lib.ROOT = old
        return code

    def _matrix(self, tmp):
        with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            return list(csv.DictReader(f))


class ChunkSelectionTests(ChunkedWriterTestCase):
    def test_selects_exactly_n_rows_in_matrix_order(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        chunk = rb.select_next_chunk_rows(rows, tmp, 5)
        self.assertEqual(len(chunk), 5)
        ids = [r["article_id"] for r in chunk]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [r["article_id"] for r in rows[:5]])

    def test_chunk_size_clamped_to_10(self):
        self.assertEqual(rb.clamp_chunk_size(3), 3)
        self.assertEqual(rb.clamp_chunk_size(5), 5)
        self.assertEqual(rb.clamp_chunk_size(10), 10)
        self.assertEqual(rb.clamp_chunk_size(50), 10)
        self.assertEqual(rb.clamp_chunk_size(0), 1)

    def test_published_pass_fail_blocked_never_reselected(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        statuses = ["PUBLISHED", "PASS", "FAIL", "BLOCKED", "WRITING",
                    "REPAIR", "REVIEW"]
        for r, st in zip(rows[:7], statuses):
            r["status"] = st
        chunk = rb.select_next_chunk_rows(rows, tmp, 5)
        # deterministic matrix order: first eligible row is rows[4]
        # (WRITING); rows[5]/[6] are REPAIR/REVIEW; then rows[7] onward.
        expected = [rows[4]["article_id"]] + \
            [r["article_id"] for r in rows[7:11]]
        self.assertEqual([r["article_id"] for r in chunk], expected)
        # no published/pass/fail/blocked/review id ever re-claimed
        forbidden = {rows[i]["article_id"] for i in (0, 1, 2, 3, 5, 6)}
        self.assertFalse(forbidden &
                         {r["article_id"] for r in chunk})

    def test_writing_row_with_existing_file_goes_to_qa_not_chunk(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        self._write_stub(tmp, rows[0])
        chunk = rb.select_next_chunk_rows(rows, tmp, 5)
        self.assertNotIn(rows[0]["article_id"],
                         [r["article_id"] for r in chunk])
        # but it IS eligible for scoped QA
        qa = rb.select_qa_rows_by_ids(rows, [rows[0]["article_id"]], tmp)
        self.assertEqual([r["article_id"] for r in qa],
                         [rows[0]["article_id"]])

    def test_scoped_qa_rejects_pass_and_published(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        for st in ("PASS", "PUBLISHED"):
            rows[0]["status"] = st
            with self.assertRaises(rb.ChunkError):
                rb.select_qa_rows_by_ids(rows, [rows[0]["article_id"]], tmp)

    def test_scoped_qa_rejects_unknown_duplicate_and_unwritten(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        with self.assertRaises(rb.ChunkError):  # not in this batch
            rb.select_qa_rows_by_ids(rows, ["ZZ-9999"], tmp)
        with self.assertRaises(rb.ChunkError):  # duplicate id
            rb.select_qa_rows_by_ids(rows, [rows[0]["article_id"],
                                            rows[0]["article_id"]], tmp)
        with self.assertRaises(rb.ChunkError):  # WRITING without file
            rb.select_qa_rows_by_ids(rows, [rows[0]["article_id"]], tmp)

    def test_next_chunk_cli_writes_manifest_and_checkpoint(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        self._run(tmp, ["--batch", "BATCH-001", "--prepare-agent"])
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        code = self._run(tmp, ["--batch", "BATCH-001", "--next-chunk", "5"])
        self.assertEqual(code, 0)
        manifest = json.load(io.open(
            os.path.join(tmp, "data", "batches", "BATCH-001-chunk.json"),
            encoding="utf-8"))
        self.assertEqual(len(manifest["articles"]), 5)
        self.assertEqual(manifest["chunk"]["chunk_size"], 5)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches", "writer-checkpoint.json"),
            encoding="utf-8"))
        self.assertEqual(cp["batch"], "BATCH-001")
        self.assertEqual(cp["chunk_size"], 5)
        self.assertEqual(cp["current_chunk_ids"],
                         [r["article_id"] for r in rows[:5]])
        self.assertEqual(cp["pending_qa_ids"], cp["current_chunk_ids"])
        # statuses untouched by --next-chunk (all stay WRITING)
        m = self._matrix(tmp)
        self.assertEqual(len([r for r in m if r["status"] == "WRITING"]), 50)

    def test_next_chunk_repeats_deterministically_without_duplicates(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        first = rb.select_next_chunk_rows(
            rb.batch_rows(_load(tmp), "BATCH-001"), tmp, 5)
        for r in first:
            self._write_stub(tmp, r)
        second = rb.select_next_chunk_rows(
            rb.batch_rows(_load(tmp), "BATCH-001"), tmp, 5)
        ids1 = {r["article_id"] for r in first}
        ids2 = {r["article_id"] for r in second}
        self.assertFalse(ids1 & ids2)
        self.assertEqual(len(ids2), 5)

    def test_time_budget_stops_cleanly_before_new_chunk(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        code = self._run(tmp, ["--batch", "BATCH-001", "--next-chunk", "5",
                               "--time-budget-remaining", "0"])
        self.assertEqual(code, 0)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches", "writer-checkpoint.json"),
            encoding="utf-8"))
        self.assertEqual(cp["last_completed_step"], "time-budget-stop")
        self.assertEqual(cp["current_chunk_ids"], [])
        self.assertFalse(os.path.exists(os.path.join(
            tmp, "data", "batches", "BATCH-001-chunk.json")))


class WriterLockTests(ChunkedWriterTestCase):
    def test_lock_prevents_second_writer(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertTrue(ok)
        self.assertEqual(lock["writer_session"], "session-A")
        ok2, lock2 = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B")
        self.assertFalse(ok2)
        self.assertEqual(lock2["writer_session"], "session-A")

    def test_same_session_can_reacquire(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        ok, _ = rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertTrue(ok)

    def test_stale_lock_recovered(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        now = datetime.datetime.now()
        old = now - datetime.timedelta(
            minutes=rb.WRITER_LOCK_TTL_MINUTES + 5)
        rb.acquire_writer_lock(tmp, "BATCH-001", "session-A", now=old)
        lock, fresh = rb.writer_lock_status(tmp, now=now)
        self.assertIsNotNone(lock)
        self.assertFalse(fresh)
        ok, lock = rb.acquire_writer_lock(tmp, "BATCH-001", "session-B",
                                          now=now)
        self.assertTrue(ok)
        self.assertEqual(lock["writer_session"], "session-B")

    def test_release_is_idempotent_and_session_scoped(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        self.assertFalse(rb.release_writer_lock(tmp, "session-B"))
        self.assertTrue(rb.release_writer_lock(tmp, "session-A"))
        self.assertIsNone(rb.writer_lock_status(tmp)[0])
        self.assertTrue(rb.release_writer_lock(tmp, "session-A"))

    def test_next_chunk_refuses_when_fresh_lock_owned_elsewhere(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        self._run(tmp, ["--batch", "BATCH-001", "--prepare-agent"])
        rb.acquire_writer_lock(tmp, "BATCH-001", "session-A")
        code = self._run(tmp, ["--batch", "BATCH-001", "--next-chunk", "5",
                               "--writer-session", "session-B"])
        self.assertEqual(code, rb.EXIT_USAGE)
        self.assertFalse(os.path.exists(os.path.join(
            tmp, "data", "batches", "BATCH-001-chunk.json")))


class CheckpointTests(ChunkedWriterTestCase):
    def test_matrix_wins_over_stale_checkpoint(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        cp = rb.empty_checkpoint("BATCH-001")
        cp["current_chunk_ids"] = [rows[0]["article_id"]]
        cp["pending_publish_ids"] = [rows[1]["article_id"]]
        cp["pending_repair_ids"] = [rows[2]["article_id"]]
        # matrix truth: row0 PUBLISHED, row1 WRITING (not PASS), row2 FAIL
        _set_status(tmp, rows[0]["article_id"], "PUBLISHED")
        _set_status(tmp, rows[2]["article_id"], "FAIL")
        out = rb.reconcile_checkpoint(cp, _load(tmp), "BATCH-001")
        self.assertEqual(out["current_chunk_ids"], [])  # PUBLISHED wins
        self.assertEqual(out["pending_publish_ids"], [])  # not PASS anymore
        self.assertEqual(out["pending_repair_ids"], [])  # FAIL wins

    def test_checkpoint_of_other_batch_is_discarded(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        cp = rb.empty_checkpoint("BATCH-001")
        cp["current_chunk_ids"] = ["KN-0001"]
        out = rb.reconcile_checkpoint(cp, _load(tmp), "BATCH-002")
        self.assertEqual(out["batch"], "BATCH-002")
        self.assertEqual(out["current_chunk_ids"], [])

    def test_resume_checkpoint_roundtrip(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        cp = rb.empty_checkpoint("BATCH-001")
        cp["current_chunk_ids"] = [r["article_id"] for r in rows[:5]]
        cp["completed_ids"] = [rows[49]["article_id"]]
        rb.save_checkpoint(tmp, cp)
        loaded = rb.load_checkpoint(tmp)
        self.assertEqual(loaded["current_chunk_ids"],
                         cp["current_chunk_ids"])
        self.assertEqual(loaded["completed_ids"], cp["completed_ids"])
        # reconcile keeps both lists (statuses still WRITING)
        out = rb.reconcile_checkpoint(loaded, _load(tmp), "BATCH-001")
        self.assertEqual(out["current_chunk_ids"], cp["current_chunk_ids"])
        self.assertEqual(out["completed_ids"], cp["completed_ids"])

    def test_scoped_qa_updates_checkpoint(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        for r in rows[:3]:
            self._write_stub(tmp, r)
        ids = ",".join(r["article_id"] for r in rows[:3])
        code = self._run(tmp, ["--batch", "BATCH-001", "--ids", ids, "--qa"])
        # stub articles cannot pass the gate; rc 3 = FAIL rows recorded
        self.assertEqual(code, rb.EXIT_FAILS)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches", "writer-checkpoint.json"),
            encoding="utf-8"))
        self.assertEqual(cp["pending_qa_ids"], [])
        self.assertEqual(cp["last_completed_step"], "qa-completed")
        # only the 3 scoped rows left WRITING state
        m = self._matrix(tmp)
        changed = [r for r in m if r["batch_id"] == "BATCH-001"
                   and r["status"] not in ("WRITING",)]
        self.assertEqual(len(changed), 3)

    def test_chunk_complete_updates_checkpoint_and_throughput(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        _set_status(tmp, rows[0]["article_id"], "PUBLISHED")
        _set_status(tmp, rows[1]["article_id"], "FAIL")
        cp = rb.empty_checkpoint("BATCH-001")
        cp["current_chunk_ids"] = [rows[0]["article_id"],
                                   rows[1]["article_id"],
                                   rows[2]["article_id"]]
        rb.save_checkpoint(tmp, cp)
        # explicit --ids: the two terminal rows complete the chunk
        code = self._run(tmp, ["--batch", "BATCH-001", "--chunk-complete",
                              "--ids", ",".join([rows[0]["article_id"],
                                                 rows[1]["article_id"]])])
        self.assertEqual(code, 0)
        cp = json.load(io.open(
            os.path.join(tmp, "data", "batches", "writer-checkpoint.json"),
            encoding="utf-8"))
        self.assertEqual(cp["current_chunk_ids"], [rows[2]["article_id"]])
        self.assertEqual(sorted(cp["completed_ids"]),
                         sorted([rows[0]["article_id"],
                                 rows[1]["article_id"]]))
        tp = json.load(io.open(os.path.join(
            tmp, "reports", "batches", "factory-throughput.json"),
            encoding="utf-8"))
        b = tp["batches"]["BATCH-001"]
        self.assertEqual(b["articles_written"], 2)
        self.assertEqual(b["chunks_completed"], 1)


class GroupedPublishScopeTests(ChunkedWriterTestCase):
    def test_publish_scope_refuses_non_pass_ids(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        _set_status(tmp, rows[0]["article_id"], "PASS")
        self._write_stub(tmp, rows[0])
        _set_status(tmp, rows[1]["article_id"], "WRITING")
        code = self._run(tmp, ["--batch", "BATCH-001", "--publish",
                               "--ids", ",".join(
                                   [rows[0]["article_id"],
                                    rows[1]["article_id"]])])
        self.assertEqual(code, rb.EXIT_USAGE)  # invalid id refuses the whole op

    def test_publish_scope_lists_only_chunk_pass_ids(self):
        import contextlib
        tmp = self._sandbox(writing_batch="BATCH-001")
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        for r in rows[:5]:
            _set_status(tmp, r["article_id"], "PASS")
            self._write_stub(tmp, r)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self._run(tmp, ["--batch", "BATCH-001", "--publish",
                                  "--ids", ",".join(
                                      r["article_id"] for r in rows[:2])])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue().count(".html"), 2)
        self.assertIn("--publish %s,%s --dry-run"
                      % (rows[0]["article_id"], rows[1]["article_id"]),
                      buf.getvalue())


class ThroughputTests(ChunkedWriterTestCase):
    def test_throughput_counters_accumulate(self):
        tmp = self._sandbox(writing_batch="BATCH-001")
        rb.update_throughput(tmp, "BATCH-001", articles_qa_checked=3,
                             qa_score_sum=270, qa_score_count=3)
        rb.update_throughput(tmp, "BATCH-001", articles_qa_checked=2,
                             qa_score_sum=190, qa_score_count=2,
                             repair_count=1)
        tp = json.load(io.open(os.path.join(
            tmp, "reports", "batches", "factory-throughput.json"),
            encoding="utf-8"))
        b = tp["batches"]["BATCH-001"]
        self.assertEqual(b["articles_qa_checked"], 5)
        self.assertEqual(b["qa_score_sum"], 460)
        self.assertEqual(b["average_qa_score"], 92.0)
        self.assertEqual(b["repair_count"], 1)
        self.assertEqual(b["articles_published"], 0)
        self.assertEqual(b["publish_operations"], 0)


class InvariantTests(ChunkedWriterTestCase):
    def test_kill_switch_semantics_unchanged(self):
        cfg = json.load(io.open(os.path.join(ROOT, "config",
                                             "content-factory.json"),
                                encoding="utf-8"))
        self.assertTrue(cfg["enabled"])
        self.assertTrue(cfg["scheduled_runs_enabled"])

    def test_matrix_invariants_preserved_by_orchestration(self):
        import validate_content_matrix as vcm
        tmp = self._sandbox(writing_batch="BATCH-001")
        self._run(tmp, ["--batch", "BATCH-001", "--prepare-agent"])
        self._run(tmp, ["--batch", "BATCH-001", "--next-chunk", "5"])
        rows = rb.batch_rows(_load(tmp), "BATCH-001")
        for r in rows[:5]:
            self._write_stub(tmp, r)
        self._run(tmp, ["--batch", "BATCH-001",
                        "--ids", ",".join(r["article_id"]
                                          for r in rows[:5]), "--qa"])
        m = _load(tmp)
        errors, _ = vcm.validate(m, lib.load_ownership())
        self.assertEqual(errors, [])
        self.assertEqual(len(m), 2008)  # 2000 production + 8 samples


def _load(tmp):
    old = lib.ROOT
    lib.ROOT = tmp
    try:
        return lib.load_matrix()
    finally:
        lib.ROOT = old


def _set_status(tmp, article_id, status):
    path = os.path.join(tmp, "data", "content-matrix.csv")
    with io.open(path, encoding="utf-8") as f:
        rd = csv.DictReader(f)
        header = list(rd.fieldnames)
        rows = list(rd)
    for r in rows:
        if r["article_id"] == article_id:
            r["status"] = status
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    unittest.main()
