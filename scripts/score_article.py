#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic article scorer for the content factory.

Usage: python3 scripts/score_article.py path/to/article.html
Exit codes: 0 = PASS, 2 = REVIEW, 3 = FAIL, 4 = tool/config error.
No network. No AI. Reads:
  config/article-rubric.json, config/business-facts.json,
  config/seo-ownership.json, data/content-matrix.csv
Writes reports/article-quality/<slug>.json
"""
import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib


def score_article(article, matrix, ownership, facts, rubric):
    """Return (score, status, sections, critical_failures, warnings, recommendations, review_flags)."""
    sections = {}
    failures = []
    warnings = []
    recommendations = []
    review_flags = []

    row = lib.find_matrix_row(article, matrix)
    thin_min = int(rubric.get("thin_content_min_words", 300))
    severe_min = 60

    # ---------------- technical_seo (15) ----------------
    pts = 0
    t = article.title
    if t:
        pts += 3 if 20 <= len(t) <= 75 else 2
    else:
        failures.append("missing title")
    md = article.meta_description
    if md:
        pts += 3 if 60 <= len(md) <= 170 else 2
    else:
        failures.append("missing meta description")
    if article.canonical:
        pts += 3
        base = os.path.basename(article.path)
        row_slug = (row or {}).get("slug") or ""
        def _canon_ok(v):
            if not v:
                return False
            c = article.canonical.rstrip("/")
            return c.endswith(v) or c.endswith(v + ".html")
        ok = _canon_ok(article.slug) or _canon_ok(base) or _canon_ok(row_slug)
        if ok:
            pts += 2
        else:
            failures.append("canonical inconsistent with slug")
    else:
        failures.append("missing canonical")
    if len(article.h1s) == 1:
        pts += 3
    elif len(article.h1s) == 0:
        failures.append("missing H1")
    else:
        failures.append("multiple H1s (%d)" % len(article.h1s))
    if article.lang:
        pts += 1
    if article.noindex:
        failures.append("noindex on public article")
    sections["technical_seo"] = min(pts, 15)

    # ---------------- search_intent (15) ----------------
    pts = 0
    pk = ((row or {}).get("primary_keyword") or "").strip()
    if not pk:
        pk = (article.h1s[0] if article.h1s else (article.title or "")).strip()
    title_l = (article.title or "").lower()
    h1_l = (article.h1s[0].lower() if article.h1s else "")
    body_l = article.body_text.lower()
    if pk:
        if pk.lower() in title_l:
            pts += 4
        else:
            warnings.append("primary keyword not in title")
        if pk.lower() in h1_l:
            pts += 4
        else:
            warnings.append("primary keyword not in H1")
        if pk.lower() in body_l:
            pts += 4
        else:
            warnings.append("primary keyword not in body")
    cat = (row or {}).get("category")
    if cat in lib.CATEGORIES:
        pts += 3
    elif row is not None:
        failures.append("invalid matrix category: %r" % cat)
    else:
        failures.append("article not in content matrix")
    sections["search_intent"] = min(pts, 15)

    # ---------------- content_quality (15) ----------------
    pts = 0
    wc = len(article.words)
    if wc >= thin_min:
        pts += 5
    elif wc >= severe_min:
        pts += 2
        review_flags.append("thin content (%d words < %d)" % (wc, thin_min))
        recommendations.append("expand article with useful, non-filler content")
    else:
        failures.append("article empty or severely truncated (%d words)" % wc)
    # duplicate sentences
    sents = [s.strip().lower() for s in re.split(r"[.!?]\s", article.body_text)
             if len(s.strip()) > 40]
    dup = len(sents) - len(set(sents))
    if sents and dup / float(len(sents)) < 0.10:
        pts += 4
    elif sents and dup / float(len(sents)) < 0.25:
        pts += 2
        warnings.append("duplicate sentences detected (%d)" % dup)
    else:
        pts += 0
        warnings.append("excessive duplicate sentences (%d/%d)" % (dup, len(sents)))
    if lib.PLACEHOLDER_RE.search(article.raw):
        failures.append("placeholder/template text present")
    else:
        pts += 3
    h2s = [h for lvl, h in article.headings if lvl == 2]
    if len(h2s) >= 2:
        pts += 3
    elif len(h2s) == 1:
        pts += 1
        warnings.append("only one H2 section")
    else:
        warnings.append("no H2 sections")
    sections["content_quality"] = min(pts, 15)

    # ---------------- internal_linking (10) ----------------
    pts = 0
    cat_hub = lib.CATEGORIES.get(cat)
    hub_linked = any(os.path.basename(t) == cat_hub for t, _ in article.internal_links)
    if hub_linked:
        pts += 4
    else:
        review_flags.append("parent category hub not linked (%s)" % cat_hub)
        recommendations.append("link the parent category hub: %s" % cat_hub)
    others = [t for t, _ in article.internal_links
              if os.path.basename(t) != cat_hub and t != ""]
    if len(others) >= 2:
        pts += 3
    elif len(others) == 1:
        pts += 1
        warnings.append("only one non-parent internal link")
    else:
        warnings.append("no contextual internal links beyond parent hub")
    anchors = [a for _, a in article.internal_links if a]
    if anchors:
        most = max([anchors.count(a) for a in set(anchors)])
        if most <= 2:
            pts += 2
        else:
            pts += 1
            warnings.append("repeated identical anchors (max %d)" % most)
    if len(set(os.path.basename(t) for t, _ in article.internal_links)) >= 3:
        pts += 1
    sections["internal_linking"] = min(pts, 10)

    # ---------------- cannibalization (15) ----------------
    pts = 15
    cf, cw, cr = lib.check_cannibalization(article, ownership, matrix, facts)
    for f in cf:
        pts -= 15
        failures.append(f)
        break  # one deduction is enough; all failures still listed
    pts -= min(2 * len(cw), 4)
    warnings.extend(cw)
    if cr:
        pts -= 3
        review_flags.extend(cr)
    sections["cannibalization"] = max(pts, 0)

    # ---------------- fact_safety (10) ----------------
    pts = 10
    ff, fw = lib.check_fact_safety(article, facts)
    if ff:
        pts = 0
        failures.extend(ff)
    warnings.extend(fw)
    sections["fact_safety"] = pts

    # ---------------- schema_metadata (10) ----------------
    pts = 0
    if article.has_article_schema:
        pts += 5
    else:
        warnings.append("no Article schema (add where article architecture supports it)")
    if article.has_breadcrumb:
        pts += 3
    if article.author:
        pts += 1
    if article.date:
        pts += 1
    sections["schema_metadata"] = min(pts, 10)

    # ---------------- readability_structure (5) ----------------
    pts = 0
    paras = [re.sub(r"<[^>]+>", " ", p) for p in article.paragraphs]
    big = [p for p in paras if len(re.sub(r"\s+", " ", p)) > 900]
    if paras and len(big) / float(len(paras)) <= 0.2:
        pts += 2
    else:
        warnings.append("large text blocks detected (%d/%d paragraphs > 900 chars)" % (len(big), len(paras)))
    # heading order: no skipping (h1 -> h3)
    levels = [lvl for lvl, _ in article.headings]
    ok_order = True
    prev = 0
    for lv in levels:
        if prev and lv > prev + 1:
            ok_order = False
        prev = lv
    if ok_order:
        pts += 2
    else:
        warnings.append("heading hierarchy skips levels")
    if article.body_text and max(len(w) for w in article.words) < 40:
        pts += 1
    sections["readability_structure"] = min(pts, 5)

    # ---------------- technical_validation (5) ----------------
    pts = 5
    for target, _ in article.internal_links:
        if target.startswith("http"):
            continue
        if lib.resolve_target(article, target) is None:
            failures.append("broken internal link: %r" % target)
            pts = 0
            break
    # parseability sanity
    if article.path.endswith(".html") and not re.search(r"<(main|article|body)\b", article.html, re.I):
        failures.append("malformed HTML: no main/article/body container")
        pts = 0
    sections["technical_validation"] = pts

    # ---------------- legal content safety ----------------
    if row is not None and str(row.get("requires_sources", "")).strip().lower() in ("true", "yes", "1"):
        body_l = article.body_text.lower()
        legal = any(h in body_l for h in lib.REQUIRED_CATEGORIES_HINTS)
        if legal and not article.sources_section:
            review_flags.append(
                "article covers legal/traffic/licence topics but has no source/reference section")
            recommendations.append(
                "add official source references (gov.vn etc.) for legal/fine/licence claims")
        if legal and not article.sources_section and str(row.get("source_notes", "")).strip() == "":
            # no sources AND no source notes at all -> stronger signal stays REVIEW
            pass

    # ---------------- production standard (Mr Tú factory standard) ---------
    production_metrics = None
    if row is not None and not lib.is_sample_row(row):
        pf, pr, pw, production_metrics = lib.evaluate_production_standard(
            article, row, rubric, ownership)
        failures.extend(pf)
        review_flags.extend(pr)
        warnings.extend(pw)

    total = sum(sections.values())
    if failures:
        status = "FAIL"
    elif review_flags or total < 90:
        status = "REVIEW" if total >= 80 else "FAIL"
    else:
        status = "PASS"
    return total, status, sections, failures, warnings, recommendations, review_flags, production_metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("article")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        rubric = lib.load_rubric()
        facts = lib.load_business_facts()
        ownership = lib.load_ownership()
        matrix = lib.load_matrix()
        article = lib.Article(os.path.abspath(args.article))
    except (lib.ConfigError, ValueError, Exception) as e:
        print("ERROR: %s" % e)
        return lib.EXIT_ERROR

    total, status, sections, failures, warnings, recs, review_flags, prod = score_article(
        article, matrix, ownership, facts, rubric)

    report = {
        "article": os.path.abspath(args.article),
        "slug": article.slug,
        "score": total,
        "status": status,
        "critical_failures": failures,
        "sections": sections,
        "warnings": warnings,
        "review_flags": review_flags,
        "recommendations": recs,
        "production_standard": prod,
    }
    outdir = lib.repo_path("reports", "article-quality")
    try:
        os.makedirs(outdir, exist_ok=True)
        with io.open(os.path.join(outdir, article.slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    print("article : %s" % args.article)
    print("score   : %d/100" % total)
    print("status  : %s" % status)
    for k in sorted(sections):
        print("  %-24s %d" % (k, sections[k]))
    if failures:
        print("CRITICAL FAILURES:")
        for f_ in failures:
            print("  ! %s" % f_)
    if review_flags:
        print("REVIEW FLAGS:")
        for r in review_flags:
            print("  ? %s" % r)
    if warnings:
        print("warnings: %d" % len(warnings))
    for r in recs:
        print("  > %s" % r)
    return {"PASS": lib.EXIT_PASS, "REVIEW": lib.EXIT_REVIEW, "FAIL": lib.EXIT_FAIL}[status]


if __name__ == "__main__":
    sys.exit(main())
