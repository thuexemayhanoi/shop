#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared deterministic article-quality logic.

Used by scripts/validate_article.py, scripts/score_article.py and
scripts/check_cannibalization.py. Python 3 standard library only.
No network access. No AI APIs. All checks are deterministic.
"""
import csv
import io
import json
import os
import re
import sys
from difflib import SequenceMatcher

def _find_root():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.exists(os.path.join(d, "config", "article-rubric.json")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _find_root()

# Exit codes (shared convention)
EXIT_PASS = 0
EXIT_REVIEW = 2
EXIT_FAIL = 3
EXIT_ERROR = 4

CATEGORIES = {
    "Kinh nghiệm": "kinhnghiem.html",
    "An toàn": "antoan.html",
    "Xe máy": "xemay.html",
    "Du lịch": "dulich.html",
    "Cung đường": "cungduong.html",
    "Hỏi đáp": "hoidap.html",
}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def repo_path(*parts):
    return os.path.join(ROOT, *parts)


def load_json(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # config error -> exit code 4
        raise ConfigError("cannot load %s: %s" % (path, e))


class ConfigError(Exception):
    pass


def load_rubric():
    return load_json(repo_path("config", "article-rubric.json"))


def load_business_facts():
    facts = load_json(repo_path("config", "business-facts.json"))
    # schema v2: only the 'trusted' section is owner-confirmed production truth.
    if "trusted" in facts:
        facts = dict(facts["trusted"])
        facts["requires_owner_confirmation"] = load_json(
            repo_path("config", "business-facts.json")).get(
            "requires_owner_confirmation", {})
    return facts


def load_ownership():
    return load_json(repo_path("config", "seo-ownership.json"))


def load_site_config():
    """The single machine-readable source for generated public URLs.

    GitHub Pages serves this repository as a PROJECT SITE at
    https://thuexemayhanoi.github.io/shop/ — every generated URL must live
    under the /shop/ base path. Scripts must use this config instead of
    hard-coding origins.
    """
    cfg = load_json(repo_path("config", "site.json"))
    for key in ("origin", "baseurl", "site_url"):
        if not cfg.get(key):
            raise ConfigError("config/site.json missing %r" % key)
    return cfg


def site_url(path=None):
    """Absolute public URL for a repo-relative path (e.g. 'kinhnghiem.html'
    -> 'https://thuexemayhanoi.github.io/shop/kinhnghiem.html')."""
    cfg = load_site_config()
    if path is None:
        return cfg["site_url"]
    return cfg["site_url"].rstrip("/") + "/" + str(path).lstrip("/")


def load_matrix():
    """Return list of dict rows from data/content-matrix.csv."""
    path = repo_path("data", "content-matrix.csv")
    if not os.path.exists(path):
        raise ConfigError("missing data/content-matrix.csv")
    with io.open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_sample_row(row):
    return str(row.get("article_id", "")).upper().startswith("SAMPLE") or \
        str(row.get("notes", "")).upper().find("SAMPLE") >= 0


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

PLACEHOLDER_PATTERNS = [
    r"\bTODO\b", r"\bFIXME\b", r"\bXXX\b", r"\[chèn[^]]*\]",
    r"\[insert[^]]*\]", r"lorem ipsum", r"\bplaceholder\b", r"TBD\b",
]
PLACEHOLDER_RE = re.compile("|".join(PLACEHOLDER_PATTERNS), re.I)


class Article(object):
    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            raise ValueError("article not found: %s" % path)
        self.raw = io.open(path, encoding="utf-8", errors="replace").read()
        self.front_matter = {}
        self.html = self.raw
        self._split_front_matter()
        self.slug = self._derive_slug()

    def _split_front_matter(self):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", self.raw, re.S)
        if m:
            block = m.group(1)
            self.html = self.raw[m.end():]
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    self.front_matter[k.strip()] = v.strip().strip('"').strip("'")

    def _derive_slug(self):
        base = os.path.basename(self.path)
        return re.sub(r"\.html?$", "", base)

    # -- metadata ----------------------------------------------------------
    @property
    def title(self):
        m = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.S | re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return (self.front_matter.get("title") or "").strip() or None

    @property
    def meta_description(self):
        m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', self.html, re.I)
        if not m:
            m = re.search(r'<meta\s+content="([^"]*)"\s+name="description"', self.html, re.I)
        return m.group(1).strip() if m else None

    @property
    def canonical(self):
        m = re.search(r'<link\s+rel="canonical"\s+href="([^"]*)"', self.html, re.I)
        if not m:
            m = re.search(r'<link\s+href="([^"]*)"\s+rel="canonical"', self.html, re.I)
        return m.group(1).strip() if m else None

    @property
    def h1s(self):
        return [re.sub(r"<[^>]+>", " ", m).strip()
                for m in re.findall(r"<h1[^>]*>(.*?)</h1>", self.html, re.S | re.I)]

    @property
    def headings(self):
        """List of (level, text) in document order."""
        out = []
        for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", self.html, re.S | re.I):
            out.append((int(m.group(1)), re.sub(r"<[^>]+>", " ", m.group(2)).strip()))
        return out

    @property
    def lang(self):
        m = re.search(r"<html[^>]*\blang=[\"']([a-zA-Z-]+)[\"']", self.html, re.I)
        return m.group(1) if m else None

    @property
    def noindex(self):
        return bool(re.search(r'<meta[^>]+name="robots"[^>]+noindex', self.html, re.I))

    @property
    def links(self):
        """List of (href, anchor_text)."""
        out = []
        for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', self.html, re.S | re.I):
            anchor = re.sub(r"<[^>]+>", " ", m.group(2))
            out.append((m.group(1).strip(), re.sub(r"\s+", " ", anchor).strip()))
        return out

    @property
    def internal_links(self):
        out = []
        for href, anchor in self.links:
            if href.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
                # absolute same-site links count as internal
                if "thuexemayhanoi.github.io" in href:
                    out.append((href.split("thuexemayhanoi.github.io/shop/")[-1], anchor))
                continue
            if href.startswith(("./", "/")):
                out.append((href.lstrip("./"), anchor))
            else:
                out.append((href, anchor))
        return out

    @property
    def body_text(self):
        body = re.sub(r"<script\b.*?</script>", " ", self.html, flags=re.S | re.I)
        body = re.sub(r"<style\b.*?</style>", " ", body, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", body)
        return re.sub(r"\s+", " ", text).strip()

    # -- main editorial content (word-count + contextual-link scope) --------
    # Word count and contextual-link counting use MAIN CONTENT ONLY:
    # 1) if an <article> element exists, use it; elif <main>, use that;
    #    otherwise fall back to the whole HTML body.
    # 2) then strip <script>/<style>/<nav>/<header>/<footer>/<aside>/
    #    <noscript>/<form> and any element whose class matches
    #    breadcrumb|menu|nav|footer|chatbot|motoai|cookie|sidebar|pagination.
    # 3) words = whitespace-separated tokens of the remaining text.
    _EXCLUDE_TAG_RE = re.compile(
        r"<(script|style|nav|header|footer|aside|noscript|form|svg)\b.*?</\1\s*>",
        re.S | re.I)
    _EXCLUDE_CLASS_RE = re.compile(
        r"<([a-z0-9]+)\b[^>]*class=\"[^\"]*(breadcrumb|menu|nav|footer|chatbot|motoai|cookie|sidebar|pagination)[^\"]*\"[^>]*>.*?</\1\s*>",
        re.S | re.I)
    _GENERIC_ANCHORS = ["xem thêm", "tại đây", "bấm vào đây", "click here",
                        "link này", "xem tại đây", "đọc thêm", "see more"]

    def _main_content_html(self):
        m = re.search(r"<article\b.*?</article\s*>", self.html, re.S | re.I)
        if m:
            html = m.group(0)
        else:
            m = re.search(r"<main\b.*?</main\s*>", self.html, re.S | re.I)
            html = m.group(0) if m else self.html
        html = self._EXCLUDE_TAG_RE.sub(" ", html)
        prev = None
        while prev != html:
            prev = html
            html = self._EXCLUDE_CLASS_RE.sub(" ", html)
        return html

    def _main_links(self):
        """All <a href> links inside the main editorial content."""
        out = []
        for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>',
                             self._main_content_html(), re.S | re.I):
            anchor = re.sub(r"<[^>]+>", " ", m.group(2))
            out.append((m.group(1).strip(), re.sub(r"\s+", " ", anchor).strip()))
        return out

    @property
    def contextual_links(self):
        """Contextual INTERNAL links inside the main editorial body.

        Excluded by construction: menu, mobile menu, footer, breadcrumb,
        logo, contact FAB, chatbot, legal/footer navigation, pagination,
        social links and external links (absolute URLs off-site).
        """
        out = []
        for href, anchor in self._main_links():
            if href.startswith(("mailto:", "tel:", "data:", "javascript:")):
                continue
            if href.startswith(("http://", "https://")):
                if "thuexemayhanoi.github.io" in href:
                    # same-site absolute URL -> strip origin + /shop base path
                    if "/shop/" in href:
                        href = href.split("thuexemayhanoi.github.io/shop/", 1)[-1]
                    else:
                        href = href.split("thuexemayhanoi.github.io/", 1)[-1]
                    out.append((href.lstrip("/"), anchor))
                continue
            if href.startswith(("./", "/")):
                out.append((href.lstrip("./").lstrip("/"), anchor))
            else:
                out.append((href, anchor))
        return out

    @property
    def main_content_words(self):
        """Words of the main editorial content only (see class docstring)."""
        text = re.sub(r"<[^>]+>", " ", self._main_content_html())
        text = re.sub(r"\s+", " ", text).strip()
        return [w for w in text.split(" ") if w]

    def analyze_contextual_links(self, row=None, ownership=None):
        """Deterministic contextual-link analysis for the production standard.

        Returns dict with:
          count, anchor_texts, duplicate_anchor_count, generic_anchors,
          parent_hub, parent_hub_present, commercial_links,
          duplicate_commercial_anchor
        """
        anchors = [a for _, a in self.contextual_links if a]
        dup = {a: anchors.count(a) for a in set(anchors)}
        duplicate_anchor_count = sum(n - 1 for n in dup.values() if n > 1)
        generic = [a for a in anchors
                   if a.lower().strip(".!") in self._GENERIC_ANCHORS]
        parent_hub = CATEGORIES.get((row or {}).get("category")) if row else None
        parent_hub_present = None
        if parent_hub:
            parent_hub_present = any(
                os.path.basename(t) == parent_hub
                for t, _ in self.contextual_links)
        commercial_paths = set()
        if ownership:
            for p in ownership.get("protected_pages", []):
                commercial_paths.add(os.path.basename(p.get("path") or ""))
        commercial = [(t, a) for t, a in self.contextual_links
                      if os.path.basename(t) in commercial_paths]
        comm_dup = 0
        if commercial:
            ca = [a for _, a in commercial if a]
            counts = {a: ca.count(a) for a in set(ca)}
            comm_dup = sum(n - 1 for n in counts.values() if n > 1)
        return {
            "count": len(self.contextual_links),
            "anchor_texts": anchors,
            "duplicate_anchor_count": duplicate_anchor_count,
            "generic_anchors": generic,
            "parent_hub": parent_hub,
            "parent_hub_present": parent_hub_present,
            "commercial_links": commercial,
            "duplicate_commercial_anchor": comm_dup,
        }

    def heading_structure(self):
        """Report heading levels + order problems (skipped levels, no H1/H2)."""
        levels = [lvl for lvl, _ in self.headings]
        problems = []
        if not levels:
            problems.append("no headings at all")
        prev = 0
        for lv in levels:
            if prev and lv > prev + 1:
                problems.append("heading level skip %d->%d" % (prev, lv))
            prev = lv
        if levels and 1 not in levels:
            problems.append("no H1")
        return {"levels": levels, "problems": problems}

    def broken_internal_links(self):
        """Internal links (anywhere in the article) that do not resolve."""
        out = []
        for target, _ in self.internal_links:
            if target.startswith(("http://", "https://")):
                continue
            if resolve_target(self, target) is None:
                out.append(target)
        return out

    @property
    def words(self):
        return [w for w in re.split(r"\s+", self.body_text) if w]

    @property
    def paragraphs(self):
        out = []
        for m in re.finditer(r"<p[^>]*>(.*?)</p>", self.html, re.S | re.I):
            out.append(m.group(1))
        return out

    @property
    def has_article_schema(self):
        for m in re.finditer(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', self.html, re.S | re.I):
            if '"Article"' in m.group(1) or '"NewsArticle"' in m.group(1):
                return True
        return False

    @property
    def has_breadcrumb(self):
        if re.search(r'itemtype="[^"]*BreadcrumbList"', self.html, re.I):
            return True
        return bool(re.search(r'breadcrumb', self.html, re.I)) and \
            bool(re.search(r'BreadcrumbList', self.html))

    @property
    def author(self):
        for m in re.finditer(r'<meta[^>]+name="author"[^>]+content="([^"]*)"', self.html, re.I):
            return m.group(1)
        return self.front_matter.get("author")

    @property
    def date(self):
        for m in re.finditer(r'<meta[^>]+property="article:published_time"[^>]+content="([^"]*)"', self.html, re.I):
            return m.group(1)
        return self.front_matter.get("date")

    @property
    def sources_section(self):
        """True if a source/reference section or official-source links exist."""
        if re.search(r'<h[23][^>]*>\s*(Nguồn|Sources?|Tham khảo)', self.html, re.I):
            return True
        for href, _ in self.links:
            if re.search(r"\.(gov|edu)\.vn|\.gov|chinhphu\.vn|congbao\.vn|vanban\.vn|gplx\.vn", href, re.I):
                return True
        return False

    def strip_for_similarity(self, text):
        return re.sub(r"[^\p{L}\p{N}]+", " ", text.lower()).split() if False else \
            re.sub(r"[^\wàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ\s]",
                   " ", text.lower()).split()


# ---------------------------------------------------------------------------
# Similarity helpers (deterministic, stdlib only)
# ---------------------------------------------------------------------------

def norm_tokens(text):
    return re.sub(r"[^\wàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ\s]",
                  " ", text.lower()).split()


def jaccard(a, b):
    sa, sb = set(norm_tokens(a)), set(norm_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def seq_ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def phrase_overlap(a, b):
    ta = norm_tokens(a)
    tb = norm_tokens(b)
    if not ta or not tb:
        return 0.0
    grams = set()
    for n in (2, 3, 4):
        for i in range(len(ta) - n + 1):
            grams.add(" ".join(ta[i:i + n]))
    hits = 0
    total = 0
    for n in (2, 3, 4):
        for i in range(len(tb) - n + 1):
            total += 1
            if " ".join(tb[i:i + n]) in grams:
                hits += 1
    return hits / float(total) if total else 0.0


# ---------------------------------------------------------------------------
# Matrix lookup
# ---------------------------------------------------------------------------

def find_matrix_row(article, matrix):
    """Find matrix row for article by output_path basename, slug, or article ID."""
    base = os.path.basename(article.path)
    norm_base = re.sub(r"\.html?$", "", base)
    rid = article.front_matter.get("article_id")
    for row in matrix:
        if row.get("output_path") and os.path.basename(row["output_path"]) in (base, norm_base):
            return row
        if row.get("slug") and row.get("slug") in (article.slug, norm_base):
            return row
        if rid and row.get("article_id") == rid:
            return row
    return None


# ---------------------------------------------------------------------------
# Link resolution
# ---------------------------------------------------------------------------

def resolve_target(article, target):
    """Resolve an internal link target against article dir then repo root."""
    if target.startswith("http"):
        return None  # not checkable offline; not a broken local link
    cands = [
        os.path.normpath(os.path.join(os.path.dirname(article.path), target)),
        os.path.normpath(os.path.join(ROOT, target)),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------------------
# Fact safety
# ---------------------------------------------------------------------------

def _fmt_vnd(n):
    s = "{:,}".format(n).replace(",", ".")
    return s


def build_approved_prices(facts):
    """Flatten model -> set of allowed price integers with variants."""
    out = {}
    for key, model in facts["approved_models"].items():
        allowed = {model["daily"], model["week"], model["monthMin"], model["monthMax"]}
        out[key] = {"name": model["name"], "allowed": allowed, "unknown": False}
    return out


def find_price_claims(text):
    """Return list of (context, price_int) for every VND price mention."""
    claims = []
    for m in re.finditer(r"(.{0,60})(\d[\d.,]*)\s*(?:đ|vnd|kđ|k/|k |nghìn|triệu)(.{0,20})", text, re.I):
        num = m.group(2)
        try:
            if "triệu" in m.group(0).lower():
                # "2 triệu" -> 2,000,000
                val = int(float(num.replace(".", "").replace(",", ".")) * 1000000)
            elif num.lower().endswith("k") or re.match(r"^\d{1,3}k$", num.replace(".", "").lower()):
                val = int(float(num.replace(".", "").replace(",", ".").rstrip("kK")) * 1000)
            else:
                val = int(float(num.replace(".", "").replace(",", "")))
        except ValueError:
            continue
        claims.append((m.group(0), val))
    return claims


def check_fact_safety(article, facts):
    """Return (failures, warnings). failures are CRITICAL."""
    failures, warnings = [], []
    text = article.body_text
    approved = facts["approved_models"]
    unknown_models = [m.lower() for m in facts.get("unapproved_models", [])]
    deposit_msg = facts["deposit_policy"]["standard_wording"]

    # 1) forbidden stale deposit claims
    for phrase in facts["deposit_policy"]["forbidden_claims"]:
        if re.search(re.escape(phrase), text, re.I):
            failures.append("stale deposit-policy claim: %r" % phrase)

    # 2) price claims near approved models must match approved values
    claims = find_price_claims(text)
    for ctx, val in claims:
        ctx_l = ctx.lower()
        for key, model in approved.items():
            variants = [key.lower(), model["name"].lower()]
            if key == "airblade":
                variants += ["air blade", "airblade"]
            hit = any(v in ctx_l for v in variants)
            if hit:
                if val not in (model["daily"], model["week"], model["monthMin"], model["monthMax"]):
                    failures.append("wrong price for %s: found %d near %r" % (model["name"], val, ctx.strip()))
                break
        else:
            # 3) unknown models must not have invented fixed prices
            for u in unknown_models:
                if u in ctx_l:
                    failures.append("invented fixed price for unapproved model %r: %s" % (u, ctx.strip()))
                    break

    # 4) deposit amount mentions must be inside the approved range wording
    for m in re.finditer(r"cọc[^.]{0,80}?(\d[\d.,]*)\s*(?:đ|vnd|triệu)", text, re.I):
        num = m.group(1)
        try:
            if "triệu" in m.group(0).lower():
                val = int(float(num.replace(",", ".")) * 1000000)
            else:
                val = int(float(num.replace(".", "").replace(",", "")))
        except ValueError:
            continue
        lo, hi = facts["deposit_policy"]["range_vnd"]
        if not (lo <= val <= hi):
            failures.append("deposit amount outside approved range: %d (%s)" % (val, m.group(0).strip()))
    return failures, warnings


# ---------------------------------------------------------------------------
# Cannibalization
# ---------------------------------------------------------------------------

def check_cannibalization(article, ownership, matrix, facts):
    """Return (failures, warnings, review_flags). Deterministic evidence only."""
    failures, warnings, review = [], [], []
    row = find_matrix_row(article, matrix)
    title = article.title or ""
    h1 = article.h1s[0] if article.h1s else ""

    candidate_kw = (row or {}).get("primary_keyword") or h1 or title

    # 1) protected commercial intent exact match
    for page in ownership.get("protected_pages", []):
        for intent in page.get("primary_intents", []):
            if norm_tokens(intent) and norm_tokens(intent) == norm_tokens(candidate_kw):
                failures.append(
                    'candidate primary keyword %r conflicts with %s: protected primary intent exact match'
                    % (candidate_kw, page["path"]))
            # protected intent appearing as the article title verbatim
            elif norm_tokens(intent) and (norm_tokens(intent) == norm_tokens(title) or
                                         norm_tokens(intent) == norm_tokens(h1)):
                failures.append(
                    'title/H1 collides with protected intent of %s (%r)'
                    % (page["path"], intent))

    # 2) duplicate primary keyword across matrix rows (excluding the article's own row)
    for r in matrix:
        if row is not None and r is row:
            continue
        rk = (r.get("primary_keyword") or "").strip()
        if rk and norm_tokens(rk) == norm_tokens(candidate_kw):
            failures.append("duplicate primary keyword with matrix row %s: %r"
                            % (r.get("article_id"), rk))

    # 3) near-similar titles (warning / review flag; never auto-FAIL on fuzzy alone)
    cmp_titles = []
    for r in matrix:
        if row is not None and r is row:
            continue
        if r.get("working_title"):
            cmp_titles.append((r.get("article_id"), r["working_title"]))
    for rid, t in cmp_titles:
        sim = seq_ratio(title, t)
        if sim >= 0.90:
            review.append("very similar title to matrix row %s (ratio %.2f)" % (rid, sim))
        elif sim >= 0.85:
            warnings.append("similar title to matrix row %s (ratio %.2f)" % (rid, sim))

    # 4) compare against existing published articles under data/articles/
    art_dir = repo_path("data", "articles")
    if os.path.isdir(art_dir):
        for fn in sorted(os.listdir(art_dir)):
            if not fn.endswith(".html"):
                continue
            try:
                other = Article(os.path.join(art_dir, fn))
            except ValueError:
                continue
            if norm_tokens(other.title or "") and norm_tokens(other.title or "") == norm_tokens(title):
                failures.append("duplicate title with existing article %s" % fn)
            elif seq_ratio(title, other.title or "") >= 0.90:
                review.append("very similar title to existing article %s" % fn)
    return failures, warnings, review


# ---------------------------------------------------------------------------
# Technical validation (hard errors)
# ---------------------------------------------------------------------------

REQUIRED_CATEGORIES_HINTS = ["luật", "phạt", "giấy phép", "bảo hiểm", "nghị định", "thông tư"]


def evaluate_production_standard(article, row, rubric, ownership):
    """Mr Tú Content Factory production standard (applies to PRODUCTION
    matrix rows only; SAMPLE/compact fixtures are exempt).

    Word rule (main-content words only):
      1600–2000 satisfied | 1200–1599 / 2001–2300 REVIEW | <1200 / >2300 FAIL
    Contextual internal links: exactly 3–5; 0 = strong REVIEW (never PASS);
      <3 or >5 = REVIEW. Parent hub link required (missing = REVIEW).
    Commercial contextual links: >1 = REVIEW. Repeated exact commercial
      anchor = strong REVIEW. Generic / duplicate anchors = warnings.

    Returns (failures, review_flags, warnings, metrics).
    """
    if is_sample_row(row or {}):
        # SAMPLE / compact test fixtures are exempt from the production
        # length and contextual-link gates.
        return [], [], [], {
            "note": "SAMPLE/fixture row — production standard not enforced",
            "word_count": len(article.main_content_words),
            "contextual_internal_link_count": len(article.contextual_links),
        }
    failures = []
    review_flags = []
    warnings = []
    length_cfg = rubric.get("article_length", {})
    tmin = int(length_cfg.get("target_min_words", 1600))
    tmax = int(length_cfg.get("target_max_words", 2000))
    rmin = int(length_cfg.get("review_min_words", 1200))
    rmax = int(length_cfg.get("review_max_words", 2300))
    link_cfg = rubric.get("contextual_internal_links", {})
    lmin = int(link_cfg.get("min", 3))
    lmax = int(link_cfg.get("max", 5))
    comm_max = int(rubric.get("commercial_links_max", 1))

    wc = len(article.main_content_words)
    if wc < tmin or wc > tmax:
        if wc < rmin:
            failures.append("production article far below length standard "
                            "(%d words < %d)" % (wc, rmin))
        elif wc > rmax:
            failures.append("production article far above length standard "
                            "(%d words > %d)" % (wc, rmax))
        else:
            review_flags.append(
                "production article outside 1,600–2,000 word target "
                "(%d words; REVIEW range %d–%d / %d–%d)"
                % (wc, rmin, tmin - 1, tmax + 1, rmax))
    if wc >= tmin and wc > tmax + 300:
        warnings.append("very long article — check for filler")

    li = article.analyze_contextual_links(row, ownership)
    n = li["count"]
    if n == 0:
        review_flags.append(
            "zero contextual internal links in editorial body (never PASS)")
    elif n < lmin:
        review_flags.append(
            "only %d contextual internal links (minimum %d)" % (n, lmin))
    elif n > lmax:
        review_flags.append(
            "%d contextual internal links (maximum %d)" % (n, lmax))
    if li["parent_hub_present"] is False:
        review_flags.append(
            "parent category hub not contextually linked (%s)" % li["parent_hub"])
    if len(li["commercial_links"]) > comm_max:
        review_flags.append(
            "%d contextual commercial landing-page links (maximum %d)"
            % (len(li["commercial_links"]), comm_max))
    if li["duplicate_commercial_anchor"] > 0:
        review_flags.append("repeated exact-match commercial anchor")
    if li["generic_anchors"]:
        warnings.append("generic anchor text present: %r"
                         % sorted(set(li["generic_anchors"])))
    if li["duplicate_anchor_count"] > 0:
        warnings.append("duplicate exact-match anchors (%d repetitions)"
                        % li["duplicate_anchor_count"])

    metrics = {
        "word_count": wc,
        "word_count_scope": "main editorial content (article/main container "
                            "minus nav/header/footer/breadcrumb/chatbot/scripts)",
        "contextual_internal_link_count": n,
        "parent_hub_link_present": li["parent_hub_present"],
        "anchor_texts": li["anchor_texts"],
        "duplicate_anchor_count": li["duplicate_anchor_count"],
        "commercial_link_count": len(li["commercial_links"]),
        "heading_structure": article.heading_structure(),
    }
    return failures, review_flags, warnings, metrics


def validate_article(article, matrix, ownership, facts, rubric):
    """Return list of hard errors (empty = valid)."""
    errors = []
    body = article.body_text

    if not article.title:
        errors.append("missing <title>")
    if not article.meta_description:
        errors.append("missing meta description")
    if not article.canonical:
        errors.append("missing canonical")
    elif article.canonical.strip() in ("", "/", "#") or "example.com" in article.canonical:
        errors.append("placeholder canonical: %r" % article.canonical)
    if len(article.h1s) == 0:
        errors.append("missing H1")
    elif len(article.h1s) > 1:
        errors.append("multiple H1s (%d)" % len(article.h1s))
    if article.noindex:
        errors.append("noindex on public article")
    if not article.lang:
        errors.append("missing lang attribute")

    # matrix presence
    row = find_matrix_row(article, matrix)
    if row is None:
        errors.append("article not present in data/content-matrix.csv")
    else:
        status = (row.get("status") or "").strip().upper()
        if status in ("PUBLISHED", "PASS") and not is_sample_row(row):
            pass  # already published; re-validation allowed
        cat = row.get("category")
        if cat not in CATEGORIES:
            errors.append("unknown category in matrix row: %r" % cat)

    # canonical / slug consistency: canonical must end with the matrix slug
    # or the article file basename
    if article.canonical:
        base = os.path.basename(article.path)
        def _canon_ok(v):
            if not v:
                return False
            c = article.canonical.rstrip("/")
            return c.endswith(v) or c.endswith(v + ".html")
        ok = _canon_ok(article.slug) or _canon_ok(base)
        if row is not None and row.get("slug"):
            ok = ok or _canon_ok(row["slug"])
        if not ok:
            errors.append("canonical does not match article slug %r: %r"
                          % (article.slug, article.canonical))

    # placeholder text
    if PLACEHOLDER_RE.search(article.raw):
        errors.append("placeholder/template text present (TODO/FIXME/lorem/...)")

    # severely truncated
    wc = len(article.words)
    if wc < 60:
        errors.append("article empty or severely truncated (%d words)" % wc)

    # malformed: quick sanity — main content tag present for HTML articles
    if article.path.endswith(".html") and not re.search(r"<(main|article|body)\b", article.html, re.I):
        errors.append("no main/article/body container (malformed or unrendered)")

    # broken internal links
    for target, _anchor in article.internal_links:
        if target.startswith("http"):
            continue
        if resolve_target(article, target) is None:
            errors.append("broken internal link: %r" % target)

    # fact safety criticals
    f_fail, _ = check_fact_safety(article, facts)
    errors.extend(f_fail)

    return errors
