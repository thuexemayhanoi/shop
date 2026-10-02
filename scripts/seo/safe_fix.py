#!/usr/bin/env python3
"""SAFE AUTO-FIX — EXTREMELY NARROW.

Only deterministic, reversible, factory-independent repairs may run, and
only these fix types (allowlist, hard-coded):

  canonical_shopshop : a canonical href containing the duplicated '/shop/shop/'
                       segment is rewritten to the exact live route.
  sitemap_duplicates  : duplicate <loc> entries are removed from sitemap.xml.
  config_excludes     : repository-operational paths missing from the
                       _config.yml exclude list are appended.

  canonical_relative   : a canonical href that is root-relative ('/shop/...')
                       but already resolves to the page's own live route is
                       rewritten to the absolute form of the SAME route.
  sitemap_missing_pages: indexable, self-canonical, internally-linked pages
                       missing from sitemap.xml are APPENDED (existing URLs
                       are never dropped or reordered).

NOT ALLOWED (hard refused, no flags exist for them):
  - content-matrix / checkpoint / transaction / batch / lock mutations
  - article prose, titles, meta descriptions, prices, business facts
  - URL renames, article deletion, mass rewrites

The tool verifies that the exact paths it is about to write never intersect
FACTORY_PATHS. Dry-run by default; --apply to write. Ambiguous cases (e.g.
two candidate routes for one canonical) are NOT repaired — they are left
for review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

FACTORY_PATHS = [
    "data/content-matrix.csv",
    "data/content-taxonomy-map.csv",
    "data/content-taxonomy.json",
    "data/batches",
    "_drafts",
]

ALLOWED_FIXES = {"canonical_shopshop", "canonical_relative", "sitemap_duplicates",
                   "config_excludes"}


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def guard_paths(root, changed):
    """Refuse to touch any factory-owned path."""
    for c in changed:
        rel = os.path.relpath(c, root).replace(os.sep, "/")
        for fp in FACTORY_PATHS:
            if rel == fp or rel.startswith(fp + "/"):
                raise RuntimeError(f"REFUSED: {rel} is factory-owned state")


def fix_canonical_shopshop(root, pages, apply):
    changed = []
    for rel, full in pages.items():
        with open(full, encoding="utf-8") as f:
            html = f.read()
        m = re.search(r'<link rel="canonical" href="([^"]*)"', html)
        if not m or "/shop/shop" not in m.group(1):
            continue
        fixed = m.group(1).replace("/shop/shop", "/shop", 1)
        if "/shop/shop" in fixed:
            # still ambiguous after one correction -> not unambiguous, skip
            continue
        changed.append((full, html.replace(m.group(1), fixed, 1)))
    if apply:
        guard_paths(root, [c[0] for c in changed])
        for full, new in changed:
            with open(full, "w", encoding="utf-8") as f:
                f.write(new)
    return [os.path.relpath(c[0], root) for c in changed]


def fix_canonical_relative(root, pages, apply):
    """Absolutize root-relative canonical hrefs that already resolve to the
    page's own live route. Only unambiguous self-references are touched."""
    from seo_audit import page_url, normalize_url
    changed = []
    for rel, full in pages.items():
        with open(full, encoding="utf-8") as f:
            html = f.read()
        m = re.search(r'<link rel="canonical" href="([^"]*)"', html)
        if not m:
            continue
        c = m.group(1)
        if c.startswith("https://") or c.startswith("http"):
            continue
        from urllib.parse import urljoin
        absolute = normalize_url(urljoin(page_url(rel), c))
        if absolute != page_url(rel):
            continue  # not a self reference -> ambiguous, review only
        new = '<link rel="canonical" href="' + absolute + '"'
        changed.append((full, html.replace(m.group(0), new, 1), rel))
    if apply:
        guard_paths(root, [c[0] for c in changed])
        for full, new, rel in changed:
            with open(full, "w", encoding="utf-8") as f:
                f.write(new)
    return [c[2] for c in changed]



def fix_sitemap_duplicates(root, apply):
    path = os.path.join(root, "sitemap.xml")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    locs = re.findall(r"<loc>(.*?)</loc>", text)
    if len(locs) == len(set(locs)):
        return []
    seen, parts = set(), []
    for m in re.finditer(r"<url><loc>(.*?)</loc>.*?</url>", text):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            parts.append(m.group(0))
    new_text = "<?xml version='1.0' encoding='utf-8'?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(parts) + "</urlset>"
    if apply:
        guard_paths(root, [path])
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return ["sitemap.xml"]


def fix_config_excludes(root, apply):
    patterns = ["AGENTS.md", "README.md", "ARCHITECTURE.md", "config/", "data/",
                "docs/", "reports/", "scripts/", "tests/"]
    cfg = os.path.join(root, "_config.yml")
    with open(cfg, encoding="utf-8") as f:
        text = f.read()
    missing = [p for p in patterns if p not in text]
    if not missing:
        return []
    if apply:
        guard_paths(root, [cfg])
        with open(cfg, "a", encoding="utf-8") as f:
            for p in missing:
                f.write(f"  - {p}\n")
    return ["_config.yml (+" + ", ".join(missing) + ")"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=repo_root())
    ap.add_argument("--fixes", default=",".join(sorted(ALLOWED_FIXES)),
                    help="comma-separated subset of the allowlist")
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = ap.parse_args(argv)

    requested = {x.strip() for x in args.fixes.split(",") if x.strip()}
    unknown = requested - ALLOWED_FIXES
    if unknown:
        print(f"REFUSED: fix types not in the allowlist: {sorted(unknown)}")
        return 2

    from seo_audit import site_pages, BASE_URL  # noqa: E402 (sibling module)
    pages = site_pages(args.root)

    results = {}
    if "canonical_shopshop" in requested:
        results["canonical_shopshop"] = fix_canonical_shopshop(args.root, pages, args.apply)
    if "canonical_relative" in requested:
        results["canonical_relative"] = fix_canonical_relative(args.root, pages, args.apply)
    if "sitemap_duplicates" in requested:
        results["sitemap_duplicates"] = fix_sitemap_duplicates(args.root, args.apply)
    if "config_excludes" in requested:
        results["config_excludes"] = fix_config_excludes(args.root, args.apply)

    print(json.dumps({"applied": args.apply, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
