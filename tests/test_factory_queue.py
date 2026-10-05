#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write-ahead queue runner tests (scripts/factory_queue.py).

Pins the TURBO QUEUE contract ported from the stable /vanchinh factory:

  * the queue is revalidated against fresh matrix truth BEFORE any
    mutation (duplicates / unknown id / wrong batch / PUBLISHED /
    terminal FAIL-BLOCKED / missing file are all FATAL, exit 1,
    nothing mutated);
  * the queue is consumed as deterministic PAIRS of 2, sequentially,
    inside one run;
  * NEW mode claims the exact pair IDs (never a blind claim) via
    run_article_batch.py --claim-ids --ids ...; REPAIR mode NEVER
    claims;
  * already-PASS rows publish directly (never re-QA'd);
  * scoped QA exit contract: ONLY 0/3/4 are valid results; 3/4 are
    legitimate recorded outcomes (recoverable), anything else marks
    the pair qa_failed (recoverable, run continues);
  * publish is explicit-ID ONLY and ALWAYS dry-run first, then the
    real transaction (factory.mjs --publish "ID,..." --dry-run);
  * a failed pair NEVER rolls back already-published pairs;
  * the run report (reports/batches/factory-queue-last-run.json,
    FACTORY_QUEUE_REPORT-overridable, env read at write time) is
    rewritten after every pair and carries the contract fields.

The canonical tools (run_article_batch.py, factory.mjs) are STUBBED via
factory_queue.run_cmd; the sandbox fixture redirects article_lib.ROOT to
a temp repository so no production state is ever touched.
"""
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import article_lib as lib               # noqa: E402
import factory_queue as fq              # noqa: E402


def _fixture_rows():
    """A minimal deterministic matrix (schema of the real ledger)."""
    return [
        # BATCH-001 (active)
        ("KN-1001", "PLANNED", "cam-nang/kinh-nghiem/kn-1001.html", "BATCH-001", "draft"),
        ("KN-1002", "PLANNED", "cam-nang/kinh-nghiem/kn-1002.html", "BATCH-001", "draft"),
        ("KN-1003", "PLANNED", "cam-nang/kinh-nghiem/kn-1003.html", "BATCH-001", None),
        ("KN-1004", "WRITING", "cam-nang/kinh-nghiem/kn-1004.html", "BATCH-001", "draft"),
        ("KN-1005", "PASS", "cam-nang/kinh-nghiem/kn-1005.html", "BATCH-001", "draft"),
        ("KN-1006", "PUBLISHED", "cam-nang/kinh-nghiem/kn-1006.html", "BATCH-001", "final"),
        ("KN-1007", "FAIL", "cam-nang/kinh-nghiem/kn-1007.html", "BATCH-001", "draft"),
        # BATCH-002
        ("HD-2001", "PLANNED", "cam-nang/hoi-dap/hd-2001.html", "BATCH-002", "draft"),
    ]


class QueueRunnerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        t = cls.tmp
        os.makedirs(os.path.join(t, "config"))
        for name in ("article-rubric.json", "business-facts.json",
                     "seo-ownership.json", "site.json"):
            src = os.path.join(ROOT, "config", name)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(t, "config", name))
        os.makedirs(os.path.join(t, "data"))
        with io.open(os.path.join(ROOT, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            cls.header = next(csv.reader(f))
        cls._write_matrix(t, _fixture_rows())
        for (aid, status, op, batch, where) in _fixture_rows():
            if where is None:
                continue
            rel = op if where == "final" else os.path.join("_drafts", op)
            p = os.path.join(t, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            io.open(p, "w", encoding="utf-8").write(
                "<html><body>%s</body></html>" % aid)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _write_matrix(cls, root, rows):
        with io.open(os.path.join(root, "data", "content-matrix.csv"),
                     "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cls.header)
            for (aid, status, op, batch, where) in rows:
                r = [""] * len(cls.header)
                r[cls.header.index("article_id")] = aid
                r[cls.header.index("status")] = status
                r[cls.header.index("category")] = "Kinh nghiệm"
                r[cls.header.index("primary_keyword")] = "kw " + aid
                r[cls.header.index("working_title")] = "Title " + aid
                r[cls.header.index("slug")] = aid.lower()
                r[cls.header.index("output_path")] = op
                r[cls.header.index("parent_hub")] = "kinhnghiem.html"
                r[cls.header.index("batch_id")] = batch
                w.writerow(r)

    def _statuses(self):
        with io.open(os.path.join(self.tmp, "data", "content-matrix.csv"),
                     encoding="utf-8") as f:
            return {r["article_id"]: (r.get("status") or "").strip()
                    for r in csv.DictReader(f)}

    def _set_status(self, aid, status):
        with io.open(os.path.join(self.tmp, "data", "content-matrix.csv"),
                     encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        for r in rows:
            if r and r[self.header.index("article_id")] == aid:
                r[self.header.index("status")] = status
        with io.open(os.path.join(self.tmp, "data", "content-matrix.csv"),
                     "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)

    def _fake(self, qa_result=None, qa_rc=0, claim_rc=0,
              dry_rc=0, publish_rc=0):
        """Stub factory_queue.run_cmd. qa_result maps id -> post-QA status
        (default PASS). Records every command in cmdlog."""
        cmdlog = []
        qa_result = dict(qa_result or {})

        def run(cmd):
            cmdlog.append(list(cmd))
            rc = subprocess.CompletedProcess(cmd, 0, "", "")
            if "--claim-ids" in cmd:
                if claim_rc:
                    return subprocess.CompletedProcess(cmd, claim_rc, "", "")
                for a in cmd[cmd.index("--ids") + 1].split(","):
                    self._set_status(a, "WRITING")
            elif "--qa" in cmd:
                # the canonical QA tool records PASS/FAIL/REVIEW in the
                # matrix and THEN exits 3/4 to signal the recorded rows;
                # an abnormal exit (1/2/...) records NOTHING
                if qa_rc in (0, 3, 4):
                    for a in cmd[cmd.index("--ids") + 1].split(","):
                        self._set_status(a, qa_result.get(a, "PASS"))
                return subprocess.CompletedProcess(cmd, qa_rc, "", "")
            elif "--publish" in cmd:
                ids = cmd[cmd.index("--publish") + 1]
                if "--dry-run" in cmd:
                    if dry_rc:
                        return subprocess.CompletedProcess(
                            cmd, dry_rc, "", "")
                else:
                    if publish_rc:
                        return subprocess.CompletedProcess(
                            cmd, publish_rc, "", "")
                    for a in ids.split(","):
                        self._set_status(a, "PUBLISHED")
            return rc
        return run, cmdlog

    def _run(self, mode, ids, **kw):
        fake, cmdlog = self._fake(**kw)
        old_root, old_run = lib.ROOT, fq.run_cmd
        lib.ROOT = self.tmp
        fq.run_cmd = fake
        try:
            rc = fq.run_queue("BATCH-001", mode, ids)
        finally:
            lib.ROOT, fq.run_cmd = old_root, old_run
        report = os.path.join(self.tmp, "reports", "batches",
                              "factory-queue-last-run.json")
        rep = json.load(io.open(report, encoding="utf-8")) \
            if os.path.isfile(report) else None
        return rc, rep, cmdlog

    def _reset(self):
        self._write_matrix(self.tmp, _fixture_rows())

    def setUp(self):
        self._reset()

    # ------------------------------------------------------ validation

    def test_queue_splits_into_pairs_of_two(self):
        for aid in ("KN-1001", "KN-1002", "KN-1003"):
            self._set_status(aid, "WRITING")
        p = os.path.join(self.tmp, "_drafts", "cam-nang", "kinh-nghiem",
                         "kn-1003.html")
        io.open(p, "w", encoding="utf-8").write("<html>x</html>")
        rc, rep, _ = self._run("repair",
                               ["KN-1004", "KN-1005", "KN-1001",
                                "KN-1002", "KN-1003"])
        self.assertEqual(rc, 0)
        self.assertEqual([len(x["ids"]) for x in rep["pairs"]],
                         [2, 2, 1])

    def test_duplicate_ids_refused(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1004", "KN-1004"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])
        self.assertIsNone(rep)

    def test_unknown_id_refused(self):
        rc, rep, cmdlog = self._run("repair", ["KN-9999"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])

    def test_wrong_batch_refused(self):
        rc, rep, cmdlog = self._run("repair", ["HD-2001"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])

    def test_published_row_refused(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1006"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])
        self.assertEqual(self._statuses()["KN-1006"], "PUBLISHED")

    def test_terminal_fail_row_refused(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1007"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])

    def test_missing_file_refused(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1003"])
        self.assertEqual(rc, 1)
        self.assertEqual(cmdlog, [])

    # ------------------------------------------------------ consumption

    def test_new_mode_claims_then_qas(self):
        rc, rep, cmdlog = self._run("new", ["KN-1001", "KN-1002"])
        self.assertEqual(rc, 0)
        claims = [c for c in cmdlog if "--claim-ids" in c]
        qas = [c for c in cmdlog if "--qa" in c]
        self.assertEqual(len(claims), 1)
        self.assertEqual(len(qas), 1)
        # claim happens BEFORE qa
        self.assertLess(cmdlog.index(claims[0]), cmdlog.index(qas[0]))
        self.assertEqual(rep["pairs"][0]["claimed"],
                         ["KN-1001", "KN-1002"])

    def test_repair_mode_never_claims(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1004", "KN-1005"])
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in cmdlog if "--claim-ids" in c], [])

    def test_qa_exit_3_records_recoverable_and_continues(self):
        rc, rep, _ = self._run("new", ["KN-1001", "KN-1002"],
                               qa_result={"KN-1001": "PASS",
                                          "KN-1002": "FAIL"}, qa_rc=3)
        self.assertEqual(rc, 0)
        self.assertEqual(rep["published_ids"], ["KN-1001"])
        self.assertEqual(rep["recoverable_ids"], ["KN-1002"])
        self.assertEqual(rep["published_total"], 1)

    def test_qa_exit_1_marks_pair_qa_failed(self):
        rc, rep, _ = self._run("new", ["KN-1001", "KN-1002"], qa_rc=1)
        self.assertEqual(rc, 0)
        self.assertEqual(rep["pairs"][0]["status"], "qa_failed")
        self.assertEqual(rep["pairs"][0]["qa_rc"], 1)
        self.assertEqual(sorted(rep["recoverable_ids"]),
                         ["KN-1001", "KN-1002"])
        self.assertEqual(rep["published_ids"], [])

    def test_publish_is_dry_run_then_real(self):
        rc, rep, cmdlog = self._run("new", ["KN-1001"])
        pubs = [c for c in cmdlog if "--publish" in c]
        self.assertEqual(len(pubs), 2)
        self.assertIn("--dry-run", pubs[0])
        self.assertNotIn("--dry-run", pubs[1])

    def test_publishes_only_pass_ids(self):
        rc, rep, cmdlog = self._run(
            "new", ["KN-1001", "KN-1002"],
            qa_result={"KN-1001": "PASS", "KN-1002": "REVIEW"})
        pubs = [c for c in cmdlog if "--publish" in c]
        self.assertEqual(len(pubs), 2)   # dry-run + real
        self.assertEqual(pubs[0][pubs[0].index("--publish") + 1],
                         "KN-1001")
        self.assertEqual(rep["pairs"][0]["published"], ["KN-1001"])
        self.assertEqual(rep["pairs"][0]["review"], ["KN-1002"])

    def test_failed_pair_does_not_rollback_published_pairs(self):
        # pair 1 QA explodes (rc 1); pair 2 still publishes
        for a in ("KN-1001", "KN-1002", "KN-1004", "KN-1005"):
            self._set_status(a, "WRITING")
        behavior = {"KN-1001": 1, "KN-1004": 0, "KN-1005": 0}

        def run(cmd):
            cmd2 = list(cmd)
            if "--qa" in cmd2:
                ids = cmd2[cmd2.index("--ids") + 1].split(",")
                code = max(behavior.get(a, 0) for a in ids)
                if not code:
                    for a in ids:
                        self._set_status(a, "PASS")
                return subprocess.CompletedProcess(cmd2, code, "", "")
            if "--publish" in cmd2 and "--dry-run" not in cmd2:
                for a in cmd2[cmd2.index("--publish") + 1].split(","):
                    self._set_status(a, "PUBLISHED")
            return subprocess.CompletedProcess(cmd2, 0, "", "")
        old_root, old_run = lib.ROOT, fq.run_cmd
        lib.ROOT, fq.run_cmd = self.tmp, run
        try:
            rc = fq.run_queue("BATCH-001", "repair",
                              ["KN-1001", "KN-1002", "KN-1004", "KN-1005"])
        finally:
            lib.ROOT, fq.run_cmd = old_root, old_run
        report = os.path.join(self.tmp, "reports", "batches",
                              "factory-queue-last-run.json")
        rep = json.load(io.open(report, encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(rep["pairs"][0]["status"], "qa_failed")
        self.assertEqual(rep["pairs"][1]["status"], "published")
        self.assertEqual(rep["published_ids"],
                         ["KN-1004", "KN-1005"])
        self.assertEqual(sorted(rep["recoverable_ids"]),
                         ["KN-1001", "KN-1002"])

    def test_touched_pass_rows_publish_direct(self):
        rc, rep, cmdlog = self._run("repair", ["KN-1005"])
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in cmdlog if "--qa" in c], [])
        pubs = [c for c in cmdlog if "--publish" in c]
        self.assertEqual(len(pubs), 2)
        self.assertEqual(rep["published_ids"], ["KN-1005"])

    def test_report_contract_fields(self):
        rc, rep, _ = self._run("new", ["KN-1001", "KN-1002"])
        for k in ("schema_version", "batch", "mode", "queue",
                  "pair_size", "started", "finished", "pairs",
                  "published_total", "published_ids",
                  "recoverable_ids", "fatal"):
            self.assertIn(k, rep)
        self.assertEqual(rep["batch"], "BATCH-001")
        self.assertEqual(rep["mode"], "new")
        self.assertEqual(rep["queue"], ["KN-1001", "KN-1002"])
        self.assertEqual(rep["published_total"], 2)
        self.assertEqual(rep["recoverable_ids"], [])
        self.assertIsNotNone(rep["finished"])

    def test_report_env_override_respected(self):
        # env is read at WRITE time: a mid-run env change must apply
        custom = os.path.join(self.tmp, "custom-report.json")
        os.environ["FACTORY_QUEUE_REPORT"] = custom
        try:
            rc, _, _ = self._run("new", ["KN-1001"])
        finally:
            del os.environ["FACTORY_QUEUE_REPORT"]
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(custom))
        rep = json.load(io.open(custom, encoding="utf-8"))
        self.assertEqual(rep["published_ids"], ["KN-1001"])


if __name__ == "__main__":
    unittest.main()
