#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic cannibalization checker.

Compares the candidate article against:
  - config/seo-ownership.json  (protected commercial intents)
  - data/content-matrix.csv     (duplicate primary keywords / similar titles)
  - data/articles/*.html       (existing article titles, where present)

Similarity is deterministic only (normalized tokens, Jaccard, SequenceMatcher,
exact phrase overlap). Fuzzy similarity never auto-fails; it emits warnings
and review flags.

Usage: python3 scripts/check_cannibalization.py path/to/article.html [--json]
Exit codes: 0 = no conflict, 2 = review needed, 3 = conflict (FAIL), 4 = error.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("article")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        ownership = lib.load_ownership()
        matrix = lib.load_matrix()
        facts = lib.load_business_facts()
        article = lib.Article(os.path.abspath(args.article))
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR
    except ValueError as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR

    failures, warnings, review_flags = lib.check_cannibalization(
        article, ownership, matrix, facts)

    result = {
        "article": os.path.abspath(args.article),
        "slug": article.slug,
        "candidate": ((lib.find_matrix_row(article, matrix) or {}).get("primary_keyword")
                      or (article.h1s[0] if article.h1s else article.title)),
        "failures": failures,
        "warnings": warnings,
        "review_flags": review_flags,
        "status": "FAIL" if failures else ("REVIEW" if (warnings or review_flags) else "PASS"),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("article: %s" % args.article)
        if failures:
            print("CONFLICTS (FAIL):")
            for f in failures:
                print("  ! %s" % f)
        if warnings:
            print("warnings:")
            for w in warnings:
                print("  ? %s" % w)
        if review_flags:
            print("review flags:")
            for r in review_flags:
                print("  ? %s" % r)
        if not (failures or warnings or review_flags):
            print("no cannibalization conflicts")
    if failures:
        return lib.EXIT_FAIL
    if warnings or review_flags:
        return lib.EXIT_REVIEW
    return lib.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
