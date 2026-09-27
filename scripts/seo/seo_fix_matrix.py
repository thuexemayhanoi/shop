#!/usr/bin/env python3
"""Fix Matrix generator: turns reports/seo/audit.json into
reports/seo/fix-matrix.json and reports/seo/fix-matrix.md.

Findings are already deduplicated by root cause (one row per rule with the
full affected-URL list). READ-ONLY with respect to factory state.

Execution status for every row is REVIEW by default; only rows whose
safe_to_auto_fix is true may be executed by scripts/seo/safe_fix.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

DEP = {
    "canonical.missing": "none",
    "canonical.wrong": "route map verified",
    "canonical.shop-shop": "none",
    "canonical.parent-dotslash": "none",
    "canonical.relative": "none",
    "canonical.cross-page": "owner decision (consolidation intent)",
    "sitemap.missing-pages": "publish transaction completed",
    "sitemap.ghost-urls": "none",
    "sitemap.duplicates": "none",
    "robots.noindex": "confirm intent",
    "h1.wrong-count": "article shell template",
    "title.missing": "none",
    "title.duplicate": "content review",
    "description.missing": "article front matter",
    "description.duplicate": "content review",
    "schema.jsonld-invalid": "none",
    "schema.article-missing": "article shell template",
    "schema.breadcrumb-missing": "article shell template",
    "schema.stale-url": "route map verified",
    "links.broken-internal": "route map verified",
    "links.broken-fragment": "target page ids",
    "links.orphans": "hub/listing generation",
    "deploy.operational-unexcluded": "none",
    "deploy.legacy-scripts-exposed": "owner decision (already ACCEPTED in docs)",
}

BEST_TOOL = {
    "sitemap.missing-pages": "scripts/generate_sitemap.py",
    "sitemap.ghost-urls": "scripts/generate_sitemap.py",
    "sitemap.duplicates": "scripts/generate_sitemap.py",
    "links.orphans": "scripts/generate_category_pages.py",
    "h1.wrong-count": "scripts/apply_article_shell.py",
    "schema.article-missing": "scripts/apply_article_shell.py",
    "schema.breadcrumb-missing": "scripts/apply_article_shell.py",
    "schema.jsonld-invalid": "scripts/apply_article_shell.py",
    "canonical.shop-shop": "scripts/seo/safe_fix.py",
    "canonical.relative": "scripts/seo/safe_fix.py",
    "deploy.operational-unexcluded": "scripts/seo/safe_fix.py",
    "deploy.legacy-scripts-exposed": "scripts/seo/safe_fix.py",
}


def build_matrix(audit):
    rows = []
    for i, f in enumerate(audit["findings"], 1):
        rule = f["rule"]
        rows.append({
            "id": f"SEO-{i:03d}",
            "severity": f["severity"],
            "rule": rule,
            "dependency": DEP.get(rule, "none"),
            "scope": f["category"],
            "issue": f["root_cause"],
            "root_cause": f["root_cause"],
            "evidence": f["evidence"],
            "affected_urls": f["affected"],
            "affected_count": f["affected_count"],
            "safe_to_auto_fix": f["safe_to_auto_fix"],
            "recommended_fix": f["recommended_fix"],
            "best_tool": BEST_TOOL.get(rule, "manual review"),
            "execution_status": "REVIEW",
            "risk_level": f["risk_level"],
            "seo_impact": f["seo_impact"] or ("meaningful" if f["severity"] in ("P0", "P1") else "minor"),
            "indexing_impact": f["indexing_impact"] or ("direct" if f["severity"] in ("P0", "P1") else "indirect"),
            "local_seo_impact": "none" if f["category"] not in ("structured_data", "deploy_hygiene") else "possible",
            "geo_ai_search_impact": "possible" if f["category"] in ("structured_data", "canonical_sitemap") else "none",
            "before_state": f["affected"][:3],
            "after_state": None,
            "verification_evidence": None,
            "rollback_requirement": "git revert of the fixing commit",
            "verified": "NOT VERIFIED",
        })
    return rows


def to_markdown(rows, scores):
    lines = ["# SEO Fix Matrix", "",
             "Generated from reports/seo/audit.json. One row per root cause.",
             "Execution status REVIEW unless safe_to_auto_fix is true AND the",
             "fix was applied by scripts/seo/safe_fix.py on an isolated branch.",
             "", "## Category scores", ""]
    for cat, sc in scores.items():
        lines.append(f"- {cat}: {sc}/100")
    lines += ["", "| ID | Sev | Rule | Affected | Root cause | Status |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['severity']} | {r['rule']} | {r['affected_count']} |"
                     f" {r['root_cause'][:80]} | {r['execution_status']} |")
    lines.append("")
    for r in rows:
        lines += [f"## {r['id']} — {r['rule']} ({r['severity']})",
                  f"- Root cause: {r['root_cause']}",
                  f"- Evidence: {r['evidence']}",
                  f"- Affected: {r['affected_count']} URL(s)",
                  f"- Safe to auto-fix: {r['safe_to_auto_fix']}",
                  f"- Recommended fix: {r['recommended_fix']}",
                  f"- Best tool: {r['best_tool']}",
                  f"- Verified: {r['verified']}", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--audit", default=None)
    args = ap.parse_args(argv)
    audit_path = args.audit or os.path.join(args.root, "reports", "seo", "audit.json")
    with open(audit_path, encoding="utf-8") as f:
        audit = json.load(f)
    rows = build_matrix(audit)
    outdir = os.path.join(args.root, "reports", "seo")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "fix-matrix.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_from": audit_path, "rows": rows,
                   "counts": {"safe_auto_fix": sum(1 for r in rows if r["safe_to_auto_fix"]),
                              "review_only": sum(1 for r in rows if not r["safe_to_auto_fix"]),
                              "total": len(rows)}}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "fix-matrix.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(rows, audit.get("scores", {})))
    print(json.dumps({"rows": len(rows),
                      "safe_auto_fix": sum(1 for r in rows if r["safe_to_auto_fix"]),
                      "review_only": sum(1 for r in rows if not r["safe_to_auto_fix"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
