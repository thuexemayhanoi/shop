#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic category-index generator (pagination-ready).

Generates category listing pages for PUBLISHED production articles under
cam-nang/<category>/index.html, 50 articles per page (page 2+ at
page-2.html ...). Generated only when a category has published articles —
never commits empty index pages.

BASE PATH: this is a GitHub Pages PROJECT SITE served at
https://thuexemayhanoi.github.io/shop/ — every generated URL (article links,
hub links) is prefixed with the /shop base path from config/site.json.
Forbidden patterns (must never appear): href="/cam-nang/...", href="/kinhnghiem.html".

The page skeleton is deliberately minimal but structured to be compatible
with the existing site design system: a <main> content area plus empty
<header>/<footer> mount points where the existing site partials can be
included later, responsive by default, article entries as list "cards".
No production redesign happens here.

Usage:
  python3 scripts/generate_category_index.py --check   # summary only
  python3 scripts/generate_category_index.py          # write pages
"""
import argparse
import html
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib

PER_PAGE = 50

CAT_DIR = {
    "Kinh nghiệm": "kinh-nghiem",
    "An toàn": "an-toan",
    "Xe máy": "xe-may",
    "Du lịch": "du-lich",
    "Cung đường": "cung-duong",
    "Hỏi đáp": "hoi-dap",
}


def published_by_category(matrix):
    out = {}
    for r in matrix:
        if lib.is_sample_row(r):
            continue
        if (r.get("status") or "").strip() != "PUBLISHED":
            continue
        out.setdefault(r.get("category"), []).append(r)
    for c in out:
        out[c].sort(key=lambda r: r.get("article_id") or "")
    return out


def render_page(cat, rows, page, total_pages, hub, baseurl="/shop"):
    """Render one category index page. All links are prefixed with the
    GitHub Pages base path (default /shop from config/site.json)."""
    base = baseurl.rstrip("/")
    items = "".join(
        '<li class="article-card"><a href="%s/%s">%s</a></li>'
        % (base, r["output_path"].lstrip("/"),
           html.escape(r.get("working_title") or r["slug"]))
        for r in rows)
    nav = ""
    if total_pages > 1:
        parts = []
        if page > 1:
            prev = "index.html" if page == 2 else "page-%d.html" % (page - 1)
            parts.append('<a rel="prev" href="%s">Trước</a>' % prev)
        parts.append("<span>%d / %d</span>" % (page, total_pages))
        if page < total_pages:
            parts.append('<a rel="next" href="page-%d.html">Sau</a>' % (page + 1))
        nav = '<nav class="pagination" aria-label="Phân trang">%s</nav>' % " ".join(parts)
    return (
        "<!DOCTYPE html>\n<html lang=\"vi\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>%s — Mr Tú Motorbike Rental</title>\n"
        "<meta name=\"description\" content=\"Danh mục bài viết %s về thuê xe máy Hà Nội.\">\n"
        "</head>\n<body>\n"
        "<header><!-- site header partial mount point --></header>\n"
        "<main class=\"category-index\">\n<h1>%s</h1>\n"
        "<nav class=\"breadcrumbs\" aria-label=\"Breadcrumb\">"
        "<a href=\"%s/\">Trang chủ</a> › <span>%s</span></nav>\n"
        "<p><a href=\"%s/%s\">%s</a></p>\n"
        "<ul class=\"article-list\">\n%s</ul>\n%s\n</main>\n"
        "<footer><!-- site footer partial mount point --></footer>\n"
        "</body>\n</html>\n"
        % (html.escape(cat), html.escape(cat), html.escape(cat),
           base, html.escape(cat),
           base, hub, html.escape("Về trang chủ đề"),
           items, nav))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="summary only, no writes")
    args = ap.parse_args()
    try:
        matrix = lib.load_matrix()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return 4
    baseurl = site["baseurl"]

    by_cat = published_by_category(matrix)
    total = sum(len(v) for v in by_cat.values())
    if args.check:
        for cat, rows in sorted(by_cat.items()):
            print("%s: %d published -> %d page(s) of %d"
                  % (cat, len(rows), (len(rows) + PER_PAGE - 1) // PER_PAGE, PER_PAGE))
        print("total published: %d" % total)
        return 0

    written = 0
    for cat, rows in sorted(by_cat.items()):
        if cat not in CAT_DIR:
            continue
        d = lib.repo_path("cam-nang", CAT_DIR[cat])
        os.makedirs(d, exist_ok=True)
        total_pages = (len(rows) + PER_PAGE - 1) // PER_PAGE
        hub = lib.CATEGORIES.get(cat, "index.html")
        for page in range(1, total_pages + 1):
            chunk = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
            fname = "index.html" if page == 1 else "page-%d.html" % page
            with io.open(os.path.join(d, fname), "w", encoding="utf-8") as f:
                f.write(render_page(cat, chunk, page, total_pages, hub, baseurl))
            written += 1
    print("category index pages written: %d (%d published articles, %d per page, "
          "base path %s)" % (written, total, PER_PAGE, baseurl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
