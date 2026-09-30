#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workflow contract tests for .github/workflows/factory-operator.yml.

The four-layer reliability hardening made the operator workflow
FAIL-CLOSED. This suite pins that contract: a workflow exiting 0 is NOT
production success, so every soft path must be contract-checked:

  * QA/requeue exit codes: ONLY 0/3/4 may end green; 1 (tool/config),
    2 (usage/lock) and any UNKNOWN exit are RED
  * op=unittest is RED when the suite fails (evidence still dumped)
  * pushes prove pushed=true; 5 failed retries are RED (no silent
    success when the push failed)
  * after a rebase the FULL canonical gate + semantic verifier rerun
    on the rebased tree BEFORE pushing it (tree A is never tested and
    tree B pushed); a rebase CONFLICT aborts safely (no force push,
    no blind auto-resolution)
  * after the push, origin/main must equal the tested result SHA and
    the EXACT final main SHA is re-verified (FINAL_MAIN_SHA must equal
    the tested tree; INPUT_SHA / OP_RESULT_SHA / FINAL_MAIN_SHA are
    recorded in the step summary)
  * the operator postcondition (scripts/verify_factory_state.py with
    op-specific args) runs even when the operation step failed
  * empty batch/ids operator-command fields cannot break the parser:
    jq defaults + sanitisation, explicit non-empty requirements where
    ids are mandatory, and the python tools tolerate empty --ids
  * the operator command itself is whitelisted, one command at a time,
    and superseded commands are aborted
"""
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

OPERATOR_YML = os.path.join(ROOT, ".github", "workflows",
                            "factory-operator.yml")
ARTICLE_YML = os.path.join(ROOT, ".github", "workflows",
                           "article-quality.yml")
GATE_SH = os.path.join(ROOT, "scripts", "ci", "factory_final_gate.sh")


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


class OperatorWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.y = read(OPERATOR_YML)

    # ------------------------------------------------------- op validation

    def test_operator_command_is_whitelisted(self):
        for op in ("prepare-next", "qa", "publish", "consistency",
                   "recover", "requeue", "unittest",
                   "apply-article-shell"):
            self.assertIn(op, self.y)
        self.assertIn('echo "::error::unsupported op: $OP"; exit 1',
                      self.y)

    def test_superseded_command_aborts(self):
        # ONE command at a time: a command file not introduced by THIS
        # push is a stale command and must abort, not run concurrently
        self.assertIn("operator command superseded by a newer push",
                      self.y)
        self.assertIn('CMD_COMMIT" != "$GITHUB_SHA"', self.y)

    def test_single_flight_concurrency_no_cancel(self):
        self.assertIn("concurrency:", self.y)
        self.assertIn("group: article-batch-production", self.y)
        self.assertIn("cancel-in-progress: false", self.y)

    def test_permissions_are_minimal_for_the_job(self):
        self.assertIn("contents: write", self.y)
        self.assertNotIn("secrets.", self.y.replace(
            "secrets.GITHUB_TOKEN", "GITHUB_TOKEN_REF"))
        self.assertNotIn("cron:", self.y)

    # --------------------------------------------------- QA exit contract

    def test_qa_allowed_exits_only_zero_three_four(self):
        y = self.y
        self.assertIn('case "$code" in', y)
        self.assertIn('0) echo "qa exit code: 0 (operation valid)"', y)
        self.assertIn(
            '3) echo "qa exit code: 3 (FAIL article rows legitimately '
            'recorded)"', y)
        self.assertIn(
            '4) echo "qa exit code: 4 (REVIEW/BLOCKED rows legitimately '
            'recorded)"', y)

    def test_unknown_or_non_contract_qa_exit_fails_the_workflow(self):
        y = self.y
        # the catch-all arm is RED: tool/config=1, usage/lock=2 and any
        # UNKNOWN exit can never finish green
        self.assertIn('*) echo "::error::qa failed with exit $code '
                      '(tool/config=1, usage/lock=2, unknown=other; '
                      'ONLY 0/3/4 are valid results)"; exit "$code" ;;',
                      y)

    def test_requeue_exit_contract(self):
        y = self.y
        self.assertIn("0|3)", y)   # 3 = refusals recorded is legitimate
        self.assertIn(
            '::error::requeue failed with exit $code '
            '(0=ok, 3=refusals recorded; 1/2/4 and unknown exits are '
            'errors)"; exit "$code"', y)

    def test_unittest_failure_fails_the_workflow(self):
        y = self.y
        self.assertIn(
            'if [ "$code" != "0" ]; then', y)
        self.assertIn("unittest suite FAILED with exit $code", y)
        # evidence is preserved even on failure (fail-closed, not
        # fail-silent): the failure grep + tail dump happen first
        self.assertIn("tail -n 80 reports/batches/unittest-output.txt",
                      y)

    # ------------------------------------------------- push fail-closed

    def test_push_proves_pushed_true(self):
        self.assertIn("pushed=false", self.y)
        self.assertIn("if git push; then", self.y)
        self.assertIn('pushed=true', self.y)

    def test_push_retry_loop_is_bounded_and_retests(self):
        y = self.y
        self.assertIn("for i in 1 2 3 4 5", y)
        self.assertIn("push retry $i/5", y)

    def test_push_retry_exhaustion_is_red_not_silent(self):
        y = self.y
        self.assertIn('if [ "$pushed" != true ]; then', y)
        self.assertIn("push failed after 5 retries", y)
        # and the branch exits RED after exhaustion
        self.assertIn(
            'echo "::error::push failed after 5 retries — nothing was '
            'reported as success; recovery evidence is preserved"\n'
            '            exit 1', y)

    def test_rebase_path_fetches_and_rebases_main(self):
        y = self.y
        self.assertIn("git fetch origin main", y)
        self.assertIn("if ! git rebase origin/main; then", y)

    def test_rebase_conflict_aborts_safely_no_force_push(self):
        y = self.y
        self.assertIn("rebase conflict — STOP SAFE: no force push, "
                      "no blind auto-resolution", y)
        self.assertIn("git rebase --abort", y)
        # NO force push anywhere in the operator workflow (the only
        # --force is the read-only checkout of the verified final SHA)
        self.assertNotIn("push --force", y)
        self.assertNotIn("push -f", y)
        self.assertNotIn("push --force-with-lease", y)
        self.assertNotIn("+main", y)

    def test_canonical_gate_reruns_after_every_rebase(self):
        y = self.y
        # (a) the pre-push canonical gate on the operation tree,
        # (b) the FULL gate again on every rebased tree inside the
        #     retry loop, (c) once more on the exact final main SHA
        self.assertGreaterEqual(
            y.count("bash scripts/ci/factory_final_gate.sh"), 3)
        # the semantic verifier also reruns after the rebase, on the
        # rebased tree, BEFORE pushing it
        self.assertIn(
            "# REBASE RETEST CONTRACT: the rebased tree has NOT been\n"
            "              # tested. Rerun the FULL canonical gate AND "
            "the semantic\n"
            "              # postcondition verifier on this exact tree "
            "before pushing.", y)
        self.assertIn(
            "python3 scripts/verify_factory_state.py $verify_args", y)
        self.assertGreaterEqual(
            y.count("python3 scripts/verify_factory_state.py"), 3)

    def test_verifier_runs_on_the_exact_pushed_tree(self):
        y = self.y
        self.assertIn(
            'git checkout --force --detach "$FINAL_MAIN_SHA"', y)
        self.assertIn(
            "PRODUCTION_INVARIANT=PASS (canonical gate + semantic "
            "verifier green on the EXACT final main SHA)", y)

    def test_final_main_sha_must_equal_the_tested_tree(self):
        y = self.y
        # in the push step: remote main must BE the tested result commit
        self.assertIn(
            'if [ "$FINAL_MAIN_SHA" != "$OP_RESULT_SHA" ]; then', y)
        self.assertIn("exact-SHA contract violated", y)
        # in the final step: the final tree is only trusted when it is
        # the SAME tree the gate verified
        self.assertIn(
            'if [ "$FINAL_MAIN_SHA" != "$op_result_sha" ]; then', y)
        self.assertIn("final state NOT verified", y)

    def test_sha_audit_trail_recorded_in_step_summary(self):
        y = self.y
        for key in ("INPUT_SHA", "OP_RESULT_SHA", "FINAL_MAIN_SHA"):
            self.assertIn(key, y)
        self.assertIn("echo \"INPUT_SHA=$input_sha\"", y)
        self.assertIn("echo \"OP_RESULT_SHA=$op_result_sha\"", y)
        self.assertIn("echo \"FINAL_MAIN_SHA=$FINAL_MAIN_SHA\"", y)
        self.assertIn("GITHUB_STEP_SUMMARY", y)

    def test_op_result_sha_never_recorded_inside_pushed_files(self):
        # schema-2 semantics: the final SHA is captured from git AFTER
        # the push — a file can never prove "this commit contains me"
        y = self.y
        self.assertIn(
            "# INPUT_SHA: the exact tree this operation starts from. "
            "The\n          # FINAL result SHA is captured from git "
            "AFTER the push — never\n          # recorded inside the "
            "pushed files themselves.", y)
        self.assertIn('echo "op_result_sha=$OP_RESULT_SHA" '
                      '>> "$GITHUB_ENV"', y)

    # -------------------------------------------- postcondition contract

    def test_operator_postcondition_checked_even_on_failure(self):
        y = self.y
        self.assertIn("Post-operation semantic state verification", y)
        # `if: always()` — a green tool exit is NOT enough, the
        # semantic state must be verified before anything is pushed
        self.assertIn("if: always()", y)
        for op, args in (
                ("publish", "--op publish --ids $ids"),
                ("requeue", "--op requeue --ids $ids"),
                ("qa", "--op qa --ids $ids"),
                ("prepare-next", "--op prepare-next")):
            self.assertIn(args, y)

    def test_matrix_invariant_never_bypassed(self):
        self.assertIn("python3 scripts/validate_content_matrix.py",
                      self.y)
        # pre-op recovery + consistency: a pending transaction is
        # recovered before ANY mutation
        self.assertIn("node scripts/js/factory.mjs --recover", self.y)
        self.assertIn("node scripts/js/factory.mjs --consistency",
                      self.y)

    def test_evidence_upload_never_blocks_the_verdict(self):
        y = self.y
        self.assertGreaterEqual(y.count("continue-on-error: true"), 3)
        self.assertIn("if: always()", y)
        self.assertIn("if-no-files-found: ignore", y)

    # -------------------------------------------- empty-args robustness

    def test_operator_command_fields_default_to_empty_safely(self):
        y = self.y
        # jq defaults + character-class sanitisation: a missing/empty
        # batch or ids field can never inject shell syntax or crash jq
        self.assertIn('.batch // ""', y)
        self.assertIn('.ids // ""', y)
        self.assertIn('.date // ""', y)
        self.assertIn('tr -cd \'A-Z0-9-\'', y)
        self.assertIn('tr -cd \'A-Z0-9,-\'', y)
        self.assertIn('tr -cd \'0-9-\'', y)

    def test_requeue_and_publish_require_non_empty_ids(self):
        y = self.y
        self.assertIn(
            'if [ -z "$ids" ]; then echo "::error::requeue requires '
            'ids"; exit 1; fi', y)
        self.assertIn(
            'if [ -z "$ids" ]; then echo "::error::publish requires '
            'ids"; exit 1; fi', y)

    def test_empty_ids_do_not_break_the_python_parsers(self):
        import run_article_batch as rb
        import requeue_rows as rq
        import verify_factory_state as vfs
        import article_lib as lib
        # requeue: empty ids -> clean "no ids" exit 1, never a crash
        self.assertEqual(rq.parse_ids(""), [])
        self.assertEqual(rq.parse_ids(" , , "), [])
        self.assertEqual(rq.main(["--ids", ""]), 1)
        # verify: empty ids + empty batch parse to op-wide verification
        ids = [s for s in "".split(",") if s.strip()]
        self.assertEqual(ids, [])
        # run_article_batch scoped-QA with an empty --ids falls back to
        # batch-wide selection instead of raising
        import csv
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copytree(os.path.join(ROOT, "config"),
                        os.path.join(tmp, "config"))
        rows = [{"article_id": "AA-0001", "status": "WRITING",
                 "batch_id": "BATCH-A", "output_path": "a.html",
                 "slug": "aa-0001", "category": "Xe máy",
                 "notes": ""}]
        with io.open(os.path.join(tmp, "data", "content-matrix.csv"),
                     "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
        old = lib.ROOT
        lib.ROOT = tmp
        try:
            self.assertEqual(
                rb.main_func(["--batch", "BATCH-A", "--ids", "",
                              "--qa"]), rb.EXIT_OK)   # nothing to QA
            self.assertEqual(
                rb.main_func(["--batch", "BATCH-A", "--ids", ",",
                              "--qa"]), rb.EXIT_OK)
        finally:
            lib.ROOT = old
        # verify CLI with empty ids/batch on a clean mini tree
        os.makedirs(os.path.join(tmp, "reports", "batches"))
        with io.open(os.path.join(tmp, "sitemap.xml"), "w",
                     encoding="utf-8") as f:
            f.write("<?xml version='1.0'?>\n<urlset></urlset>\n")
        for hub in ("kinhnghiem.html", "antoan.html", "xemay.html",
                    "dulich.html", "cungduong.html", "hoidap.html"):
            with io.open(os.path.join(tmp, hub), "w",
                         encoding="utf-8") as f:
                f.write("<!-- ARTICLE-LIST:START -->"
                        "<!-- ARTICLE-LIST:END -->\n")
        rb.write_factory_progress(tmp, rows)
        self.assertEqual(
            vfs.main_func(["--repo-root", tmp, "--op", "qa",
                           "--ids", "", "--batch", ""]), 0)


class CanonicalGateContract(unittest.TestCase):
    """The ONE canonical gate is the drift-free definition of green for
    EVERY consumer (article-quality PR gate, factory operator, local
    runs)."""

    def test_gate_runs_both_suites_and_the_semantic_verifier(self):
        g = read(GATE_SH)
        self.assertIn("python3 -m unittest discover tests", g)
        self.assertIn('node --test "tests/js/**/*.test.mjs"', g)
        self.assertIn("scripts/validate_content_matrix.py", g)
        self.assertIn("--consistency", g)
        self.assertIn("generate_sitemap.py --check", g)
        self.assertIn("generate_category_pages.py --check", g)
        self.assertIn("verify_factory_state.py --op consistency", g)

    def test_gate_is_deterministic_only(self):
        g = read(GATE_SH)
        self.assertIn("set -euo pipefail", g)
        self.assertNotIn("curl", g)
        self.assertNotIn("wget", g)
        self.assertNotIn("api_key", g.lower())
        self.assertNotIn("openai", g.lower())
        self.assertNotIn("anthropic", g.lower())

    def test_article_quality_uses_the_same_canonical_gate(self):
        y = read(ARTICLE_YML)
        self.assertIn("bash scripts/ci/factory_final_gate.sh", y)
        # per-candidate checks stay in the workflow (same tools, exit 3)
        self.assertIn("scripts/validate_article.py", y)
        self.assertIn("scripts/check_cannibalization.py", y)
        self.assertIn("scripts/score_article.py", y)
        self.assertIn("status=3", y)


if __name__ == "__main__":
    unittest.main()
