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
    return load_json(repo_path("config", "business-facts.json"))


def load_ownership():
    return load_json(repo_path("config", "seo-ownership.json"))


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
