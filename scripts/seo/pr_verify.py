#!/usr/bin/env python3
"""PR Verifier: verifies the EXACT candidate tree before merge.

Pipeline on the current checkout (which MUST be the PR candidate tree):
  1. run the SEO audit (strict)
  2. generate the fix matrix
  3. run the regression guard against the accepted baseline
  4. run the safe-fix dry-run and assert no factory-owned file is touched
  5. verify factory non-interference: matrix/batch/draft state is byte-identical
     to the merge-base (drift check done by the caller via git)

Exit 0 only when the candidate tree introduces no new P0/P1 and no
regression. Never merge because local files "looked fine" — this script is
the machine check of the exact tree it runs in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import seo_audit  # noqa: E402
import seo_fix_matrix  # noqa: E402
import seo_regression  # noqa: E402


def main(argv=None):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    failures = []

    print("== 1. SEO audit (strict) ==")
    report = seo_audit.run_audit(root)
    p0, p1 = report["summary"]["P0"], report["summary"]["P1"]
    print(f"P0={p0} P1={p1}")
    out = os.path.join(root, "reports", "seo", "audit.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if p0 or p1:
        failures.append(f"strict SEO audit failed: P0={p0} P1={p1}")

    print("== 2. Fix matrix ==")
    seo_fix_matrix.main(["--root", root])

    print("== 3. Regression guard ==")
    rc = seo_regression.main(["--root", root])
    if rc != 0:
        failures.append(f"regression guard exit {rc}")

    print("== 4. Safe-fix non-interference (dry-run) ==")
    import safe_fix
    before = _snapshot_factory(root)
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "seo", "safe_fix.py"),
                        "--root", root], capture_output=True, text=True)
    after = _snapshot_factory(root)
    if before != after:
        failures.append("safe_fix dry-run mutated factory state")
    print("factory state unchanged in dry-run:", before == after)

    print("== 5. Result ==")
    if failures:
        for x in failures:
            print("FAIL:", x)
        return 1
    print("PR VERIFIER: GREEN — candidate tree passes audit + regression, "
          "no factory interference.")
    return 0


def _snapshot_factory(root):
    import hashlib
    files = ["data/content-matrix.csv", "reports/batches/factory-progress.json"]
    snap = {}
    for rel in files:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            snap[rel] = hashlib.md5(open(p, "rb").read()).hexdigest()
        else:
            snap[rel] = None
    lockdir = os.path.join(root, "data", "batches")
    snap["_batches_listing"] = sorted(os.listdir(lockdir)) if os.path.isdir(lockdir) else []
    return snap


if __name__ == "__main__":
    sys.exit(main())
