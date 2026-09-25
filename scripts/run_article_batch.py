#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch controller for the 2,000-article content factory.

Orchestrates ONE batch of up to 50 articles end to end:

    per article: PLANNED -> WRITING -> QA -> (REPAIR -> QA){<=3} -> outcome

Outcomes: PASS (publishable), FAIL (never published), REVIEW (needs another
repair pass), BLOCKED (repair budget exhausted — never published),
PROVIDER_ERROR (safe stop; row returns to PLANNED for a later run).

Hard invariants:
  - One bad article NEVER kills the other 49 (per-article isolation).
  - PASS / PUBLISHED rows are never rewritten.
  - No real writer => safe stop (WRITER_NOT_CONFIGURED / WRITER_SECRET_MISSING);
    rows stay PLANNED. Content is never fabricated.
  - QA is deterministic: validate_article + check_cannibalization + score_article.
  - Max batch = 50, max repair attempts = 3, bounded API retries, sequential
    processing by default (configurable 1-3 via --concurrency).

Modes:
  --batch BATCH-001 [--prepare|--resume|--dry-run|--pilot]
  --next            first batch with PLANNED rows (never chained by itself)
  --pilot          BATCH-001 ONLY, max 50, no automatic next batch
  --mark-published flip PASS rows with existing on-MAIN files to PUBLISHED
                   (call only AFTER the commit reached MAIN)

Reports: reports/batches/BATCH-XXX.json + .md (per-article detail).

Exit codes:
  0 ok/prepared/dry-run
  1 usage or matrix violation
  2 non-blocking issues (REVIEW/BLOCKED present)
  3 batch had FAIL articles
  4 tool/config error
  5 WRITER_NOT_CONFIGURED
  6 WRITER_SECRET_MISSING
"""
import argparse
import concurrent.futures
import csv
import datetime
import io
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib
import article_writer
import score_article as score_article_module

MAX_BATCH_SIZE = 50
MAX_REPAIR_ATTEMPTS = 3
MAX_CONCURRENCY = 3
# Cost/failure guard: stop generating NEW articles when >= 5 provider errors
# occur AND they exceed 30% of attempted writes. Completed results preserved.
PROVIDER_ERROR_FLOOR = 5
PROVIDER_ERROR_RATE = 0.30
EXIT_USAGE = 1
EXIT_ISSUES = 2
EXIT_FAILS = 3
EXIT_ERROR = 4


# ---------------------------------------------------------------------------
# Matrix state helpers (pure functions, unit-testable)
# ---------------------------------------------------------------------------

def production_rows(matrix):
    return [r for r in matrix if not lib.is_sample_row(r)]


def batch_rows(matrix, batch_id):
    return [r for r in production_rows(matrix)
            if (r.get("batch_id") or "").strip() == batch_id]


def next_batch_id(matrix):
    """First batch that still has a PLANNED row, or None."""
    for r in production_rows(matrix):
        if (r.get("status") or "").strip() == "PLANNED":
            return (r.get("batch_id") or "").strip()
    return None


def select_claim_rows(rows, batch_size=MAX_BATCH_SIZE):
    """Rows claimable by this runner: PLANNED only, capped at batch_size."""
    batch_size = min(int(batch_size), MAX_BATCH_SIZE)
    return [r for r in rows
            if (r.get("status") or "").strip() == "PLANNED"][:batch_size]


def select_resume_rows(rows, repo_root, batch_size=MAX_BATCH_SIZE):
    """Unfinished rows: file exists and status is WRITING/QA/REPAIR/REVIEW.
    PASS/PUBLISHED rows are never re-processed (resume safety)."""
    batch_size = min(int(batch_size), MAX_BATCH_SIZE)
    active = ("WRITING", "QA", "REPAIR", "REVIEW")
    out = []
    for r in rows:
        st = (r.get("status") or "").strip()
        if st not in active:
            continue
        path = r.get("output_path") or ""
        if path and os.path.isfile(os.path.join(repo_root, path)):
            out.append(r)
    return out[:batch_size]


def select_stale_rows(rows, repo_root, batch_size=MAX_BATCH_SIZE):
    """Crash recovery: rows claimed WRITING/QA/REPAIR whose file was never
    written (runner died mid-write). They are safely re-claimable; their
    status will be redone from scratch. PASS/PUBLISHED never qualify."""
    out = []
    for r in rows:
        st = (r.get("status") or "").strip()
        if st not in ("WRITING", "QA", "REPAIR", "REVIEW"):
            continue
        path = r.get("output_path") or ""
        if path and not os.path.isfile(os.path.join(repo_root, path)):
            out.append(r)
    return out[:batch_size]


def neighboring_topics(matrix, row, limit=6):
    """Nearby matrix topics (same category, other rows) so the writer avoids
    cannibalization. Excludes the article itself and PUBLISHED titles' exact
    duplicates."""
    topics = []
    for r in production_rows(matrix):
        if r.get("article_id") == row.get("article_id"):
            continue
        if (r.get("category") or "").strip() != (row.get("category") or "").strip():
            continue
        t = (r.get("working_title") or "").strip()
        if t:
            topics.append({"article_id": r.get("article_id"), "title": t})
    return topics[:limit]


def build_writer_context(row, matrix, ownership, facts, rubric, site=None,
                         repo_root=None):
    """Full production context handed to the writer for ONE article.

    Includes everything the writer must respect: identity fields, target
    length, link rules, parent hub requirement, commercial link limit,
    trusted business facts, unapproved-model policy, deposit wording, legal
    source requirements, protected intents, site base URL and neighboring
    matrix topics for cannibalization awareness."""
    rubric = rubric or {}
    length_cfg = rubric.get("article_length", {})
    link_cfg = rubric.get("contextual_internal_links", {})
    site = site or lib.load_site_config()
    base = (site.get("site_url") or "https://thuexemayhanoi.github.io/shop").rstrip("/")
    slug = (row.get("slug") or "").strip()
    out_path = (row.get("output_path") or "").strip()
    canonical = "%s/%s" % (base, out_path) if out_path else base
    protected = []
    for p in (ownership or {}).get("protected_pages", []):
        for intent in p.get("primary_intents", []):
            protected.append({"page": p.get("path"), "intent": intent})
    trusted = dict(facts or {})
    # Defensive: never leak unverified fields into the writer context.
    trusted.pop("requires_owner_confirmation", None)
    return {
        "standard": "Mr Tú Content Factory production standard",
        "article_id": row.get("article_id"),
        "category": row.get("category"),
        "category_label": row.get("category"),
        "working_title": row.get("working_title"),
        "primary_keyword": row.get("primary_keyword"),
        "secondary_keywords": row.get("secondary_keywords") or "",
        "search_intent": row.get("search_intent"),
        "slug": slug,
        "output_path": out_path,
        "parent_hub": row.get("parent_hub"),
        "requires_sources": row.get("requires_sources"),
        "source_notes": row.get("source_notes") or "",
        "internal_link_targets": (row.get("internal_link_targets") or "").replace(";", ", "),
        "commercial_link_target": row.get("commercial_link_target") or "",
        "canonical_url": canonical,
        "published_date": row.get("planned_date") or datetime.date.today().isoformat(),
        "target_min_words": int(length_cfg.get("target_min_words", 1600)),
        "target_max_words": int(length_cfg.get("target_max_words", 2000)),
        "contextual_internal_links_min": int(link_cfg.get("min", 3)),
        "contextual_internal_links_max": int(link_cfg.get("max", 5)),
        "parent_hub_link_required": True,
        "commercial_links_max": int(rubric.get("commercial_links_max", 1)),
        "business_facts": trusted,
        "approved_price_data": trusted.get("approved_models", {}),
        "unapproved_models": trusted.get("unapproved_models", []),
        "unapproved_price_message": trusted.get("unapproved_price_message", ""),
        "deposit_wording": (trusted.get("deposit_policy") or {}).get(
            "standard_wording", ""),
        "protected_intents": protected,
        "neighbor_topics": neighboring_topics(matrix, row),
        "url_base": base,
        "baseurl": site.get("baseurl", "/shop"),
        "word_count_scope": "main editorial content only",
        "anchors": "descriptive and diverse; no 'xem thêm'/'tại đây'/'click here'",
        "h1_per_article": 1,
        "schema": "Article",
        "breadcrumb": "required",
    }


def build_manifest(batch_id, rows, rubric=None, facts=None, ownership=None,
                  site=None, matrix=None):
    """Batch manifest consumed by an authorized AI writer.

    writer_context carries the full production standard so a real writer
    knows the target length, link rules, parent hub, allowed targets,
    commercial link limit, business facts and protected intents.
    """
    rubric = rubric or {}
    length_cfg = rubric.get("article_length", {})
    link_cfg = rubric.get("contextual_internal_links", {})
    site = site or {}
    writer_context = {
        "standard": "Mr Tú Content Factory production standard",
        "target_min_words": int(length_cfg.get("target_min_words", 1600)),
        "target_max_words": int(length_cfg.get("target_max_words", 2000)),
        "word_count_scope": "main editorial content only (article/main "
                            "container; nav/header/footer/breadcrumb/chatbot "
                            "excluded)",
        "contextual_internal_links_min": int(link_cfg.get("min", 3)),
        "contextual_internal_links_max": int(link_cfg.get("max", 5)),
        "parent_hub_link_required": True,
        "commercial_links_max": int(rubric.get("commercial_links_max", 1)),
        "anchors": "descriptive and diverse; no 'xem thêm'/'tại đây'/'click here'; "
                   "no repeated exact-match anchors",
        "primary_intents_per_article": 1,
        "h1_per_article": 1,
        "canonical": "self-referencing",
        "schema": "Article",
        "breadcrumb": "required",
        "sources": "required for rows with requires_sources=true "
                   "(official Vietnamese government/legal domains preferred)",
        "business_facts_file": "config/business-facts.json (trusted section only; "
                               "requires_owner_confirmation values are null and "
                               "must never be published)",
        "protected_intents_file": "config/seo-ownership.json",
        "url_base": (site or {}).get("site_url", "https://thuexemayhanoi.github.io/shop"),
    }
    return {
        "batch_id": batch_id,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "writer_context": writer_context,
        "articles": [
            {
                "article_id": r.get("article_id"),
                "category": r.get("category"),
                "primary_keyword": r.get("primary_keyword"),
                "secondary_keywords": r.get("secondary_keywords"),
                "search_intent": r.get("search_intent"),
                "working_title": r.get("working_title"),
                "slug": r.get("slug"),
                "output_path": r.get("output_path"),
                "parent_hub": r.get("parent_hub"),
                "requires_sources": r.get("requires_sources"),
                "source_notes": r.get("source_notes"),
                "internal_link_targets": r.get("internal_link_targets"),
                "commercial_link_target": r.get("commercial_link_target"),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# QA of a single written article (pure w.r.t. inputs)
# ---------------------------------------------------------------------------

def qa_article(html_path, matrix, ownership, facts, rubric):
    """Run the 3 gate tools on one article. Return result dict."""
    article = lib.Article(html_path)
    errors = lib.validate_article(article, matrix, ownership, facts, rubric)
    fails, warns, flags = lib.check_cannibalization(article, ownership, matrix, facts)
    (score, status, sections, criticals, warnings, recs, rflags, prod) = \
        score_article_module.score_article(article, matrix, ownership, facts, rubric)
    if errors or criticals:
        status = "FAIL"
    result = {
        "article_id": None,
        "path": html_path,
        "validation_errors": errors,
        "cannibalization_failures": fails,
        "cannibalization_warnings": warns,
        "cannibalization_flags": flags,
        "score": score,
        "status": status,  # PASS / REVIEW / FAIL
        "critical_failures": criticals,
        "review_flags": rflags,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# Batch state file IO
# ---------------------------------------------------------------------------

def batches_dir(repo_root):
    return os.path.join(repo_root, "data", "batches")


def lock_path(repo_root, batch_id):
    return os.path.join(batches_dir(repo_root), batch_id + ".lock")


def acquire_lock(repo_root, batch_id):
    """Simple lock: refuses if a fresh (<24h) lock exists for another run."""
    os.makedirs(batches_dir(repo_root), exist_ok=True)
    lp = lock_path(repo_root, batch_id)
    if os.path.exists(lp):
        try:
            ts = datetime.datetime.fromisoformat(io.open(lp, encoding="utf-8").read().strip())
            if datetime.datetime.now() - ts < datetime.timedelta(hours=24):
                return False
        except ValueError:
            pass
    with io.open(lp, "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds"))
    return True


def release_lock(repo_root, batch_id):
    try:
        os.remove(lock_path(repo_root, batch_id))
    except OSError:
        pass


def update_matrix_statuses(repo_root, updates):
    """updates: {article_id: {field: value}} — persists to content-matrix.csv."""
    path = os.path.join(repo_root, "data", "content-matrix.csv")
    with io.open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames)
        rows = list(reader)
    for r in rows:
        upd = updates.get(r.get("article_id"))
        if upd:
            r.update(upd)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)


def write_report(repo_root, report):
    d = os.path.join(repo_root, "reports", "batches")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, report["batch_id"] + ".json")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    md = os.path.join(d, report["batch_id"] + ".md")
    with io.open(md, "w", encoding="utf-8") as f:
        f.write(report_markdown(report))
    return p


def report_markdown(report):
    L = []
    L.append("# Batch report %s" % report.get("batch_id"))
    L.append("")
    L.append("- started_at: %s" % report.get("started_at"))
    L.append("- finished_at: %s" % report.get("finished_at"))
    L.append("- writer_provider: %s" % report.get("writer_provider"))
    L.append("- commit_sha: %s" % report.get("commit_sha"))
    L.append("- requested: %s | written: %s | pass: %s | published: %s" %
             (report.get("requested"), report.get("written"),
              report.get("pass"), report.get("published")))
    L.append("- review: %s | repair: %s | fail: %s | blocked: %s | provider_errors: %s" %
             (report.get("review"), report.get("repair"),
              report.get("fail"), report.get("blocked"),
              report.get("provider_errors")))
    L.append("- scores: avg %s | min %s | max %s | repair_count: %s" %
             (report.get("average_score"), report.get("min_score"),
              report.get("max_score"), report.get("repair_count")))
    L.append("")
    L.append("| article_id | output_path | status | score | repairs | cannibalization | notes |")
    L.append("|---|---|---|---|---|---|---|")
    for a in report.get("articles", []):
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            a.get("article_id"), a.get("output_path"), a.get("outcome"),
            a.get("score"), a.get("repair_attempts"),
            ("FAIL" if a.get("cannibalization_failures") else
             ("warn" if a.get("cannibalization_warnings") else "PASS")),
            "; ".join((a.get("quality_failures") or [])[:3])))
    return "\n".join(L) + "\n"


def write_manifest(repo_root, manifest):
    d = batches_dir(repo_root)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, manifest["batch_id"] + ".json")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return p


# ---------------------------------------------------------------------------
# Writer pipeline for ONE article (isolated; one failure never blocks others)
# ---------------------------------------------------------------------------

def _qa_report_for_writer(res):
    """Compact QA report sent back to the writer for repair."""
    return {
        "score": res.get("score"),
        "status": res.get("status"),
        "validation_errors": res.get("validation_errors"),
        "critical_failures": res.get("critical_failures"),
        "review_flags": res.get("review_flags"),
        "cannibalization_failures": res.get("cannibalization_failures"),
        "cannibalization_warnings": res.get("cannibalization_warnings"),
        "warnings": res.get("warnings"),
    }


def process_article(row, matrix, ownership, facts, rubric, repo_root,
                    provider, site=None, dry_run=False, resume_only=False):
    """Full lifecycle of one article: write -> QA -> repair loop.

    Returns (updates, entry). Never raises for a single-article failure —
    provider/QA errors are captured in the entry so the other 49 continue.
    """
    aid = row.get("article_id")
    out_rel = (row.get("output_path") or "").strip()
    out_abs = os.path.join(repo_root, out_rel) if out_rel else ""
    entry = {
        "article_id": aid,
        "output_path": out_rel,
        "outcome": None,
        "score": None,
        "repair_attempts": 0,
        "quality_failures": [],
        "cannibalization_failures": [],
        "cannibalization_warnings": [],
        "provider_error": None,
    }
    updates = {}
    prior_attempts = repair_attempts(row.get("notes", ""))

    status = (row.get("status") or "").strip()
    if status in ("PASS", "PUBLISHED"):
        # Never rewritten. Crash/resume safety invariant.
        entry["outcome"] = "SKIP_PASS_PUBLISHED"
        return updates, entry

    if not out_rel:
        entry["outcome"] = "FAIL"
        entry["quality_failures"] = ["missing output_path"]
        updates[aid] = {"status": "FAIL", "quality_status": "FAIL",
                        "last_checked": today()}
        return updates, entry

    html = None
    if os.path.isfile(out_abs) and not dry_run:
        # Resume: QA the existing file first; rewrite only if QA says so.
        pass  # no file yet: falls through to the write step below
    elif not resume_only:
        if provider is None:
            entry["outcome"] = "WRITER_NOT_CONFIGURED"
            return updates, entry
        if dry_run:
            entry["outcome"] = "WOULD_WRITE"
            return updates, entry
        # ---- real write ----
        if not os.path.isfile(out_abs) or status in ("WRITING", "QA", "REPAIR", "REVIEW"):
            ctx = build_writer_context(row, matrix, ownership, facts, rubric,
                                       site, repo_root)
            updates[aid] = {"status": "WRITING"}
            try:
                html = provider.write_article(row, ctx)
            except article_writer.WriterSecretMissing as e:
                entry["outcome"] = "WRITER_SECRET_MISSING"
                entry["provider_error"] = str(e)
                updates = {aid: {"status": "PLANNED"}}  # row stays PLANNED
                return updates, entry
            except Exception as e:  # provider timeout/error -> safe stop for row
                entry["outcome"] = "PROVIDER_ERROR"
                entry["provider_error"] = str(e)[:300]
                # row returns to PLANNED for a later run (no durable fake state)
                updates = {aid: {"status": "PLANNED"}}
                return updates, entry
            if not os.path.isdir(os.path.dirname(out_abs)):
                os.makedirs(os.path.dirname(out_abs), exist_ok=True)
            with io.open(out_abs, "w", encoding="utf-8") as f:
                f.write(html)
            updates[aid] = {"status": "QA"}

    if dry_run:
        entry["outcome"] = "WOULD_QA" if os.path.isfile(out_abs) else "WOULD_WRITE"
        return updates, entry

    if not os.path.isfile(out_abs):
        entry["outcome"] = "NOT_WRITTEN"
        return updates, entry

    # ---- QA + repair loop ----
    attempts = prior_attempts
    while True:
        res = qa_article(out_abs, matrix, ownership, facts, rubric)
        entry["score"] = res["score"]
        entry["quality_failures"] = (res.get("validation_errors") or [])[:10] + \
            (res.get("critical_failures") or [])[:10]
        entry["cannibalization_failures"] = res.get("cannibalization_failures") or []
        entry["cannibalization_warnings"] = res.get("cannibalization_warnings") or []
        if res["status"] == "PASS":
            entry["outcome"] = "PASS"
            updates[aid] = {"status": "PASS", "quality_status": "PASS",
                            "score": str(res["score"]),
                            "last_checked": today()}
            return updates, entry
        if res["status"] == "FAIL":
            # FAIL is never auto-published and (per current policy) never
            # silently converted to PASS. Recorded and kept.
            entry["outcome"] = "FAIL"
            updates[aid] = {"status": "FAIL", "quality_status": "FAIL",
                            "score": str(res["score"]),
                            "last_checked": today()}
            return updates, entry
        # REVIEW: repair only the identified problems, max 3 attempts total
        if attempts >= MAX_REPAIR_ATTEMPTS or provider is None:
            entry["outcome"] = "BLOCKED" if attempts >= MAX_REPAIR_ATTEMPTS else "REVIEW_NO_WRITER"
            updates[aid] = {"status": "BLOCKED" if attempts >= MAX_REPAIR_ATTEMPTS else "REVIEW",
                            "quality_status": "BLOCKED" if attempts >= MAX_REPAIR_ATTEMPTS else "REVIEW",
                            "score": str(res["score"]),
                            "notes": note_repair(row.get("notes", ""), attempts),
                            "last_checked": today()}
            return updates, entry
        try:
            with io.open(out_abs, encoding="utf-8") as f:
                original_html = f.read()
            repaired = provider.repair_article(
                row, build_writer_context(row, matrix, ownership, facts,
                                          rubric, site, repo_root),
                original_html, _qa_report_for_writer(res))
            with io.open(out_abs, "w", encoding="utf-8") as f:
                f.write(repaired)
        except Exception as e:
            entry["provider_error"] = ("repair: %s" % str(e))[:300]
            # keep the last QA verdict; a repair API failure must not fake PASS
            entry["outcome"] = "PROVIDER_ERROR"
            updates[aid] = {"status": "REVIEW", "quality_status": "REVIEW",
                            "score": str(res["score"]),
                            "notes": note_repair(row.get("notes", ""), attempts),
                            "last_checked": today()}
            return updates, entry
        attempts += 1
        entry["repair_attempts"] = attempts - prior_attempts


class _Guard(object):
    """Cost guard: stop generating NEW articles when provider errors spike."""

    def __init__(self):
        self.lock = threading.Lock()
        self.attempted = 0
        self.errors = 0
        self.stopped = False

    def note_attempt(self):
        with self.lock:
            self.attempted += 1

    def note_error(self):
        with self.lock:
            self.errors += 1
            if (self.errors >= PROVIDER_ERROR_FLOOR and
                    self.errors > PROVIDER_ERROR_RATE * max(self.attempted, 1)):
                self.stopped = True

    def should_stop(self):
        with self.lock:
            return self.stopped


def run_writer_pipeline(rows, matrix, ownership, facts, rubric, repo_root,
                        provider, site=None, dry_run=False, resume_only=False,
                        concurrency=1):
    """Write + QA every row independently. One failure never blocks others.

    Sequential by default (reliability over speed); bounded 1-3 concurrency
    via ThreadPoolExecutor when explicitly requested."""
    guard = _Guard()
    results = []

    def work(row):
        if not dry_run and provider is not None:
            guard.note_attempt()
        updates, entry = process_article(
            row, matrix, ownership, facts, rubric, repo_root, provider,
            site, dry_run=dry_run, resume_only=resume_only)
        if entry.get("outcome") in ("PROVIDER_ERROR", "WRITER_SECRET_MISSING"):
            guard.note_error()
        return updates, entry

    todo = list(rows)

    def skipped(row):
        return ({}, {"article_id": row.get("article_id"),
                     "output_path": row.get("output_path"),
                     "outcome": "SKIPPED_PROVIDER_ERRORS",
                     "score": None, "repair_attempts": 0,
                     "quality_failures": [],
                     "cannibalization_failures": [],
                     "cannibalization_warnings": [],
                     "provider_error": None})

    if concurrency <= 1:
        for row in todo:
            if not dry_run and guard.should_stop():
                results.append(skipped(row))
                continue
            results.append(work(row))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = []
            for row in todo:
                if not dry_run and guard.should_stop():
                    results.append(skipped(row))
                    continue
                futures.append(ex.submit(work, row))
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())

    updates = {}
    articles = []
    for upd, entry in results:
        updates.update(upd)
        articles.append(entry)
    return updates, articles, guard


# ---------------------------------------------------------------------------
# QA-only policy for pre-existing files (kept for backward compatibility)
# ---------------------------------------------------------------------------

def run_qa_for_rows(rows, matrix, ownership, facts, rubric, repo_root):
    """QA each row whose file exists. Never lets one failure block others.
    REVIEW rows get up to MAX_REPAIR_ATTEMPTS attempts (no writer -> BLOCKED)."""
    updates = {}
    report_articles = []
    for r in rows:
        aid = r.get("article_id")
        path = os.path.join(repo_root, r.get("output_path") or "")
        entry = {"article_id": aid, "output_path": r.get("output_path"),
                 "outcome": None, "score": None, "repair_attempts": 0}
        if not (r.get("output_path") and os.path.isfile(path)):
            entry["outcome"] = "NOT_WRITTEN"
            report_articles.append(entry)
            continue
        res = qa_article(path, matrix, ownership, facts, rubric)
        entry["score"] = res["score"]
        entry["article_id"] = res["article_id"] or aid
        if res["status"] == "PASS":
            entry["outcome"] = "PASS"
            updates[aid] = {"status": "PASS", "quality_status": "PASS",
                            "score": str(res["score"]),
                            "last_checked": today()}
        elif res["status"] == "REVIEW":
            entry["outcome"] = "REVIEW"
            updates[aid] = {"status": "REVIEW", "quality_status": "REVIEW",
                            "score": str(res["score"]),
                            "last_checked": today()}
        else:
            entry["outcome"] = "FAIL"
            updates[aid] = {"status": "FAIL", "quality_status": "FAIL",
                            "score": str(res["score"]),
                            "last_checked": today()}
        report_articles.append(entry)
    return updates, report_articles


def today():
    return datetime.date.today().isoformat()


def repair_attempts(notes):
    import re as _re
    m = _re.search(r"repair:(\d+)", notes or "")
    return int(m.group(1)) if m else 0


def note_repair(notes, n):
    import re as _re
    s = _re.sub(r"repair:\d+", "repair:%d" % n, notes or "")
    if "repair:%d" % n not in s:
        s = (s + " " if s.strip() else "") + "repair:%d" % n
    return s.strip()


def summarize(report_articles):
    scores = [a.get("score") for a in report_articles
              if isinstance(a.get("score"), (int, float))]
    return {
        "pass": len([a for a in report_articles if a.get("outcome") == "PASS"]),
        "review": len([a for a in report_articles
                       if a.get("outcome") in ("REVIEW", "REVIEW_NO_WRITER")]),
        "repair": len([a for a in report_articles if (a.get("repair_attempts") or 0) > 0]),
        "fail": len([a for a in report_articles if a.get("outcome") == "FAIL"]),
        "blocked": len([a for a in report_articles if a.get("outcome") == "BLOCKED"]),
        "provider_errors": len([a for a in report_articles
                                if a.get("outcome") in ("PROVIDER_ERROR",
                                                        "WRITER_SECRET_MISSING")]),
        "average_score": (round(sum(scores) / len(scores), 1) if scores else None),
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "repair_count": sum(a.get("repair_attempts") or 0 for a in report_articles),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_kill_switch(repo_root):
    """Factory kill switch: config/content-factory.json. Missing = enabled."""
    p = os.path.join(repo_root, "config", "content-factory.json")
    if not os.path.isfile(p):
        return {"enabled": True, "scheduled_runs_enabled": True}
    try:
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"enabled": True, "scheduled_runs_enabled": True}


def main_func(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--batch", help="batch id, e.g. BATCH-001")
    mode.add_argument("--next", action="store_true", help="first batch with PLANNED rows")
    ap.add_argument("--prepare", action="store_true",
                    help="claim rows and write batch manifest only")
    ap.add_argument("--resume", action="store_true",
                    help="QA unfinished rows only; never rewrite PASS/PUBLISHED")
    ap.add_argument("--pilot", action="store_true",
                    help="pilot mode: BATCH-001 only, max 50, no chaining")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would run; write nothing")
    ap.add_argument("--mark-published", action="store_true",
                    help="flip PASS rows with existing files to PUBLISHED "
                         "(call only AFTER the commit reached MAIN)")
    ap.add_argument("--scheduled", action="store_true",
                    help="cron entry point: honors config/content-factory.json "
                         "kill switch and FACTORY_COMPLETE detection")
    ap.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE,
                    help="max articles per run (default 50, max 50)")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="writer calls in parallel (default 1, max 3)")
    args = ap.parse_args(argv)

    repo_root = lib.ROOT
    batch_size = min(args.batch_size, MAX_BATCH_SIZE)
    concurrency = max(1, min(args.concurrency, MAX_CONCURRENCY))

    kill = _load_kill_switch(repo_root)
    if args.scheduled and not kill.get("enabled", True):
        print("FACTORY_PAUSED: config/content-factory.json enabled=false. "
              "No changes made.")
        return 0
    if args.scheduled and not kill.get("scheduled_runs_enabled", True):
        print("FACTORY_SCHEDULE_PAUSED: scheduled_runs_enabled=false. "
              "No changes made.")
        return 0

    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return EXIT_ERROR

    # ------- pilot mode: BATCH-001 only, never chained -------
    if args.pilot:
        batch_id = "BATCH-001"
        rows = batch_rows(matrix, batch_id)
        if not rows:
            print("ERROR: BATCH-001 not found — pilot aborted.")
            return EXIT_USAGE
        if args.batch and args.batch != "BATCH-001":
            print("ERROR: pilot mode may only run BATCH-001.")
            return EXIT_USAGE
    else:
        batch_id = args.batch
        if args.next or (not batch_id and not args.resume and
                         not args.mark_published):
            batch_id = next_batch_id(matrix)
            if not batch_id:
                if args.scheduled:
                    print("FACTORY_COMPLETE: no PLANNED/WRITING/QA/REPAIR "
                          "rows remain. No changes made.")
                    return 0
                print("No PLANNED rows left — all batches done.")
                return 0
            print("Next batch: %s" % batch_id)

    if batch_id is None and args.resume:
        batch_id = next_batch_id(matrix)
        if not batch_id:
            print("No unfinished rows.")
            return 0

    rows = batch_rows(matrix, batch_id) if batch_id else []
    if not rows:
        print("ERROR: batch %s not found" % batch_id)
        return EXIT_USAGE

    if not acquire_lock(repo_root, batch_id):
        print("LOCKED: another runner holds %s (data/batches/%s.lock, <24h old)."
              % (batch_id, batch_id))
        return EXIT_USAGE
    try:
        started_at = datetime.datetime.now().isoformat(timespec="seconds")

        # ---------------- prepare-only mode ----------------
        if args.prepare:
            claim = select_claim_rows(rows, batch_size)
            if not claim:
                print("No PLANNED rows in %s (statuses: %s)"
                      % (batch_id, sorted({(r.get("status") or "?") for r in rows})))
                return 0
            manifest = build_manifest(batch_id, claim, rubric, facts,
                                     ownership, site, matrix)
            provider = None
            configured = False
            try:
                provider = article_writer.get_provider()
                configured = provider.is_configured()
            except Exception:
                configured = False
            if not configured:
                write_manifest(repo_root, manifest)
                if _secret_missing(provider):
                    print("WRITER_SECRET_MISSING: provider selected but its "
                          "API key is absent. Manifest written to "
                          "data/batches/%s.json; rows stay PLANNED; no "
                          "content generated." % batch_id)
                    return article_writer.EXIT_WRITER_SECRET_MISSING
                print("WRITER_NOT_CONFIGURED: manifest written to "
                      "data/batches/%s.json; NO article generated, matrix "
                      "rows left PLANNED. Configure WRITER_PROVIDER + its "
                      "secret (GitHub Actions Secrets) then run the batch "
                      "for real." % batch_id)
                return article_writer.EXIT_WRITER_NOT_CONFIGURED
            write_manifest(repo_root, manifest)
            print("PREPARED %s: writer '%s' configured; %d articles ready. "
                  "Run without --prepare to write, QA and repair for real."
                  % (batch_id, getattr(provider, "name", "?"), len(claim)))
            return 0

        # ---------------- mark-published mode ----------------
        if args.mark_published:
            ready = [r for r in rows
                     if (r.get("status") or "").strip() == "PASS"
                     and os.path.isfile(os.path.join(repo_root, r.get("output_path") or ""))]
            if not ready:
                print("No PASS-with-file rows to mark PUBLISHED in %s." % batch_id)
                return 0
            update_matrix_statuses(repo_root, {r["article_id"]: {"status": "PUBLISHED"}
                                              for r in ready})
            print("PUBLISHED %d articles in %s (files already on MAIN)." %
                  (len(ready), batch_id))
            return 0

        # ---------------- dry run ----------------
        if args.dry_run:
            claim = select_claim_rows(rows, batch_size)
            resume = select_resume_rows(rows, repo_root, batch_size)
            print("DRY RUN %s: %d PLANNED claimable, %d unfinished files, "
                  "statuses: %s" % (batch_id, len(claim), len(resume),
                                    sorted({(r.get("status") or "?") for r in rows})))
            return 0

        # ---------------- real run / resume ----------------
        resume_rows = select_resume_rows(rows, repo_root, batch_size)
        claim_rows = []
        provider = article_writer.get_provider()
        provider_name = getattr(provider, "name", "none")
        if len(resume_rows) < batch_size:
            want = batch_size - len(resume_rows)
            seen_ids = set()
            candidate_claim = []
            # crash recovery: re-claim WRITING/QA/REPAIR rows that never
            # produced a file, then fresh PLANNED rows
            for r in (select_stale_rows(rows, repo_root, want) +
                      select_claim_rows(rows, want)):
                if r["article_id"] not in seen_ids:
                    seen_ids.add(r["article_id"])
                    candidate_claim.append(r)
            candidate_claim = candidate_claim[:want]
            # A real writer must be configured before PLANNED rows are claimed.
            try:
                configured = provider.is_configured()
            except Exception:
                configured = False
            if candidate_claim and configured:
                claim_rows = candidate_claim
            elif candidate_claim and not resume_rows:
                # nothing resumable AND no writer -> safe stop
                manifest = build_manifest(batch_id, candidate_claim, rubric,
                                          facts, ownership, site, matrix)
                write_manifest(repo_root, manifest)
                if _secret_missing(provider):
                    print("WRITER_SECRET_MISSING: provider '%s' selected but "
                          "its API key is not configured. Batch %s prepared as "
                          "manifest only; rows stay PLANNED; no content "
                          "generated." % (provider_name, batch_id))
                    return article_writer.EXIT_WRITER_SECRET_MISSING
                print("WRITER_NOT_CONFIGURED: batch %s prepared as manifest; "
                      "no content generated." % batch_id)
                return article_writer.EXIT_WRITER_NOT_CONFIGURED

        todo = claim_rows + resume_rows
        if not todo:
            print("Nothing to do in %s (no claimable PLANNED rows without a "
                  "writer, no unfinished files)." % batch_id)
            return 0

        # Durable WRITING claim before the first API call (crash-safe resume).
        if claim_rows:
            update_matrix_statuses(repo_root,
                                   {r["article_id"]: {"status": "WRITING"}
                                    for r in claim_rows})
            matrix = lib.load_matrix()
            rows = batch_rows(matrix, batch_id)
            by_id = {r["article_id"]: r for r in rows}
            todo = [by_id.get(r["article_id"], r) for r in todo]

        updates, articles, guard = run_writer_pipeline(
            todo, matrix, ownership, facts, rubric, repo_root, provider,
            site=site, resume_only=False, concurrency=concurrency)

        # Persist per-article outcomes (idempotent; PASS/PUBLISHED untouched).
        update_matrix_statuses(repo_root, updates)

        stats = summarize(articles)
        secret_missing = any(a.get("outcome") == "WRITER_SECRET_MISSING"
                            for a in articles)
        report = {
            "batch_id": batch_id,
            "started_at": started_at,
            "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "requested": len(todo),
            "writer_provider": provider_name,
            "written": len([a for a in articles if a.get("outcome") not in
                            ("NOT_WRITTEN", "WRITER_NOT_CONFIGURED",
                             "WRITER_SECRET_MISSING", "SKIPPED_PROVIDER_ERRORS")]),
            "published": 0,  # set only after the commit reaches MAIN
            "commit_sha": os.environ.get("GITHUB_SHA") or None,
            "articles": articles,
        }
        report.update(stats)
        rp = write_report(repo_root, report)
        print(json.dumps({k: v for k, v in report.items() if k != "articles"},
                         ensure_ascii=False))
        print("report: %s" % rp)
        if guard.should_stop():
            print("GUARD: provider error rate exceeded threshold — new "
                  "generation stopped; completed results preserved.")
        if secret_missing:
            print("WRITER_SECRET_MISSING: at least one article could not be "
                  "written because the API key is absent. Rows stayed PLANNED.")
            return article_writer.EXIT_WRITER_SECRET_MISSING
        if report["fail"]:
            return EXIT_FAILS
        if report["review"] or report["blocked"]:
            return EXIT_ISSUES
        return 0
    finally:
        release_lock(repo_root, batch_id)


def _secret_missing(provider):
    """True when a named provider is selected but its secret is absent."""
    if provider is None or isinstance(provider, article_writer._NullProvider):
        return False
    try:
        env = getattr(provider, "env", None)
        if env is not None and provider.name == "mistral":
            return not bool((env.get("MISTRAL_API_KEY") or "").strip())
    except Exception:
        pass
    return False


if __name__ == "__main__":
    sys.exit(main_func())
