#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full cannibalization sweep — every published article, in one process.

Used ONLY by the heavy FULL audit workflow
(.github/workflows/factory-publish-verify.yml: manual dispatch, batch
terminal, engine change, final 2000-article audit). The per-pair loop and
the FAST content gate already run the SAME canonical checker
(scripts/check_cannibalization.py -> lib.check_cannibalization) on each
changed candidate against the full corpus; this sweep is the periodic
whole-corpus re-check (belt and braces, deterministic, stdlib only).

In-process (no subprocess per article): the config/ownership/matrix
corpus is loaded once, then every PUBLISHED production article is
checked with the exact same lib.check_cannibalization call the
per-candidate CLI tool uses — no drift, no weakened thresholds.

Exit codes (same contract as check_cannibalization.py):
  0 = clean, or only fuzzy-similarity REVIEW warnings (never auto-fail)
  3 = at least one hard conflict (FAIL)
  4 = error (bad config, unreadable corpus)
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib  # noqa: E402

REPO = lib.ROOT


def published_article_paths(repo_root=None):
    root = repo_root or REPO
    paths = []
    with open(os.path.join(root, "data", "content-matrix.csv"),
              encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").strip() != "PUBLISHED":
                continue
            aid = (r.get("article_id") or "").strip()
            if aid.startswith("SAMPLE"):
                continue
            op = (r.get("output_path") or "").strip()
            if op and os.path.isfile(os.path.join(root, op)):
                paths.append((aid, os.path.join(root, op)))
    return paths


def main():
    try:
        ownership = lib.load_ownership()
        matrix = lib.load_matrix()
        facts = lib.load_business_facts()
    except (lib.ConfigError, ValueError) as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR

    rows = published_article_paths()
    print("full cannibalization sweep: %d published articles" % len(rows))
    conflicts = 0
    errors = 0
    for aid, path in rows:
        try:
            article = lib.Article(path)
        except Exception as e:  # unreadable article: error, never skip
            print("ERROR reading %s (%s): %s" % (aid, path, e))
            errors += 1
            continue
        failures, _warnings, _flags = lib.check_cannibalization(
            article, ownership, matrix, facts)
        if failures:
            conflicts += 1
            print("CONFLICT %s (%s):" % (aid, path))
            for f in failures:
                print("  ! %s" % f)
    print("sweep done: %d articles, %d conflicts, %d errors"
          % (len(rows), conflicts, errors))
    if errors:
        return lib.EXIT_ERROR
    if conflicts:
        return lib.EXIT_FAIL
    return lib.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
