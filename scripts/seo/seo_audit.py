#!/usr/bin/env python3
"""Deterministic SEO audit engine for thuexemayhanoi/shop.

READ-ONLY with respect to factory-owned state. This module never writes to
data/content-matrix.csv, data/batches/, _drafts/ or any article prose.
It reads the published page tree, sitemap.xml, robots.txt and _config.yml
and emits a findings report (reports/seo/audit.json) plus category scores.

Rules are grouped by root cause: one finding per rule, with the full list
of affected URLs attached. Exit codes:
  0 = audit produced a report (findings may or may not exist)
  2 = usage/tool error
Use --strict to exit 1 when any P0/P1 finding exists (PR verification).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

BASE_URL = "https://thuexemayhanoi.github.io/shop/"

# Repository-operational trees that are never public site pages.
EXCLUDED_DIRS = {"tests", "docs", "reports", "scripts", "config", "data",
                 "assets", "_data", "_includes", "_snippets", ".github"}
EXCLUDED_FILES = {"AGENTS.md", "README.md", "ARCHITECTURE.md"}

OPERATIONAL_PATTERNS = ["AGENTS.md", "README.md", "ARCHITECTURE.md",
                        "config/", "data/", "reports/", "scripts/", "tests/",
                        "docs/"]

CATEGORIES = ["technical_seo", "crawl_indexability", "canonical_sitemap",
              "internal_linking", "structured_data", "onpage_structure",
              "performance", "deploy_hygiene"]


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def site_pages(root):
    """All publishable HTML pages as {relpath: fullpath}."""
    pages = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDED_DIRS and not d.startswith("_")
                       and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".html"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            pages[rel] = full
    return pages


def page_url(rel):
    """Canonical live-route URL for a page file.

    index.html maps to the directory URL (GitHub Pages serves dir/), the
    site root maps to the bare base URL.
    """
    if rel == "index.html":
        return BASE_URL
    if rel.endswith("/index.html"):
        return BASE_URL + rel[: -len("index.html")]
    return BASE_URL + rel


def normalize_url(u):
    """Normalize a URL that may appear as /dir/index.html or /dir/."""
    if u == BASE_URL + "index.html":
        return BASE_URL
    if u.endswith("/index.html"):
        return u[: -len("index.html")]
    return u


class PageParser(HTMLParser):
    """Collect head metadata, headings, JSON-LD blocks, links and ids."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonicals = []
        self.title = ""
        self.in_title = False
        self.meta_description = ""
        self.robots = ""
        self.jsonld = []
        self._jsonld_buf = None
        self.headings = []  # (level, text)
        self.links = []      # (href, text)
        self.ids = set()
        self._h_level = None
        self._h_buf = None
        self._a_href = None
        self._a_buf = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonicals.append(a.get("href", ""))
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "description":
                self.meta_description = (a.get("content") or "").strip()
            if name == "robots":
                self.robots = (a.get("content") or "").strip()
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._jsonld_buf = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._h_level = int(tag[1])
            self._h_buf = []
        elif tag == "a":
            self._a_href = a.get("href")
            self._a_buf = []
        if a.get("id"):
            self.ids.add(a["id"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script" and self._jsonld_buf is not None:
            self.jsonld.append("".join(self._jsonld_buf))
            self._jsonld_buf = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._h_buf is not None:
            self.headings.append((self._h_level, " ".join("".join(self._h_buf).split())))
            self._h_buf = None
        elif tag == "a" and self._a_buf is not None:
            if self._a_href is not None:
                self.links.append((self._a_href, " ".join("".join(self._a_buf).split())))
            self._a_buf = None
            self._a_href = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self._jsonld_buf is not None:
            self._jsonld_buf.append(data)
        if self._h_buf is not None:
            self._h_buf.append(data)
        if self._a_buf is not None:
            self._a_buf.append(data)


def parse_page(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    p = PageParser()
    try:
        p.feed(html)
    except Exception:
        pass
    return p, html


def load_sitemap(root):
    path = os.path.join(root, "sitemap.xml")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return re.findall(r"<loc>\s*(.*?)\s*</loc>", f.read())


def finding(rule, severity, category, root_cause, evidence, affected,
             recommended_fix, safe_to_auto_fix=False, risk="low",
             seo_impact="", indexing_impact=""):
    return {
        "rule": rule,
        "severity": severity,
        "category": category,
        "root_cause": root_cause,
        "evidence": evidence,
        "affected": affected,
        "affected_count": len(affected),
        "recommended_fix": recommended_fix,
        "safe_to_auto_fix": safe_to_auto_fix,
        "risk_level": risk,
        "seo_impact": seo_impact,
        "indexing_impact": indexing_impact,
    }


def run_audit(root):
    pages = site_pages(root)
    findings = []
    urls = {page_url(r) for r in pages}
    url_to_rel = {page_url(r): r for r in pages}

    sitemap_locs = load_sitemap(root)
    locs = [u.strip() for u in sitemap_locs if u.strip()]

    # ---------- canonical / sitemap ----------
    canon_bad, canon_missing, canon_shopshop, canon_dotslash = [], [], [], []
    canon_relative = []
    canon_crosspage = []
    h1_bad, title_bad, desc_bad, jsonld_bad, schema_mismatch, missing_breadcrumb = [], [], [], [], [], []
    schema_missing_type = []
    noindex_pages = []
    linked_from = {}
    broken_links = []
    broken_anchors = []

    titles, descs = {}, {}

    for rel, full in sorted(pages.items()):
        url = page_url(rel)
        p, _ = parse_page(full)

        # canonical checks
        if not p.canonicals:
            canon_missing.append(url)
        else:
            c = p.canonicals[0]
            if len(p.canonicals) > 1:
                canon_bad.append(url)
            if "/shop/shop/" in c or c.rstrip("/").endswith("/shop/shop"):
                canon_shopshop.append(url)
            if "../" in c:
                canon_dotslash.append(url)
            expected = url
            absolute = urljoin(BASE_URL, c) if c else ""
            absolute = normalize_url(absolute)
            if not absolute.startswith("https://"):
                canon_bad.append(url)
            elif absolute == expected and not c.startswith("https://"):
                # resolvable but not absolute (e.g. '/shop/...' root-relative)
                canon_relative.append(url)
            elif absolute != expected:
                if absolute in urls:
                    # deliberate cross-page canonical (e.g. legacy duplicate
                    # consolidated onto the homepage) — review, not corruption
                    canon_crosspage.append(url)
                else:
                    canon_bad.append(url)

        # robots
        if "noindex" in p.robots.lower():
            noindex_pages.append(url)

        # on-page structure
        h1s = [t for lvl, t in p.headings if lvl == 1]
        if len(h1s) != 1 or not h1s[0].strip():
            h1_bad.append(url)
        t = p.title.strip()
        if not t:
            title_bad.append(url)
        else:
            titles.setdefault(t, []).append(url)
        d = p.meta_description.strip()
        if not d:
            desc_bad.append(url)
        else:
            descs.setdefault(d, []).append(url)

        # heading hierarchy: skip level > 1 without any h1 seen
        seen = set()
        for lvl, _ in p.headings:
            seen.add(lvl)
        if p.headings and 1 not in seen:
            h1_bad.append(url)

        # JSON-LD
        parsed = []
        for block in p.jsonld:
            try:
                parsed.append(json.loads(block))
            except Exception:
                jsonld_bad.append(url)
                parsed.append(None)
        types = [b.get("@type") for b in parsed if isinstance(b, dict)]
        is_article = rel.startswith("cam-nang/") and re.match(r"^[a-z]{2}-\d{4}-", os.path.basename(rel)) is not None
        if is_article:
            if "Article" not in types and "BlogPosting" not in types:
                schema_missing_type.append(url)
            if "BreadcrumbList" not in types:
                missing_breadcrumb.append(url)
        for b in parsed:
            if not isinstance(b, dict):
                continue
            refs = []
            main = b.get("mainEntityOfPage") or b.get("url")
            if main:
                refs.append(main)
            if b.get("@type") == "BreadcrumbList":
                for it in b.get("itemListElement", []):
                    item = it.get("item")
                    if item:
                        refs.append(item)
            for ref in refs:
                ref = normalize_url(urljoin(BASE_URL, str(ref)))
                if ref.startswith(BASE_URL) and ref not in urls:
                    schema_mismatch.append(url)

        # internal links
        for href, _text in p.links:
            if not href or href.startswith(("http", "mailto:", "tel:", "javascript:", "data:")):
                continue
            target = urljoin(url, href)
            frag = ""
            if "#" in target:
                target, frag = target.split("#", 1)
            target = normalize_url(target)
            if target.startswith(BASE_URL) or target == "https://thuexemayhanoi.github.io/shop":
                if target not in urls:
                    broken_links.append((url, target))
                else:
                    linked_from.setdefault(url_to_rel[target], []).append(rel)
                    if frag:
                        tp, _ = parse_page(pages[url_to_rel[target]])
                        if frag not in tp.ids:
                            broken_anchors.append((url, target + "#" + frag))
            elif target.startswith("https://thuexemayhanoi.github.io/"):
                broken_links.append((url, target))

    # ---------- sitemap coverage ----------
    loc_set = []
    dupes = [u for u in set(locs) if locs.count(u) > 1]
    cross = set(canon_crosspage)
    pagination = {u for u in urls if re.search(r"/page-\d+\.html$", u)}
    missing_in_sitemap = sorted(u for u in urls
                                if u not in set(locs) and u not in cross
                                and u not in pagination)
    pagination_out = sorted(pagination - set(locs))
    ghost_sitemap = sorted(u for u in set(locs) if u not in urls)

    # ---------- orphans ----------
    # published article pages not referenced by any other page
    article_rels = [r for r in pages if r.startswith("cam-nang/") and r != "index.html"
                    and re.match(r"^[a-z]{2}-\d{4}-", os.path.basename(r))]
    orphans = sorted(page_url(r) for r in article_rels if r not in linked_from)

    # ---------- duplicate titles / descriptions ----------
    dup_titles = {t: u for t, u in titles.items() if len(u) > 1}
    dup_descs = {d: u for d, u in descs.items() if len(u) > 1}

    # ---------- deploy hygiene ----------
    cfg = os.path.join(root, "_config.yml")
    cfg_text = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
    unexcluded = [pat for pat in OPERATIONAL_PATTERNS
                  if pat not in cfg_text]
    exposed = []
    for rel in pages:
        pass
    if unexcluded:
        exposed = unexcluded
    # stale legacy scripts deployed? (motoai files are excluded via config)
    motoai = [fn for fn in os.listdir(root) if fn.startswith("motoai_") and fn not in cfg_text]

    def add(rule, sev, cat, cause, ev, affected, fix, auto=False, risk="low", si="", ii=""):
        if affected:
            findings.append(finding(rule, sev, cat, cause, ev, affected, fix, auto, risk, si, ii))

    add("canonical.missing", "P0", "canonical_sitemap",
        "Page has no <link rel=canonical> — indexability at risk.",
        "grep: 0 canonical tags in <head>", canon_missing,
        "Add self-canonical " + BASE_URL + "<relpath> matching the live route.",
        si="Duplicate/indexing ambiguity", ii="Direct")
    add("canonical.wrong", "P1", "canonical_sitemap",
        "Canonical does not match the live route of the page (base path /shop mismatch or stale slug).",
        "canonical != expected route", canon_bad,
        "Set canonical to the exact live URL of the page; never rename the route.",
        si="Wrong URL may be indexed", ii="Direct")
    add("canonical.shop-shop", "P0", "canonical_sitemap",
        "Canonical contains the duplicated base path '/shop/shop/'.",
        "string '/shop/shop/' in canonical href", canon_shopshop,
        "Strip one duplicated '/shop' segment so the canonical equals the live route.",
        auto=True, si="Canonical points to a 404", ii="Direct")
    add("canonical.relative", "P2", "canonical_sitemap",
        "Canonical href is root-relative (e.g. '/shop/...') instead of absolute — emitted by the generated pagination/hub shell.",
        "canonical resolves to the page route but does not start with https://", canon_relative,
        "Absolutize the canonical to the exact live URL (same route, no rename).",
        auto=True, si="Interoperability risk with some crawlers", ii="Indirect")
    add("canonical.cross-page", "P3", "canonical_sitemap",
        "Canonical deliberately points at another live page (duplicate-content consolidation, e.g. legacy landing pages onto the homepage).",
        "canonical resolves to a different existing live route", canon_crosspage,
        "Review: keep if intentional consolidation; else self-canonicalize.",
        risk="review", si="Consolidates ranking signals", ii="By design")
    add("canonical.parent-dotslash", "P1", "canonical_sitemap",
        "Canonical uses '../' relative segments.", "string '../' in canonical href",
        canon_dotslash, "Replace with the absolute live URL.")
    add("sitemap.missing-pages", "P1", "canonical_sitemap",
        "Published pages are missing from sitemap.xml.",
        "sitemap URL set != published page set", missing_in_sitemap,
        "Regenerate sitemap via scripts/generate_sitemap.py after publish.",
        si="Discovery delay", ii="Direct")
    add("sitemap.ghost-urls", "P1", "canonical_sitemap",
        "sitemap.xml contains URLs with no corresponding published page.",
        "sitemap URL has no source file", ghost_sitemap,
        "Regenerate sitemap from the published page tree.",
        si="Sends crawlers to 404s", ii="Direct")
    add("sitemap.pagination-policy", "P3", "canonical_sitemap",
        "Generated pagination pages (page-N.html) are excluded from sitemap.xml by the factory sitemap generator policy.",
        "generate_sitemap.py rebuilds /cam-nang/ URLs from matrix rows only; pagination is reachable via hub links and self-canonical",
        pagination_out,
        "Owner decision: keep excluded (crawlable via links) or extend generate_sitemap.py to include pagination.",
        risk="review", si="Slower discovery of deep list pages", ii="Indirect")
    add("sitemap.duplicates", "P2", "canonical_sitemap",
        "sitemap.xml contains duplicate <loc> entries.", "count(loc)>1", dupes,
        "Deduplicate sitemap entries.", auto=True)
    add("robots.noindex", "P0", "crawl_indexability",
        "Page carries an accidental noindex robots meta.",
        "meta robots contains noindex", noindex_pages,
        "Remove noindex unless the page is intentionally non-public.")
    add("h1.wrong-count", "P2", "onpage_structure",
        "Page does not have exactly one non-empty <h1>.",
        "heading scan", h1_bad,
        "Ensure the article layout emits exactly one h1 (the title).",
        si="Weak relevance signal", ii="Indirect")
    add("title.missing", "P1", "onpage_structure",
        "Page has an empty <title>.", "title tag empty", title_bad,
        "Set a unique, descriptive <title>.")
    add("title.duplicate", "P2", "onpage_structure",
        "Multiple pages share the same <title>.",
        "duplicate title text", sorted(dup_titles.values()),
        "Differentiate titles per page intent.")
    add("description.missing", "P2", "onpage_structure",
        "Page has no meta description.", "meta description empty", desc_bad,
        "Add a unique meta description from article front matter.")
    add("description.duplicate", "P3", "onpage_structure",
        "Multiple pages share the same meta description.",
        "duplicate description", sorted(dup_descs.values()),
        "Differentiate descriptions per page.")
    add("schema.jsonld-invalid", "P1", "structured_data",
        "A JSON-LD block does not parse.", "json.loads failed", jsonld_bad,
        "Fix the generated JSON-LD block.", si="Rich result loss", ii="Indirect")
    add("schema.article-missing", "P1", "structured_data",
        "Published article pages missing Article JSON-LD.", "type scan",
        schema_missing_type, "Emit Article schema in the article shell.")
    add("schema.breadcrumb-missing", "P2", "structured_data",
        "Published article pages missing BreadcrumbList JSON-LD.", "type scan",
        missing_breadcrumb, "Emit BreadcrumbList schema in the article shell.")
    add("schema.stale-url", "P1", "structured_data",
        "Structured data references a URL that is not a live route (stale slug or wrong base path).",
        "mainEntityOfPage/breadcrumb item not in route set", sorted(set(schema_mismatch)),
        "Point schema URLs at the current verified route; keep in sync with canonical.",
        si="Search engines may drop the rich result", ii="Indirect")
    add("links.broken-internal", "P1", "internal_linking",
        "Internal links point to routes that do not exist.",
        "href target not in route set", sorted({f"{a} -> {b}" for a, b in broken_links}),
        "Fix the href to the correct live route.",
        si="Crawl waste + user 404", ii="Indirect")
    add("links.broken-fragment", "P2", "internal_linking",
        "Internal fragment links point to ids that do not exist on the target page.",
        "fragment not in target ids", sorted({f"{a} -> {b}" for a, b in broken_anchors}),
        "Fix or add the anchor id.")
    add("links.orphans", "P2", "internal_linking",
        "Published article pages are not referenced by any other page (orphan).",
        "no inbound internal link found", orphans,
        "Ensure hub/category pages link every published article.")
    add("deploy.operational-unexcluded", "P2", "deploy_hygiene",
        "Repository-operational files are not excluded from the Pages build.",
        "_config.yml exclude list gap", exposed,
        "Add them to the _config.yml exclude list (crawl hygiene, not a secret leak).",
        auto=True)
    add("deploy.legacy-scripts-exposed", "P3", "deploy_hygiene",
        "Legacy motoai_*.js files at repo root are not excluded from the Pages build.",
        "_config.yml missing entry", motoai,
        "Exclude them (already documented as non-deployable).", auto=True)

    # ---------- scores ----------
    sev_weight = {"P0": 100, "P1": 40, "P2": 12, "P3": 4}
    scores = {}
    for cat in CATEGORIES:
        pen = sum(sev_weight[f["severity"]] for f in findings if f["category"] == cat)
        scores[cat] = max(0, 100 - pen)

    worst = {"P0": 1, "P1": 2, "P2": 3, "P3": 4, None: 5}
    worst_sev = min((worst[f["severity"]] for f in findings), default=5)
    worst_sev = {v: k for k, v in worst.items()}.get(worst_sev)

    metrics = {
        "published_pages": len(pages),
        "sitemap_url_count": len(locs),
        "canonical_error_count": len(canon_missing) + len(canon_bad) + len(canon_shopshop) + len(canon_dotslash) + len(canon_relative) + len(canon_crosspage),
        "broken_internal_link_count": len(set(broken_links)),
        "broken_anchor_count": len(set(broken_anchors)),
        "schema_error_count": len(jsonld_bad) + len(schema_missing_type) + len(missing_breadcrumb) + len(set(schema_mismatch)),
        "orphan_count": len(orphans),
        "duplicate_title_count": sum(len(u) - 1 for u in dup_titles.values()),
        "duplicate_meta_count": sum(len(u) - 1 for u in dup_descs.values()),
        "noindex_count": len(noindex_pages),
        "h1_error_count": len(h1_bad),
        "missing_sitemap_entry_count": len(missing_in_sitemap),
        "pagination_sitemap_gap_count": len(pagination_out),
        "ghost_sitemap_url_count": len(ghost_sitemap),
    }

    return {
        "tool": "seo-audit",
        "base_url": BASE_URL,
        "findings": findings,
        "scores": scores,
        "metrics": metrics,
        "worst_severity": worst_sev,
        "summary": {
            "P0": sum(1 for f in findings if f["severity"] == "P0"),
            "P1": sum(1 for f in findings if f["severity"] == "P1"),
            "P2": sum(1 for f in findings if f["severity"] == "P2"),
            "P3": sum(1 for f in findings if f["severity"] == "P3"),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=repo_root())
    ap.add_argument("--out", default=None, help="output json path (default reports/seo/audit.json)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any P0/P1 finding exists")
    args = ap.parse_args(argv)

    report = run_audit(args.root)
    out = args.out or os.path.join(args.root, "reports", "seo", "audit.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "summary": report["summary"],
        "scores": report["scores"],
        "metrics": report["metrics"],
        "findings": len(report["findings"]),
    }, ensure_ascii=False, indent=2))

    if args.strict and (report["summary"]["P0"] or report["summary"]["P1"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
