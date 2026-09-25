#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic category pagination generator.

ARCHITECTURE (bug #3 fix — no duplicate page-1 intent):
- The six ROOT hub pages (kinhnghiem.html, antoan.html, xemay.html,
  dulich.html, cungduong.html, hoidap.html) ARE page 1 of each category.
  This generator NEVER creates cam-nang/<cat>/index.html.
- When a category has MORE than 50 PUBLISHED articles, page 2+ goes to
  cam-nang/<cat>/page-2.html, page-3.html, ... (50 articles per page).
- Page 2+ links back to the root hub (page 1).
- The first 50 published article cards are injected into the ROOT hub via
  clearly delimited, idempotent blocks:
      <!-- ARTICLE-LIST:START -->
      ...generated cards...
      <!-- ARTICLE-LIST:END -->
  Manually authored hub content outside the delimiters is never touched.
  If _includes/generated/ is preferred later, the same block content can be
  moved there without changing this logic.

BASE PATH: links are /shop-prefixed per config/site.json (GitHub Pages
project site).

Usage:
  python3 scripts/generate_category_pages.py --check   # summary only
  python3 scripts/generate_category_pages.py            # write pages + hub blocks
"""
import argparse
import html
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib

PER_PAGE = 50
START = "<!-- ARTICLE-LIST:START -->"
END = "<!-- ARTICLE-LIST:END -->"

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


def card_list(rows, baseurl):
    base = baseurl.rstrip("/")
    return "\n".join(
        '<li class="article-card"><a href="%s/%s">%s</a></li>'
        % (base, r["output_path"].lstrip("/"),
           html.escape(r.get("working_title") or r["slug"]))
        for r in rows)


def hub_block(rows, baseurl, hub, cat, total_published):
    """The generated include-block injected into the root hub page."""
    inner = card_list(rows[:PER_PAGE], baseurl)
    more = ""
    if total_published > PER_PAGE:
        more = ('<p class="article-list-more">Xem thêm: '
                '<a href="%s/cam-nang/%s/page-2.html">trang 2</a></p>'
                % (baseurl, CAT_DIR[cat]))
    return "%s\n<ul class=\"article-list\">\n%s\n</ul>\n%s%s" % (START, inner, more, END)


def inject_hub_block(hub_path, block):
    """Idempotently replace the delimited block in a hub page; leave all
    other manually authored content untouched. Appends the block before
    </main> (or </body>) if no block exists yet."""
    text = io.open(hub_path, encoding="utf-8").read()
    if START in text and END in text:
        pre = text.split(START)[0]
        post = text.split(END, 1)[1]
        return pre + block + post, False
    # no block yet: insert before </main> if present else </body>
    for marker in ("</main>", "</body>"):
        if marker in text:
            i = text.index(marker)
            return text[:i] + block + "\n" + text[i:], True
    return text + "\n" + block + "\n", True


def render_page_n(cat, rows, page, total_pages, hub, baseurl):
    base = baseurl.rstrip("/")
    items = card_list(rows, baseurl)
    parts = []
    if page > 2:
        parts.append('<a rel="prev" href="page-%d.html">Trước</a>' % (page - 1))
    elif page == 2:
        parts.append('<a rel="prev" href="%s/%s">Trang 1</a>' % (base, hub))
    parts.append("<span>%d / %d</span>" % (page, total_pages))
    if page < total_pages:
        parts.append('<a rel="next" href="page-%d.html">Sau</a>' % (page + 1))
    nav = '<nav class="pagination" aria-label="Phân trang">%s</nav>' % " ".join(parts)
    return (
        "<!DOCTYPE html>\n<html lang=\"vi\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>%s — trang %d — Mr Tú Motorbike Rental</title>\n"
        "<meta name=\"description\" content=\"Danh mục bài viết %s, trang %d.\">\n"
        "<link rel=\"canonical\" href=\"%s/cam-nang/%s/page-%d.html\">\n"
        "</head>\n<body>\n"
        "<header><!-- site header partial mount point --></header>\n"
        "<main class=\"category-index\">\n<h1>%s — trang %d</h1>\n"
        "<nav class=\"breadcrumbs\" aria-label=\"Breadcrumb\">"
        "<a href=\"%s/\">Trang chủ</a> › <a href=\"%s/%s\">%s</a> › <span>Trang %d</span></nav>\n"
        "<ul class=\"article-list\">\n%s</ul>\n%s\n</main>\n"
        "<footer><!-- site footer partial mount point --></footer>\n"
        "</body>\n</html>\n"
        % (html.escape(cat), page, html.escape(cat), page,
           base, CAT_DIR[cat], page,
           html.escape(cat), page,
           base, base, hub, html.escape(cat), page,
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
    for cat, rows in by_cat.items():
        pages = (len(rows) + PER_PAGE - 1) // PER_PAGE
        print("%s: %d published -> root hub page 1 (%d cards) + %d extra page(s)"
              % (cat, len(rows), min(len(rows), PER_PAGE), max(pages - 1, 0)))
    if args.check:
        return 0

    written = 0
    for cat, rows in sorted(by_cat.items()):
        if cat not in CAT_DIR:
            continue
        hub = lib.CATEGORIES[cat]
        # 1) inject first-50 block into the ROOT hub (page 1)
        hub_path = lib.repo_path(hub)
        if os.path.exists(hub_path):
            block = hub_block(rows, baseurl, hub, cat, len(rows))
            new_text, appended = inject_hub_block(hub_path, block)
            with io.open(hub_path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print("hub %s: article-list block %s (%d cards)"
                  % (hub, "appended" if appended else "updated", min(len(rows), PER_PAGE)))
        # 2) page 2+ files
        total_pages = (len(rows) + PER_PAGE - 1) // PER_PAGE
        for page in range(2, total_pages + 1):
            chunk = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
            d = lib.repo_path("cam-nang", CAT_DIR[cat])
            os.makedirs(d, exist_ok=True)
            with io.open(os.path.join(d, "page-%d.html" % page), "w",
                         encoding="utf-8") as f:
                f.write(render_page_n(cat, chunk, page, total_pages, hub, baseurl))
            written += 1
        # 3) remove stale page files beyond current pagination
        d = lib.repo_path("cam-nang", CAT_DIR[cat])
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith("page-") and fn.endswith(".html"):
                    try:
                        n = int(fn[5:-5])
                    except ValueError:
                        continue
                    if n < 2 or n > total_pages:
                        os.remove(os.path.join(d, fn))
    print("category pagination pages written: %d (never cam-nang/<cat>/index.html)"
          % written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
