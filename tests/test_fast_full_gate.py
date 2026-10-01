#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAST/FULL gate contract tests (fast micro-pair loop, 2026-10-01).

Pins the approved dual-mode workflow contract:

  CONTENT-ONLY PUSH = FAST:
    - article-quality.yml runs NO full canonical L1-L4 per pair; it
      runs matrix invariants + whole-site factory consistency + the
      same per-candidate validate/cannibalize/score tools as before
      (critical business/legal/source gates are inside those tools).
    - factory-publish.yml stays bounded per pair: selection, recover,
      exact claim, exact QA, exact publish, promoted-article gate,
      matrix smoke, consistency smoke, commit, push, clean txn/lock.

  ENGINE/WORKFLOW PUSH = FULL (fail-closed):
    - qa_scope decides "full" for engine/global-affecting changes;
      article-quality.yml then runs the ONE canonical gate
      (scripts/ci/factory_final_gate.sh).

  HEAVY AUDIT MOVED to factory-publish-verify.yml:
    - full python + node suites, full consistency, semantic verifier,
      generator freshness, full cannibalization sweep, evidence-aware
      full published-articles audit
    - runs on: manual dispatch, batch terminal (dispatched by
      factory-publish.yml), engine-change push (paths trigger), final
      2000 audit (manual)
    - READ-ONLY: never pushes, never publishes without --dry-run.

  SAFETY GATES NEVER WEAKENED:
    - thresholds stay owner-approved 75/70/75 (rubric-driven)
    - chunk_size = 2 bounds the micro-pair (config/content-factory.json)
    - txn/lock safety, exact-ID publish, no blind claim, no force push
      unchanged (covered by the dedicated suites; re-pinned here for
      the touched workflows).
"""
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import qa_scope  # noqa: E402


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


class FastFullGateContractTest(unittest.TestCase):
    """The workflow files implement the approved dual-mode contract."""

    def test_content_only_change_is_fast_engine_change_is_full(self):
        # the scope decision is qa_scope's, pinned by its own suite; the
        # gate mapping in the workflow is the exact one-line rule
        matrix = qa_scope.lib.load_matrix()
        fast = qa_scope.select_scope(
            ["_drafts/cam-nang/xe-may/xm-0001.html"], matrix, ROOT)
        engine = qa_scope.select_scope(["scripts/score_article.py"],
                                      matrix, ROOT)
        shared = qa_scope.select_scope(
            ["_drafts/cam-nang/xe-may/xm-0001.html",
             "config/article-rubric.json"], matrix, ROOT)
        self.assertEqual(fast["scope"], "changed")
        self.assertEqual(engine["scope"], "full")
        self.assertEqual(shared["scope"], "full")  # any engine file wins

    def test_fast_gate_runs_no_full_l1_l4_per_content_pair(self):
        y = _read(".github/workflows/article-quality.yml")
        self.assertIn("if: steps.candidates.outputs.gate != 'full'", y)
        self.assertIn("if: steps.candidates.outputs.gate == 'full'", y)

    def test_publish_workflow_stays_bounded_per_pair(self):
        y = _read(".github/workflows/factory-publish.yml")
        for needle in (
            "factory_push_selection.py --added",
            "node scripts/js/factory.mjs --recover",
            "run_article_batch.py --batch",
            "gate_published_articles.py --ids",
            "validate_content_matrix.py",
            "verify_factory_state.py --op publish",
            "verify_factory_state.py --op consistency",
            "txn marker left behind",
            "batch lock left behind",
            "push failed after 2 attempts",
        ):
            self.assertIn(needle, y)
        # no full published-corpus audit inside the pair loop anymore
        self.assertNotIn("gate_published_articles.py\n", y)
        # no force push anywhere
        self.assertNotIn("--force", y)

    def test_publish_workflow_no_recursion_on_state_commit(self):
        # the factory's own state commit (promoted PUBLISHED files)
        # re-triggers the workflow but selection returns mode=skip and
        # exits bounded — pinned by the selector's own tests; the
        # workflow must keep the SKIP contract
        y = _read(".github/workflows/factory-publish.yml")
        self.assertIn("SKIP:", y)
        self.assertIn("nothing to do", y)

    def test_heavy_audit_lives_only_in_verify_workflow(self):
        v = _read(".github/workflows/factory-publish-verify.yml")
        for needle in (
            "python3 -m unittest discover tests",
            "node --test \"${NODE_TEST_FILES[@]}\"",
            "python3 scripts/validate_content_matrix.py",
            "node scripts/js/factory.mjs --consistency",
            "python3 scripts/verify_factory_state.py --op consistency",
            "python3 scripts/generate_sitemap.py --check",
            "python3 scripts/generate_category_pages.py --check",
            "python3 scripts/full_cannibalization_audit.py",
            "python3 scripts/gate_published_articles.py",
        ):
            self.assertIn(needle, v, needle)
        # read-only: no commit, no push, no real publish
        self.assertNotIn("git push", v)
        self.assertNotIn("git commit", v)
        self.assertIn("--dry-run", v)
        self.assertIn("contents: read", v)
        self.assertNotIn("contents: write", v)
        # triggers: manual dispatch + engine-change push (batch terminal
        # arrives via the dispatch from factory-publish.yml)
        self.assertIn("workflow_dispatch", v)
        self.assertIn("push:", v)
        for path in ("scripts/**", "tests/**", "config/**",
                     ".github/workflows/**"):
            self.assertIn(path, v)
        # never runs after each pair: no cam-nang/_drafts path trigger
        self.assertNotIn("cam-nang/**", v)
        self.assertNotIn("_drafts/**", v)

    def test_verify_lock_check_handles_unexpanded_glob(self):
        # regression pin (2026-10-01 verify failure): the stale-lock
        # sweep must treat an UNEXPANDED data/batches/*.lock glob (no
        # locks present) as clean. The case pattern must be the escaped
        # two-asterisk form "*\**)" — the lone form "*\*)" only matches
        # strings ENDING in a literal '*' so the unexpanded glob fell
        # through to the fail branch and the step could never pass.
        v = _read(".github/workflows/factory-publish-verify.yml")
        self.assertIn("*\\**)", v)
        self.assertNotIn('*\\*) ;;', v)
        # behavior pin: the exact shell snippet passes when no lock
        # files exist (same as the workflow step body)
        import subprocess
        snippet = (
            "set -eu\n"
            "test ! -f data/batches/txn/txn.json || "
            "{ echo 'pending txn marker present'; exit 1; }\n"
            "for l in data/batches/*.lock; do\n"
            "  test -z \"$l\" && continue\n"
            "  case \"$l\" in\n"
            "    *\\**) ;;\n"
            "    *) echo \"stale batch lock present: $l\"; exit 1 ;;\n"
            "  esac\n"
            "done\n"
            "echo 'factory state clean'\n"
        )
        r = subprocess.run(
            ["bash", "-c", snippet], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_thresholds_not_weakened(self):
        rubric = json.load(io.open(os.path.join(
            ROOT, "config", "article-rubric.json"), encoding="utf-8"))
        self.assertEqual(rubric["thresholds"]["PASS"]["min"], 75)
        self.assertEqual(rubric["thresholds"]["REVIEW"]["min"], 70)
        self.assertTrue(rubric["thresholds"]["PASS"]
                        ["requires_no_critical_failures"])
        # publish path keeps the rubric as the single threshold source
        self.assertEqual(rubric["thresholds"]["PASS"]["min"], 75)

    def test_chunk_size_is_two_in_production_config(self):
        cfg = json.load(io.open(os.path.join(
            ROOT, "config", "content-factory.json"), encoding="utf-8"))
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg.get("chunk_size"), 2)
        # workflow docs agree with the config (pair contract = 2)
        y = _read(".github/workflows/factory-publish.yml")
        self.assertIn("chunk_size = 2", y)

    def test_sweep_script_uses_the_canonical_checker(self):
        s = _read("scripts/full_cannibalization_audit.py")
        self.assertIn("lib.check_cannibalization", s)
        self.assertIn("PUBLISHED", s)
        self.assertIn("EXIT_FAIL", s)
        self.assertIn("EXIT_ERROR", s)

    def test_sweep_enumerates_published_articles_from_matrix_truth(self):
        # fast structural check against the real matrix (the full sweep
        # itself runs in the heavy verify workflow / its own CLI)
        import full_cannibalization_audit as sweep
        rows = sweep.published_article_paths()
        self.assertGreater(len(rows), 100)
        for aid, path in rows[:20]:
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(aid.startswith("SAMPLE"))


if __name__ == "__main__":
    unittest.main()
