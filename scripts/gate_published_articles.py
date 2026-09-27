#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate: every PUBLISHED article must validate and score PASS.

Used by the factory operator (op=apply-article-shell) and safe to run
locally at any time. Exit 0 = all published articles pass
scripts/validate_article.py and scripts/score_article.py.
"""
import csv
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(REPO, "data", "content-matrix.csv"),
              encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    files = sorted(r["output_path"] for r in rows
                   if r["status"] == "PUBLISHED"
                   and not r["article_id"].startswith("SAMPLE")
                   and os.path.isfile(os.path.join(REPO, r["output_path"])))
    bad = 0
    for f in files:
        for tool in ("scripts/validate_article.py",
                     "scripts/score_article.py"):
            p = subprocess.run([sys.executable, tool, f], cwd=REPO,
                               capture_output=True, text=True)
            if p.returncode != 0:
                bad += 1
                print("GATE FAIL", f, p.returncode)
                print(p.stdout[-800:])
    print("gate: %d published articles checked, %d failures"
          % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
