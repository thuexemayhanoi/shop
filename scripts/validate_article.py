#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hard technical validation before scoring.

Usage: python3 scripts/validate_article.py path/to/article.html [--json]
Exit codes: 0 = valid, 1 = hard errors, 4 = tool/config error.
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
        rubric = lib.load_rubric()
        facts = lib.load_business_facts()
        ownership = lib.load_ownership()
        matrix = lib.load_matrix()
        article = lib.Article(os.path.abspath(args.article))
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR
    except ValueError as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR

    errors = lib.validate_article(article, matrix, ownership, facts, rubric)
    result = {
        "article": os.path.abspath(args.article),
        "slug": article.slug,
        "valid": not errors,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("article: %s" % args.article)
        if errors:
            print("INVALID — hard errors:")
            for e in errors:
                print("  ! %s" % e)
        else:
            print("VALID — passed hard technical validation")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
