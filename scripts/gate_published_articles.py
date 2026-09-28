#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate: every PUBLISHED article must validate and score PASS.

Used by the factory operator (publish / apply-article-shell ops) and safe
to run locally at any time. Exit 0 = every checked article passes
scripts/validate_article.py and scripts/score_article.py.

Scoped since the workflow hardening (2026-09-28):
  * `--ids AT-0076,KN-0077` — publish scope: fully re-validate ONLY the
    freshly published articles (never re-scans the other published
    articles). Used by the publish op right after promotion; these
    articles are always re-validated, evidence is never reused for them.
  * no `--ids` (FULL audit) — every published article, but an article is
    SKIPPED when its recorded QA evidence still matches (content hash +
    config hash + validator version, see scripts/qa_scope.py). A changed
    article, a rubric/engine change or a validator bump always forces a
    real re-validation. Full audits run at batch completion, on
    apply-article-shell ops and on manual FULL runs.
  * Successful full-audit validations refresh the stored evidence.
"""
import csv
import datetime
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import qa_scope  # noqa: E402


def published_rows():
    with open(os.path.join(REPO, "data", "content-matrix.csv"),
              encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r["status"] == "PUBLISHED"
                and not r["article_id"].startswith("SAMPLE")
                and os.path.isfile(os.path.join(REPO, r["output_path"]))]
    return rows


def main():
    ids = []
    args = sys.argv[1:]
    if "--ids" in args:
        i = args.index("--ids")
        if i + 1 >= len(args):
            print("usage: gate_published_articles.py [--ids A,B,...]")
            return 2
        ids = [s.strip() for s in args[i + 1].split(",") if s.strip()]
    rows = published_rows()
    if ids:
        known = {r["article_id"]: r for r in rows}
        missing = [i for i in ids if i not in known]
        if missing:
            print("GATE REFUSED: not PUBLISHED rows with existing files: %s"
                  % ", ".join(missing))
            return 2
        files = [(i, known[i]["output_path"]) for i in ids]
        reused = 0
    else:
        # FULL audit with evidence reuse (hash-matched PASS evidence only)
        cfg = qa_scope.config_sha256(REPO)
        evidence = qa_scope.load_evidence(REPO)
        files = []
        reused = 0
        for r in rows:
            path = os.path.join(REPO, r["output_path"])
            entry = evidence.get(r["article_id"])
            if qa_scope.evidence_is_reusable(entry, path, cfg):
                reused += 1
                continue
            files.append((r["article_id"], r["output_path"]))
    bad = 0
    passed = []
    for aid, f in files:
        ok = True
        for tool in ("scripts/validate_article.py",
                     "scripts/score_article.py"):
            p = subprocess.run([sys.executable, tool, f], cwd=REPO,
                               capture_output=True, text=True)
            if p.returncode != 0:
                ok = False
                bad += 1
                print("GATE FAIL", f, p.returncode)
                print(p.stdout[-800:])
        if ok:
            passed.append((aid, f))
    if passed:
        cfg = qa_scope.config_sha256(REPO)
        entries = [{
            "article_id": aid,
            "content_sha256": qa_scope.file_sha256(os.path.join(REPO, f)),
            "config_sha256": cfg,
            "validator_version": qa_scope.lib.VALIDATOR_VERSION,
            "status": "PASS",
            "score": None,
            "path": f,
            "last_checked": datetime.date.today().isoformat(),
        } for aid, f in passed]
        try:
            qa_scope.record_evidence(REPO, entries)
        except OSError:
            pass
    print("gate: %d published articles, %d checked, %d evidence-reused, "
          "%d failures" % (len(rows), len(files), reused, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
