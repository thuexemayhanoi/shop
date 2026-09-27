#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic article-shell migration for /shop articles.

Applies the ONE shared article design system (assets/css/article.css) to
existing article files without touching editorial content:

  - wraps the prose in the shared shell
    (<main class="article-main"><article class="article">…</article>…)
  - adds the article header: breadcrumb (Trang chủ -> Cẩm nang -> Parent ->
    Child -> Article), taxonomy kicker, H1, publication date, real author
  - adds a "Mục lục" <details> TOC when the article has >= 4 H2 sections
  - adds real heading anchors (id="sec-N") for TOC links
  - wraps every <table> in .article-table-wrap (controlled mobile scroll)
  - adds ONE restrained CTA after the article (trusted business facts only)
  - adds "Bài viết liên quan" (same child topic, then same parent;
    PUBLISHED articles only, deterministic order, no self-link, no dups)
  - adds compact prev/next navigation within the same child topic
  - upgrades BreadcrumbList JSON-LD to match the visible breadcrumb
  - links assets/css/article.css in <head>

NEVER changes: prose text, H1/H2/H3 text, links, canonical URL, Article
schema, publication date, article ID, URL, taxonomy mapping, matrix state.

Idempotent: files already carrying the shell (marker class "article-main")
are reported as already-migrated and left untouched.

Usage:
  python3 scripts/apply_article_shell.py                      # all PUBLISHED
  python3 scripts/apply_article_shell.py path/to/article.html # specific files
  python3 scripts/apply_article_shell.py --drafts             # also _drafts/
"""
import csv
import datetime
import html as html_mod
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

SITE_URL = "https://thuexemayhanoi.github.io/shop"
BASE = "/shop"
CAM_NANG_HUB = BASE + "/cam-nang/chu-de/"
ARTICLE_CSS = BASE + "/assets/css/article.css"
TOC_MIN_H2 = 4
RELATED_MAX = 4

# --------------------------------------------------------------------- data

def load_rows():
    with open(os.path.join(REPO, "data", "content-matrix.csv"),
              encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)]


def load_tax():
    tax = json.load(open(os.path.join(REPO, "data", "content-taxonomy.json"),
                        encoding="utf-8"))
    parents = {p["parent_id"]: p for p in tax["parents"]}
    children = {}
    for p in tax["parents"]:
        for c in p["children"]:
            children[c["child_id"]] = dict(c, parent_id=p["parent_id"],
                                           parent_title=p["parent_title"],
                                           parent_hub=p["parent_hub"])
    return parents, children


def load_map():
    with open(os.path.join(REPO, "data", "content-taxonomy-map.csv"),
              encoding="utf-8") as f:
        return {r["article_id"]: r for r in csv.DictReader(f)}


# ------------------------------------------------------------------ helpers

def strip_prefix(path):
    return path[len(BASE):] if path.startswith(BASE) else path


def file_exists(path):
    p = strip_prefix(path).lstrip("/")
    return os.path.isfile(os.path.join(REPO, p))


def display_date(iso):
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return d.strftime("%d/%m/%Y")
    except Exception:
        return iso[:10]


def esc(s):
    return html_mod.escape(s, quote=True)


def article_id_for(path, row=None):
    if row is not None:
        return row["article_id"]
    base = os.path.basename(path)
    m = re.match(r"([a-z]{2})-(\d{4})-", base)
    if not m:
        return None
    return "%s-%s" % (m.group(1).upper(), m.group(2))


# ------------------------------------------------------------- shell pieces

def breadcrumb_html(parent, child, title):
    parts = [
        '<a href="%s/index.html">Trang chủ</a>' % BASE,
        '<span class="bc-sep" aria-hidden="true">›</span>',
        '<a href="%s">Cẩm nang</a>' % CAM_NANG_HUB,
        '<span class="bc-sep" aria-hidden="true">›</span>',
        '<a href="%s">%s</a>' % (parent["parent_hub"],
                                 esc(parent["parent_title"])),
        '<span class="bc-sep" aria-hidden="true">›</span>',
    ]
    if child:
        parts.append('<a href="%s">%s</a>' % (child["child_hub_url"],
                                              esc(child["child_title"])))
        parts.append('<span class="bc-sep" aria-hidden="true">›</span>')
    short = title if len(title) <= 70 else title[:67].rstrip() + "…"
    parts.append('<span aria-current="page">%s</span>' % esc(short))
    return ('<nav class="article-breadcrumb" aria-label="Breadcrumb">%s'
            "</nav>" % "".join(parts))


def breadcrumb_schema(parent, child, canonical, title=None):
    items = [
        ("Trang chủ", SITE_URL + "/"),
        ("Cẩm nang", SITE_URL + "/cam-nang/chu-de/"),
        (parent["parent_title"], SITE_URL + strip_prefix(parent["parent_hub"])),
    ]
    if child:
        items.append((child["child_title"],
                      SITE_URL + strip_prefix(child["child_hub_url"])))
    # final item: human-readable article title, NOT the canonical URL
    final_name = (title or "").strip() or canonical
    items.append((final_name, canonical))
    elements = ",".join(
        json.dumps({"@type": "ListItem", "position": i + 1, "name": n,
                    "item": u}, ensure_ascii=False)
        for i, (n, u) in enumerate(items))
    return ('{"@context":"https://schema.org","@type":"BreadcrumbList",'
            '"itemListElement":[%s]}' % elements)


def toc_html(h2s):
    if len(h2s) < TOC_MIN_H2:
        return ""
    lis = "".join('<li><a href="#sec-%d">%s</a></li>'
                  % (i + 1, t) for i, t in enumerate(h2s))
    return ('<nav class="article-toc" aria-label="Mục lục">'
            '<details><summary>Mục lục</summary><ol>%s</ol></details></nav>' % lis)


def wrap_tables(prose):
    return re.sub(r"(<table\b)", r'<div class="article-table-wrap">\1',
                  prose, flags=re.I) if "<table" in prose else prose


def _close_table_wrap(prose):
    # pair each opened wrap div with its table close
    return re.sub(r"(</table\s*>)", r"\1</div>", prose, flags=re.I)


def cta_html():
    return (
        '<section class="article-cta" aria-label="Liên hệ đặt xe">'
        '<div class="article-cta-inner">'
        "<p>Bạn đang tìm xe máy phù hợp cho chuyến đi của mình?</p>"
        '<a href="%s/banggia.html">Xem bảng giá thuê xe</a>'
        "</div></section>" % BASE)


def related_html(row, published_same_child, published_same_parent,
                 parents, children):
    m = load_map() if not hasattr(related_html, "_map") else related_html._map
    picks, seen = [], set()
    for other in published_same_child:
        if other["article_id"] != row["article_id"]:
            picks.append(other)
    if len(picks) < RELATED_MAX:
        for other in published_same_parent:
            if (other["article_id"] != row["article_id"]
                    and other["article_id"] not in
                    {p["article_id"] for p in picks}):
                picks.append(other)
    picks = picks[:RELATED_MAX]
    if not picks:
        return ""
    cards = []
    for other in picks:
        tmap = m.get(other["article_id"])
        child = children.get(tmap["child_id"]) if tmap else None
        ptitle = (parents.get(tmap["parent_id"]) or {}).get("parent_title", "") \
            if tmap else ""
        topic = ptitle
        if child:
            topic = ptitle + " · " + child["child_title"] if ptitle \
                else child["child_title"]
        cards.append(
            "<li><a href=\"%s/%s\"><span class=\"rel-title\">%s</span>"
            '<span class="rel-topic">%s</span></a></li>'
            % (BASE, other["output_path"], esc(other["working_title"]),
               esc(topic)))
    return ('<section class="article-related" aria-labelledby="rel-h">'
            '<h2 class="article-related-title" id="rel-h">Bài viết liên quan'
            "</h2><ul class=\"article-related-list\">%s</ul></section>"
            % "".join(cards))


def pn_html(row, same_child_sorted):
    ids = [r["article_id"] for r in same_child_sorted]
    if row["article_id"] not in ids:
        return ""
    i = ids.index(row["article_id"])
    prev = same_child_sorted[i - 1] if i > 0 else None
    nxt = same_child_sorted[i + 1] if i + 1 < len(same_child_sorted) else None
    if not prev and not nxt:
        return ""
    lis = []
    if prev:
        lis.append('<li><a href="%s/%s"><span class="pn-label">Bài trước'
                   "</span>%s</a></li>"
                   % (BASE, prev["output_path"], esc(prev["working_title"])))
    if nxt:
        lis.append('<li><a class="pn-next" href="%s/%s"><span class="pn-label">'
                   "Bài sau</span>%s</a></li>"
                   % (BASE, nxt["output_path"], esc(nxt["working_title"])))
    return ('<nav class="article-pn" aria-label="Điều hướng bài viết">'
            '<ul class="article-pn-list">%s</ul></nav>' % "".join(lis))


# ------------------------------------------------------------------- core

def migrate(path, rows_by_id, published_by_child, published_by_parent,
            parents, children, tax_map):
    raw = open(path, encoding="utf-8").read()
    if "article-main" in raw:
        return "already-migrated"

    aid = article_id_for(path)
    row = rows_by_id.get(aid)
    if row is None:
        return "skip: article not in matrix"
    tmap = tax_map.get(aid)
    if tmap is None:
        return "skip: no taxonomy mapping"
    parent = parents.get(tmap["parent_id"])
    child = children.get(tmap["child_id"])
    if parent is None:
        return "skip: unknown parent"

    # ---- extract main prose FIRST (H1 title feeds the breadcrumb schema) --
    m = re.search(r"<body[^>]*>\s*<main>(.*?)</main>", raw, re.S)
    if not m:
        return "skip: unexpected structure (no <main> block)"
    prose = m.group(1).strip()

    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", prose, re.S)
    if not h1_m:
        return "skip: no H1"
    h1_text = re.sub(r"\s+", " ", h1_m.group(1)).strip()
    prose = prose.replace(h1_m.group(0), "", 1).strip()

    # ---- head -----------------------------------------------------------
    head_new = raw
    if ARTICLE_CSS not in head_new:
        head_new = head_new.replace(
            "</head>",
            '<link rel="stylesheet" href="%s">\n</head>' % ARTICLE_CSS, 1)
    canonical_m = re.search(
        r'<link rel="canonical" href="([^"]+)"', raw)
    canonical = canonical_m.group(1) if canonical_m else row.get("canonical") \
        or (SITE_URL + "/" + row["output_path"])
    # upgrade BreadcrumbList JSON-LD to match the visible breadcrumb
    new_bc = breadcrumb_schema(parent, child, canonical, title=h1_text)
    if "BreadcrumbList" in head_new:
        head_new = re.sub(
            r'{"@context":"https://schema.org","@type":"BreadcrumbList".*?}\s*(?=</script>)',
            lambda _mm: new_bc.replace("\\", "\\\\"), head_new, count=1,
            flags=re.S)

    # H2 anchors + TOC
    h2s = [re.sub(r"<[^>]+>", " ", t).strip() for t in
           re.findall(r"<h2[^>]*>(.*?)</h2>", prose, re.S)]
    h2s = [re.sub(r"\s+", " ", t) for t in h2s]
    counter = [0]

    def add_id(match):
        counter[0] += 1
        return '<h2 id="sec-%d">%s</h2>' % (counter[0], match.group(1))

    prose = re.sub(r"<h2[^>]*>(.*?)</h2>", add_id, prose, flags=re.S)
    toc = toc_html(h2s)
    prose = _close_table_wrap(wrap_tables(prose))

    # meta from head (real values only)
    date_m = re.search(r'property="article:published_time" content="([^"]+)"',
                       raw)
    date = date_m.group(1) if date_m else ""
    author_m = re.search(r'<meta name="author" content="([^"]+)"', raw)
    author = author_m.group(1) if author_m else (row.get("author") or "Mr Tú")

    meta_bits = []
    if date:
        meta_bits.append('<time datetime="%s">%s</time>'
                         % (esc(date), esc(display_date(date))))
    if author:
        meta_bits.append("<span>%s</span>" % esc(author))
    # <footer> here is the HTML5 byline/footer-of-section pattern; it keeps
    # article QA word-count scope identical to the pre-shell files (only the
    # H1 + prose count as main editorial content).
    meta_html = ('<footer class="article-meta">%s</footer>'
                 % '<span aria-hidden="true">·</span>'.join(meta_bits)) \
        if meta_bits else ""

    kicker = esc(parent["parent_title"] +
                  (" · " + child["child_title"] if child else ""))

    # related / prev-next from PUBLISHED set only (never link drafts)
    pub_child = published_by_child.get(tmap["child_id"], [])
    pub_parent = published_by_parent.get(tmap["parent_id"], [])
    related = related_html(row, pub_child, pub_parent, parents, children)
    pn = pn_html(row, pub_child)

    new_body = (
        '<body>\n<main class="article-main">\n'
        '<article class="article">\n'
        '<header class="article-header">\n'
        + breadcrumb_html(parent, child, h1_text) + "\n"
        + '<p class="article-kicker">%s</p>\n' % kicker
        + "</header>\n"
        + '<h1 class="article-title">%s</h1>\n' % h1_text
        + meta_html + "\n"
        + (toc + "\n" if toc else "")
        + '<div class="article-body">\n' + prose + "\n</div>\n"
        + "</article>\n</main>\n"
        + cta_html() + "\n"
        + related + ("\n" + pn if pn else "") + "\n"
    )

    out = head_new[:head_new.index("<body")] + new_body + \
        raw[raw.index("</main>") + len("</main>"):].lstrip("\n")
    # raw tail after </main> holds the compact footer + chatbot embed
    out = out.replace("</main>", "</main>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return "migrated"



def fix_breadcrumb(path, rows_by_id):
    """Idempotent repair of an existing BreadcrumbList JSON-LD block.

    Repairs the known defect where the final ListItem uses the canonical
    URL as "name". Correct shape:
        name  = human-readable article title (the page's H1)
        item  = canonical article URL
    Positions are renumbered 1..n (valid + contiguous). JSON syntax is
    validated before the file is written; a broken block is left
    untouched and reported.
    """
    raw = open(path, encoding="utf-8").read()
    m = re.search(
        r'(<script[^>]*>)\s*(\{"@context":"https://schema.org",'
        r'"@type":"BreadcrumbList".*?\})\s*(</script>)', raw, re.S)
    if not m:
        return "fix-bc: no BreadcrumbList block"
    try:
        data = json.loads(m.group(2))
    except ValueError:
        return "fix-bc: broken JSON (left untouched)"

    canonical_m = re.search(r'<link rel="canonical" href="([^"]+)"', raw)
    canonical = canonical_m.group(1) if canonical_m else None
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.S)
    h1_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h1_m.group(1))
                     ).strip() if h1_m else ""
    if not canonical or not h1_text:
        return "fix-bc: missing canonical or H1 (left untouched)"

    items = data.get("itemListElement") or []
    if not isinstance(items, list) or not items:
        return "fix-bc: empty itemListElement (left untouched)"

    changed = False
    last = items[-1]
    if last.get("name") != h1_text or last.get("item") != canonical:
        last["name"] = h1_text
        last["item"] = canonical
        changed = True
    for i, it in enumerate(items):
        if it.get("position") != i + 1:
            it["position"] = i + 1
            changed = True

    if not changed:
        return "ok: already correct"

    new_block = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    out = raw[:m.start(2)] + new_block + raw[m.end(2):]
    json.loads(new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return "fixed-breadcrumb"


def main():
    fix_only = "--fix-breadcrumbs" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    include_drafts = "--drafts" in sys.argv
    rows = load_rows()
    rows_by_id = {r["article_id"]: r for r in rows}
    parents, children = load_tax()
    tax_map = load_map()
    related_html._map = tax_map

    published = [r for r in rows
                 if r["status"] == "PUBLISHED"
                 and not r["article_id"].startswith("SAMPLE")]
    published = [r for r in published if file_exists("/" + r["output_path"])]

    by_child, by_parent = {}, {}
    for r in published:
        t = tax_map.get(r["article_id"])
        if not t:
            continue
        by_child.setdefault(t["child_id"], []).append(r)
        by_parent.setdefault(t["parent_id"], []).append(r)
    for v in list(by_child.values()) + list(by_parent.values()):
        v.sort(key=lambda r: r["article_id"])

    if args:
        targets = args
    else:
        targets = [os.path.join(REPO, r["output_path"]) for r in published]
        if include_drafts:
            draft_root = os.path.join(REPO, "_drafts")
            for root, _dirs, files in os.walk(draft_root):
                for fn in files:
                    if fn.endswith(".html"):
                        targets.append(os.path.join(root, fn))

    counts = {}
    for t in targets:
        t = os.path.relpath(t, REPO) if os.path.isabs(t) else t
        if not os.path.isfile(t):
            counts["missing"] = counts.get("missing", 0) + 1
            continue
        if fix_only:
            res = fix_breadcrumb(t, rows_by_id)
        else:
            res = migrate(t, rows_by_id, by_child, by_parent, parents,
                          children, tax_map)
        counts[res] = counts.get(res, 0) + 1
        print("%-24s %s" % (res, t))
    print("---")
    for k in sorted(counts):
        print("%s: %d" % (k, counts[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
