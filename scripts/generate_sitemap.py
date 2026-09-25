#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic sitemap generator for the content factory.

Merges the CURRENT public sitemap.xml with production articles that have
status PUBLISHED in data/content-matrix.csv.

Rules:
  - every URL currently in sitemap.xml is preserved (commercial pages never drop)
  - only PUBLISHED production articles are added
  - SAMPLE fixtures and PLANNED/WRITING/REVIEW/FAIL/BLOCKED rows are never added
  - no duplicate URLs; valid XML output

Usage:
  python3 scripts/generate_sitemap.py            # write sitemap.xml if changed
  python3 scripts/generate_sitemap.py --check    # exit 1 if sitemap is stale
"""
import argparse
import datetime
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib


def current_urls(sitemap_path):
    urls = []
    if os.path.exists(sitemap_path):
        tree = ET.parse(sitemap_path)
        ns = ""
        m = re.match(r"\{(.+)\}", tree.getroot().tag)
        if m:
            ns = m.group(1)
        for loc in tree.getroot().iter("{%s}loc" % ns if ns else "loc"):
            urls.append((loc.text or "").strip())
    return urls


def published_article_urls(matrix, site_url_base=None):
    """Absolute public URLs of PUBLISHED production articles only.

    URL = site_url (from config/site.json) + "/" + output_path, e.g.
    https://thuexemayhanoi.github.io/shop/cam-nang/an-toan/at-0001-....html
    SAMPLE rows and any non-PUBLISHED status (PLANNED, WRITING, QA, REVIEW,
    FAIL, BLOCKED, PASS-without-commit) are never included.
    """
    urls = []
    for r in matrix:
        if lib.is_sample_row(r):
            continue
        if (r.get("status") or "").strip() != "PUBLISHED":
            continue
        path = (r.get("output_path") or "").strip().lstrip("/")
        if not path:
            continue
        if site_url_base:
            urls.append(site_url_base.rstrip("/") + "/" + path)
        else:
            urls.append("/" + path)
    return urls


def build_urlset(base_urls):
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
    root = ET.Element("{http://www.sitemaps.org/schemas/sitemap/0.9}urlset")
    seen = set()
    for u in base_urls:
        norm = u.rstrip("/") if not u.endswith(".html") else u
        if norm in seen:
            continue
        seen.add(norm)
        el = ET.SubElement(root, "{http://www.sitemaps.org/schemas/sitemap/0.9}url")
        loc = ET.SubElement(el, "{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        loc.text = u
        lm = ET.SubElement(el, "{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod")
        lm.text = datetime.date.today().isoformat()
    return ET.ElementTree(root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="only verify sitemap freshness (no write)")
    args = ap.parse_args()
    sitemap_path = lib.repo_path("sitemap.xml")
    try:
        matrix = lib.load_matrix()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return 4

    existing = current_urls(sitemap_path)
    # GitHub Pages project site: article URLs come from config/site.json
    # site_url (https://thuexemayhanoi.github.io/shop) — NEVER the bare
    # host origin, which would drop the /shop base path.
    factory_prefix = site["site_url"].rstrip("/") + "/cam-nang/"
    # STALE URL ACCUMULATION FIX: factory article URLs are REBUILT from the
    # CURRENT matrix on every generation — never preserved from the old
    # sitemap. Only non-factory (legacy/commercial) URLs are retained.
    legacy = [u for u in existing if not u.startswith(factory_prefix)]
    published = published_article_urls(matrix, site["site_url"])

    wanted = legacy[:]
    for p in published:
        if p not in wanted:
            wanted.append(p)

    new_count = len(wanted) - len(legacy)
    if args.check:
        cur = current_urls(sitemap_path)
        missing = [u for u in wanted if u not in cur]
        stale = [u for u in cur if u.startswith(factory_prefix) and u not in wanted]
        if missing or stale:
            print("STALE: %d missing, %d stale factory URL(s)" % (len(missing), len(stale)))
            return 1
        print("OK: sitemap.xml is up to date (%d URLs, %d published articles)"
              % (len(cur), len(published)))
        return 0

    tree = build_urlset(wanted)
    tmp = sitemap_path + ".tmp"
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    with io.open(tmp, "a", encoding="utf-8") as f:
        f.write("\n")
    os.replace(tmp, sitemap_path)
    print("sitemap.xml: %d legacy URLs kept, %d published articles included "
          "(total %d)" % (len(existing), len(published), len(wanted)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
