#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-driven factory-publish contract tests (Simple Production Mode).

Static workflow contract pins for .github/workflows/factory-publish.yml
plus functional tests for the --claim-ids exact-ID claim mode of
scripts/run_article_batch.py:

  * event-driven only: NO cron/schedule, bounded steps, no AI/secrets
  * concurrency group serializes runs; cancel-in-progress is FALSE
  * claim is EXACT-ID (--claim-ids --ids ...), never a blind claim
  * QA is scoped (--ids), exit contract ONLY 0/3/4; a FAIL/REVIEW row
    never blocks this pair's PASS rows (per-article isolation)
  * publish is explicit-ID ONLY (factory.mjs --publish "ID,..."),
    single batch, thresholds read from config/article-rubric.json
  * fail-closed: pending txn recovered first; no marker/lock may be
    left behind; refusals exit non-zero
  * single derived-state commit with bounded rebase retry (2 attempts),
    consistency re-verified on the rebased tree BEFORE pushing
  * freshly published articles always fully re-validated
    (gate_published_articles --ids) + batch-end FULL audit
  * thresholds 75/70/75 centralized in config/article-rubric.json:
    score_article.py and factory.mjs contain NO hardcoded band logic
"""
import csv
import io
import json
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

import article_lib as lib                      # noqa: E402
import run_article_batch as rb                 # noqa: E402
import score_article as sc                     # noqa: E402

WF = os.path.join(ROOT, ".github", "workflows", "factory-publish.yml")


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


class PublishWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.y = read(WF)

    # ------------------------------------------------------- triggers

    def test_event_driven_no_cron(self):
        self.assertNotIn("schedule:", self.y)
        self.assertNotIn("cron:", self.y)
        self.assertIn("workflow_dispatch:", self.y)
        self.assertIn("paths: ['_drafts/cam-nang/**', 'cam-nang/**', "
                      "'.github/workflows/factory-publish.yml']",
                      self.y)

    def test_concurrency_serializes_and_never_cancels(self):
        self.assertIn("group: factory-publish", self.y)
        self.assertIn("cancel-in-progress: false", self.y)

    def test_no_ai_no_secrets(self):
        y = self.y
        self.assertNotIn("OPENAI", y)
        self.assertNotIn("ANTHROPIC", y)
        self.assertNotIn("MISTRAL", y)
        self.assertNotIn("api_key", y.lower().replace("api-keys", ""))

    # ------------------------------------------------------- exact IDs

    def test_claim_is_exact_id_never_blind(self):
        y = self.y
        self.assertIn("--claim-ids", y)
        self.assertIn('python3 scripts/run_article_batch.py --batch '
                      '"${{ steps.select.outputs.batch }}" --claim-ids '
                      '--ids "${{ steps.select.outputs.claim_ids }}"', y)
        # the OLD blind claim mode must NOT appear in this workflow
        self.assertNotIn("--prepare-agent", y)

    def test_qa_is_scoped_with_exit_contract(self):
        y = self.y
        self.assertIn('--ids "${{ steps.select.outputs.qa_ids }}" --qa', y)
        for code in ("0", "3", "4"):
            self.assertIn("%s)" % code, y)
        self.assertIn("ONLY 0/3/4 are valid results", y)

    def test_publish_is_explicit_id_only(self):
        y = self.y
        self.assertIn(
            'node scripts/js/factory.mjs --publish '
            '"${{ steps.passids.outputs.ids }}"', y)
        self.assertIn("--dry-run", y)

    def test_publish_gate_and_batch_end_audit(self):
        y = self.y
        self.assertIn("gate_published_articles.py --ids", y)
        self.assertIn("batch-end FULL audit", y)
        self.assertIn("verify_factory_state.py --op publish", y)
        self.assertIn("verify_factory_state.py --op consistency", y)

    # ---------------------------------------------------- fail-closed

    def test_recovers_pending_transaction_before_mutations(self):
        y = self.y
        self.assertIn("node scripts/js/factory.mjs --recover", y)
        self.assertIn("pending txn marker still present after --recover", y)

    def test_asserts_clean_state_after_commit(self):
        y = self.y
        self.assertIn("txn marker left behind", y)
        self.assertIn("batch lock left behind", y)

    def test_single_commit_with_bounded_rebase_retry(self):
        y = self.y
        self.assertIn("git commit -m", y)
        self.assertIn("for attempt in 1 2", y)
        self.assertIn("git pull --rebase origin main", y)
        self.assertIn("push failed after 2 attempts", y)

    def test_publish_gate_uses_rubric_not_magic_numbers(self):
        # the workflow documents the canonical threshold source
        y = self.y
        self.assertIn("config/article-rubric.json", y)
        self.assertIn("75/70/75", y)


class ThresholdCentralization(unittest.TestCase):
    """75/70/75 lives in ONE place: config/article-rubric.json."""

    def test_rubric_thresholds(self):
        rubric = json.loads(read(os.path.join(ROOT, "config",
                                              "article-rubric.json")))
        th = rubric["thresholds"]
        self.assertEqual(th["PASS"]["min"], 75)
        self.assertEqual(th["PASS"]["max"], 100)
        self.assertEqual(th["REVIEW"]["min"], 70)
        self.assertEqual(th["REVIEW"]["max"], 74)
        self.assertEqual(th["FAIL"]["min"], 0)
        self.assertEqual(th["FAIL"]["max"], 69)
        # the 75/70/75 mapping is documented in the rubric itself
        self.assertIn("mapping_note", rubric["threshold_policy"])
        self.assertEqual(rubric["threshold_policy"]["qa_warning_band"],
                         {"min": 75, "max": 89})

    def test_score_article_has_no_hardcoded_bands(self):
        src = read(os.path.join(SCRIPTS, "score_article.py"))
        self.assertIn("def status_from_totals(", src)
        self.assertIn("def rubric_thresholds(", src)
        self.assertIn('rubric.get("thresholds")', src)
        # the old 90/80 inline band logic is gone
        self.assertNotIn("total < 90", src)
        self.assertNotIn("total >= 80", src)
        self.assertNotIn("score >= 90", src)

    def test_factory_mjs_reads_rubric(self):
        src = read(os.path.join(SCRIPTS, "js", "factory.mjs"))
        self.assertIn("function readRubric()", src)
        self.assertIn("thresholds?.PASS?.min", src)
        self.assertIn("rubric.passMin", src)
        # the old hardcoded gates are gone
        self.assertNotIn("score < 90", src)
        self.assertNotIn("PASS requires score >= 90", src)
        self.assertNotIn("score ${row.score} < 90", src)

    def test_status_from_totals_mapping(self):
        rubric = json.loads(read(os.path.join(ROOT, "config",
                                              "article-rubric.json")))
        f = sc.status_from_totals
        # PASS band: 75..100 (75-89 carries a QA warning, 90+ excellent)
        self.assertEqual(f(100, [], [], rubric), "PASS")
        self.assertEqual(f(90, [], [], rubric), "PASS")
        self.assertEqual(f(75, [], [], rubric), "PASS")
        # REVIEW band 70-74
        self.assertEqual(f(74, [], [], rubric), "REVIEW")
        self.assertEqual(f(70, [], [], rubric), "REVIEW")
        # FAIL band < 70
        self.assertEqual(f(69, [], [], rubric), "FAIL")
        self.assertEqual(f(0, [], [], rubric), "FAIL")
        # CRITICAL GATES ARE NEVER LOWERED: any critical failure is FAIL
        # even at score 100, and review flags always hold REVIEW
        self.assertEqual(f(100, ["confirmed wrong business price"], [],
                           rubric), "FAIL")
        self.assertEqual(f(95, [], ["similar title"], rubric), "REVIEW")

    def test_threshold_change_is_config_driven(self):
        # atomic proof that the code reads the rubric: raise PASS.min to
        # 80 in a COPY and the same totals map differently
        rubric = json.loads(read(os.path.join(ROOT, "config",
                                              "article-rubric.json")))
        rubric["thresholds"]["PASS"]["min"] = 80
        rubric["thresholds"]["REVIEW"]["min"] = 70
        self.assertEqual(sc.status_from_totals(76, [], [], rubric), "REVIEW")
        self.assertEqual(sc.status_from_totals(80, [], [], rubric), "PASS")


class ClaimIdsTests(unittest.TestCase):
    """--claim-ids: exact-ID claim, never a blind first-N claim."""

    def _sandbox(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        matrix = os.path.join(tmp, "data", "content-matrix.csv")
        shutil.copy(os.path.join(ROOT, "data", "content-matrix.csv"), matrix)
        # every production row PLANNED except one WRITING probe row
        rows = []
        with io.open(matrix, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        probe = None
        for r in rows:
            if lib.is_sample_row(r):
                continue
            if probe is None and r["batch_id"] == "BATCH-012":
                probe = r["article_id"]
                r["status"] = "WRITING"
            else:
                r["status"] = "PLANNED"
            r["published_date"] = ""
        with io.open(matrix, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return tmp, probe

    def _run(self, tmp, argv):
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            return rb.main_func(argv)
        finally:
            lib.ROOT = old

    def _statuses(self, tmp):
        with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                     encoding="utf-8", newline="") as f:
            return {r["article_id"]: (r["status"] or "").strip()
                    for r in csv.DictReader(f)}

    def _b12_planned(self, tmp, n=2):
        with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                     encoding="utf-8", newline="") as f:
            return [r["article_id"] for r in csv.DictReader(f)
                    if (r["batch_id"] or "").strip() == "BATCH-012"
                    and not r["article_id"].startswith("SAMPLE")
                    and (r["status"] or "").strip() == "PLANNED"][:n]

    def test_claim_ids_claims_exactly_those_rows(self):
        tmp, probe = self._sandbox()
        wanted = self._b12_planned(tmp)
        self.assertEqual(len(wanted), 2)
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids",
                             "--ids", ",".join(wanted)])
        self.assertEqual(rc, rb.EXIT_OK)
        st = self._statuses(tmp)
        for aid in wanted:
            self.assertEqual(st[aid], "WRITING")
        # every OTHER BATCH-012 PLANNED row stays PLANNED (exact scope)
        others = self._b12_planned(tmp, 50)
        for aid in others:
            if aid not in wanted:
                self.assertEqual(st[aid], "PLANNED")
        # manifest written for exactly the claimed ids
        manifest = json.loads(read(os.path.join(
            tmp, "data", "batches", "BATCH-012.json")))
        self.assertEqual(manifest["batch_id"], "BATCH-012")
        self.assertEqual(
            sorted(a["article_id"] for a in manifest["articles"]),
            sorted(wanted))

    def test_claim_ids_refuses_non_planned_row(self):
        tmp, probe = self._sandbox()
        self.assertIsNotNone(probe)  # the WRITING probe row
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids",
                             "--ids", probe])
        self.assertEqual(rc, rb.EXIT_USAGE)
        # nothing was claimed
        self.assertEqual(self._statuses(tmp)[probe], "WRITING")

    def test_claim_ids_refuses_unknown_id(self):
        tmp, probe = self._sandbox()
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids",
                             "--ids", "ZZ-9999"])
        self.assertEqual(rc, rb.EXIT_USAGE)

    def test_claim_ids_refuses_missing_ids_argument(self):
        tmp, probe = self._sandbox()
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids"])
        self.assertEqual(rc, rb.EXIT_USAGE)

    def test_claim_ids_refuses_when_lock_held(self):
        tmp, probe = self._sandbox()
        # a fresh lock of another runner blocks the claim (exit 2)
        lock = os.path.join(tmp, "data", "batches", "BATCH-012.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        # lock file format: a bare timezone-aware Hanoi ISO timestamp
        io.open(lock, "w", encoding="utf-8").write(rb.now_vn_iso())
        wanted = self._b12_planned(tmp)
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids",
                             "--ids", ",".join(wanted)])
        self.assertEqual(rc, rb.EXIT_USAGE)

    def test_kill_switch_blocks_claim_ids(self):
        tmp, probe = self._sandbox()
        cfg = os.path.join(tmp, "config", "content-factory.json")
        data = json.loads(read(cfg))
        data["enabled"] = False
        io.open(cfg, "w", encoding="utf-8").write(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        wanted = self._b12_planned(tmp)
        rc = self._run(tmp, ["--batch", "BATCH-012", "--claim-ids",
                             "--ids", ",".join(wanted)])
        self.assertEqual(rc, rb.EXIT_USAGE)


class WorkflowYamlLint(unittest.TestCase):
    """Deterministic lint for the YAML hazard class that broke
    factory-publish.yml at startup (both run #4 and run #5 failed with
    zero jobs): a plain (unquoted) scalar mapping value containing ': '
    is INVALID YAML - e.g. `- name: Guard: no lock` - and GitHub then
    rejects the whole workflow file. Block-quoted scalars and the
    contents of block scalars (run: |) are exempt.
    """

    KEY_LINE = re.compile(r"^(\s*(?:- )?)([A-Za-z_][\w-]*):(?!\s*[|>])(.*)$")

    def _workflow_files(self):
        wf_dir = os.path.join(ROOT, ".github", "workflows")
        for fn in sorted(os.listdir(wf_dir)):
            if fn.endswith((".yml", ".yaml")):
                yield fn, os.path.join(wf_dir, fn)

    def test_no_plain_scalar_contains_colon_space(self):
        for fn, path in self._workflow_files():
            text = read(path)
            for i, line in enumerate(text.splitlines(), 1):
                s = line.rstrip("\n")
                if not s.strip() or s.lstrip().startswith("#"):
                    continue
                m = self.KEY_LINE.match(s)
                if not m:
                    continue
                value = m.group(3).strip()
                if not value or value.startswith(("'", '"')):
                    continue  # empty or quoted scalar
                self.assertFalse(
                    re.search(r":\s", value),
                    "%s line %d: plain scalar value contains ': ' "
                    "(invalid YAML - quote the value or drop the colon): %r"
                    % (fn, i, s.strip()))

    def test_step_names_have_no_colon_space(self):
        # explicit pin of the exact 2026-09-30 startup failure:
        # `- name: Guard: no pending transaction...` made GitHub reject
        # the entire factory-publish.yml (runs 36751415249/36751593494,
        # zero jobs). The step name is now parenthesized.
        y = read(WF)
        for line in y.splitlines():
            stripped = line.strip()
            if stripped.startswith("- name:"):
                value = stripped[len("- name:"):].strip()
                if not value.startswith(("'", '"')):
                    self.assertFalse(
                        re.search(r":\s", value),
                        "step name is a plain scalar containing ': ': %r"
                        % stripped)


if __name__ == "__main__":
    unittest.main()
