#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate data/content-matrix.csv for the 2,000-article content factory.

Checks:
  - exactly 2000 production rows (SAMPLE rows excluded)
  - exactly 40 batches, exactly 50 production rows per batch
  - unique article_id / slug / output_path / primary_keyword / working_title
  - valid category (one of lib.CATEGORIES)
  - valid parent_hub (category -> hub html file)
  - no protected-intent conflict vs config/seo-ownership.json
  - required fields present on every production row
  - legal/safety topics flagged requires_sources=true
Exit 0 = valid, non-zero = violation.
No network. Deterministic.
"""
import io
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib

EXPECTED_PROD_ROWS = 2000
EXPECTED_BATCHES = 40
EXPECTED_BATCH_SIZE = 50

PROD_ID_RE = re.compile(r"^[A-Z]{2}-\d{4}$")
BATCH_RE = re.compile(r"^BATCH-\d{3}$")

REQUIRED_FIELDS = [
    "article_id", "status", "category", "primary_keyword",
    "secondary_keywords", "search_intent", "working_title", "slug",
    "output_path", "parent_hub", "protected_intent_conflict",
    "requires_sources", "source_notes", "internal_link_targets",
    "commercial_link_target", "author", "planned_date", "score",
    "quality_status", "last_checked", "notes", "batch_id",
]

LEGAL_HINTS = ["luật", "phạt", "giấy phép", "bảo hiểm", "nghị định",
               "thông tư", "csgt", "đăng kiểm", "sát hạch", "bộc phạt"]


def validate(matrix, ownership):
    errors = []
    warnings = []
    prod = [r for r in matrix if not lib.is_sample_row(r)]
    samples = [r for r in matrix if lib.is_sample_row(r)]

    if len(prod) != EXPECTED_PROD_ROWS:
        errors.append("production rows = %d, expected %d" % (len(prod), EXPECTED_PROD_ROWS))

    # header completeness
    if matrix:
        hdr = set(matrix[0].keys())
        for f in REQUIRED_FIELDS:
            if f not in hdr:
                errors.append("missing matrix column: %s" % f)

    # uniqueness
    for f in ("article_id", "slug", "output_path", "primary_keyword", "working_title"):
        vals = [(r.get(f) or "").strip() for r in prod]
        seen = {}
        for v in vals:
            if v:
                seen[v] = seen.get(v, 0) + 1
        dups = [v for v, n in seen.items() if n > 1]
        if dups:
            errors.append("duplicate %s in production rows: %d values" % (f, len(dups)))

    # per-row checks
    protected_intents = []
    for page in ownership.get("protected_pages", []):
        protected_intents.extend(page.get("primary_intents", []))

    for r in prod:
        aid = r.get("article_id", "")
        if not PROD_ID_RE.match(aid):
            errors.append("bad article_id %r" % aid)
        cat = r.get("category", "")
        if cat not in lib.CATEGORIES:
            errors.append("row %s: unknown category %r" % (aid, cat))
        else:
            hub = r.get("parent_hub", "")
            if hub != lib.CATEGORIES[cat]:
                errors.append("row %s: parent_hub %r != %r" % (aid, hub, lib.CATEGORIES[cat]))
        bid = r.get("batch_id", "")
        if not BATCH_RE.match(bid):
            errors.append("row %s: bad batch_id %r" % (aid, bid))
        for f in REQUIRED_FIELDS:
            if f not in ("score", "quality_status", "last_checked", "notes",
                         "source_notes", "protected_intent_conflict") and not (r.get(f) or "").strip():
                errors.append("row %s: empty required field %s" % (aid, f))
        kw = (r.get("primary_keyword") or "").strip()
        if kw and lib.norm_tokens(kw) in [lib.norm_tokens(p) for p in protected_intents if p]:
            errors.append("row %s: primary_keyword conflicts with protected intent %r" % (aid, kw))
        if (r.get("protected_intent_conflict") or "").strip().lower() not in ("", "no", "none", "false", "0"):
            errors.append("row %s: protected_intent_conflict = %r" % (aid, r.get("protected_intent_conflict")))

    # batches
    batches = {}
    for r in prod:
        batches.setdefault(r.get("batch_id", ""), []).append(r)
    if len(batches) != EXPECTED_BATCHES:
        errors.append("batches = %d, expected %d" % (len(batches), EXPECTED_BATCHES))
    for bid, rows in sorted(batches.items()):
        if len(rows) != EXPECTED_BATCH_SIZE:
            errors.append("batch %s has %d rows, expected %d" % (bid, len(rows), EXPECTED_BATCH_SIZE))

    # legal topics require sources
    for r in prod:
        blob = " ".join([
            (r.get("primary_keyword") or ""), (r.get("secondary_keywords") or ""),
            (r.get("working_title") or ""), (r.get("search_intent") or ""),
        ]).lower()
        needs = any(h in blob for h in LEGAL_HINTS)
        has = (r.get("requires_sources") or "").strip().lower() == "true"
        if needs and not has:
            errors.append("row %s: legal topic not flagged requires_sources" % r.get("article_id"))

    return errors, warnings


def main():
    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return 4
    errors, warnings = validate(matrix, ownership)
    prod = [r for r in matrix if not lib.is_sample_row(r)]
    samples = [r for r in matrix if lib.is_sample_row(r)]
    print("matrix: %d production rows, %d sample rows" % (len(prod), len(samples)))
    if warnings:
        for w in warnings:
            print("WARN: %s" % w)
    if errors:
        for e in errors[:50]:
            print("VIOLATION: %s" % e)
        print("TOTAL VIOLATIONS: %d" % len(errors))
        return 1
    print("OK: content matrix is valid (2000 production rows, 40 batches x 50).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
