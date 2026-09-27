#!/usr/bin/env python3
"""Regression Guard: compare current audit metrics against the last accepted
good baseline (reports/seo/baseline.json).

Rules:
  - worse state (metric regression) => fail (exit 1)
  - equal state => pass
  - better state => pass
  - NEVER update the baseline while an unresolved P0/P1 exists (exit 3)
  - baselining is a deliberate action (--update-baseline), never automatic.

READ-ONLY with respect to factory state. Metrics that legitimately grow with
the factory (published_pages, sitemap_url_count) only regress when they
shrink.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HIGHER_IS_OK = {"published_pages", "sitemap_url_count"}


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=repo_root())
    ap.add_argument("--audit", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--update-baseline", action="store_true",
                    help="accept the current audit as the new good baseline")
    args = ap.parse_args(argv)

    audit_path = args.audit or os.path.join(args.root, "reports", "seo", "audit.json")
    baseline_path = args.baseline or os.path.join(args.root, "reports", "seo", "baseline.json")
    audit = load(audit_path)

    if args.update_baseline:
        has_p01 = audit["summary"]["P0"] or audit["summary"]["P1"]
        if has_p01:
            print("REFUSED: cannot baseline while unresolved P0/P1 findings exist. "
                  "Fix the defects first; never baseline a real defect.")
            return 3
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": audit["metrics"],
                       "scores": audit["scores"]}, f, ensure_ascii=False, indent=2)
        print("BASELINE UPDATED")
        return 0

    if not os.path.exists(baseline_path):
        print("NO BASELINE: first run must create one with --update-baseline "
              "(only allowed when no P0/P1 exists).")
        return 2

    base = load(baseline_path)["metrics"]
    cur = audit["metrics"]
    regressions = []
    improvements = []
    for k, v in cur.items():
        b = base.get(k, 0)
        if k in HIGHER_IS_OK:
            if v < b:
                regressions.append(f"{k}: {b} -> {v}")
            elif v > b:
                improvements.append(f"{k}: {b} -> {v}")
        else:
            if v > b:
                regressions.append(f"{k}: {b} -> {v}")
            elif v < b:
                improvements.append(f"{k}: {b} -> {v}")

    print(json.dumps({"regressions": regressions, "improvements": improvements},
                     ensure_ascii=False, indent=2))
    if regressions:
        print("REGRESSION GUARD: FAILED")
        return 1
    print("REGRESSION GUARD: PASS (equal or better state)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
