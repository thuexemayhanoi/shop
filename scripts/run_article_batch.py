#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch controller for the 2,000-article content factory.

Orchestrates ONE batch of up to 50 articles. It NEVER writes article
content itself — writing is delegated to scripts/article_writer.py, which
stops with WRITER_NOT_CONFIGURED (exit 5) unless a real provider is
configured.

Modes:
  --batch BATCH-001 --prepare   claim up to 50 PLANNED rows, mark them
                                WRITING, write data/batches/BATCH-001.json
  --batch BATCH-001 --resume    continue QA of unfinished rows (files that
                                already exist); never rewrites PASS/PUBLISHED
  --batch BATCH-001             full run: write (needs provider) then QA
  --next [--batch-size N]       pick the first batch that still has PLANNED
                                rows and run it (prepare only, without writer)

QA per article = validate_article + check_cannibalization + score_article.
PASS -> publishable. REVIEW -> up to 3 repair attempts, then BLOCKED.
FAIL  -> never published. One bad article never blocks the others.

Reports: reports/batches/BATCH-XXX.json (gitignored).

Exit codes:
  0 ok / prepared
  1 usage or matrix violation
  2 non-blocking issues (some articles still REVIEW)
  3 batch had FAIL articles
  4 tool/config error
  5 WRITER_NOT_CONFIGURED
"""
import argparse
import csv
import datetime
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib
import article_writer
import score_article as score_article_module

MAX_BATCH_SIZE = 50
MAX_REPAIR_ATTEMPTS = 3
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


def build_manifest(batch_id, rows, rubric=None, facts=None, ownership=None,
                  site=None):
    """Batch manifest consumed by an external authorized AI writer.

    writer_context carries the full production standard so a real writer
    knows the target length, link rules, parent hub, allowed targets,
    commercial link limit, business facts and protected intents.
    """
    rubric = rubric or {}
    length_cfg = rubric.get("article_length", {})
    link_cfg = rubric.get("contextual_internal_links", {})
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
        "score": score,
        "status": status,  # PASS / REVIEW / FAIL
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
    return p


def write_manifest(repo_root, manifest):
    d = batches_dir(repo_root)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, manifest["batch_id"] + ".json")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return p


# ---------------------------------------------------------------------------
# QA + publish policy for a set of rows (pure; unit-testable)
# ---------------------------------------------------------------------------

def run_qa_for_rows(rows, matrix, ownership, facts, rubric, repo_root):
    """QA each row whose file exists. Never lets one failure block others.
    REVIEW rows get up to MAX_REPAIR_ATTEMPTS attempts (no writer -> BLOCKED).
    PASS rows are marked publishable (PUBLISHED is set only after the actual
    git commit to MAIN)."""
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
        attempts = 0
        # Repair loop: without a configured writer no automatic repair is
        # possible, so REVIEW stays REVIEW here and the orchestrator marks
        # BLOCKED after MAX_REPAIR_ATTEMPTS recorded attempts.
        if res["status"] == "PASS":
            entry["outcome"] = "PASS"
            updates[aid] = {"status": "PASS", "quality_status": "PASS",
                            "score": str(res["score"]),
                            "last_checked": today()}
        elif res["status"] == "REVIEW":
            # count previous recorded attempts via notes field
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main_func(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--batch", help="batch id, e.g. BATCH-001")
    mode.add_argument("--next", action="store_true", help="first batch with PLANNED rows")
    ap.add_argument("--prepare", action="store_true",
                    help="claim rows and write batch manifest only")
    ap.add_argument("--resume", action="store_true",
                    help="QA unfinished rows only; never rewrite PASS/PUBLISHED")
    ap.add_argument("--mark-published", action="store_true",
                    help="flip PASS rows with existing files to PUBLISHED "
                         "(call only AFTER the commit reached MAIN)")
    ap.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE,
                    help="max articles per run (default 50, max 50)")
    args = ap.parse_args(argv)

    repo_root = lib.ROOT
    batch_size = min(args.batch_size, MAX_BATCH_SIZE)
    if args.batch_size > MAX_BATCH_SIZE:
        print("NOTE: batch-size capped to %d" % MAX_BATCH_SIZE)

    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return EXIT_ERROR

    batch_id = args.batch
    if args.next or (not batch_id and not args.resume):
        batch_id = next_batch_id(matrix)
        if not batch_id:
            print("No PLANNED rows left — all batches done.")
            return 0
        print("Next batch: %s" % batch_id)

    rows = batch_rows(matrix, batch_id)
    if not rows:
        print("ERROR: batch %s not found" % batch_id)
        return EXIT_USAGE

    if not acquire_lock(repo_root, batch_id):
        print("LOCKED: another runner holds %s (data/batches/%s.lock, <24h old)."
              % (batch_id, batch_id))
        return EXIT_USAGE
    try:
        # ---------------- prepare-only mode ----------------
        if args.prepare:
            claim = select_claim_rows(rows, batch_size)
            if not claim:
                print("No PLANNED rows in %s (statuses: %s)"
                      % (batch_id, sorted({(r.get("status") or "?") for r in rows})))
                return 0
            manifest = build_manifest(batch_id, claim, rubric, facts, ownership, site)
            # Probe the writer BEFORE claiming. Without a real provider we
            # must NOT leave durable WRITING claims in the matrix ledger —
            # rows stay PLANNED and remain safely claimable later. The
            # manifest is still produced as an artifact for an external
            # authorized writer.
            try:
                article_writer.write_article(claim[0], {"mode": "prepare-probe"})
            except article_writer.WriterNotConfigured:
                write_manifest(repo_root, manifest)
                print("WRITER_NOT_CONFIGURED: manifest written to "
                      "data/batches/%s.json; NO article generated, matrix rows "
                      "left PLANNED (no durable WRITING claim without a writer). "
                      "Run an authorized AI writer (e.g. Mistral agent) on the "
                      "manifest, then use --resume." % batch_id)
                return article_writer.EXIT_WRITER_NOT_CONFIGURED
            # A real writer is configured: claim the rows durably now.
            write_manifest(repo_root, manifest)
            updates = {r["article_id"]: {"status": "WRITING"} for r in claim}
            update_matrix_statuses(repo_root, updates)
            print("PREPARED %s: %d articles claimed WRITING, manifest at "
                  "data/batches/%s.json" % (batch_id, len(claim), batch_id))
            print("writer provider present — refusing inline generation; "
                  "use --resume after the writer produced files.")
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

        # ---------------- resume / run mode ----------------
        if args.resume:
            todo = select_resume_rows(rows, repo_root, batch_size)
        else:
            # full run: writer must exist to create missing files
            claim = select_claim_rows(rows, batch_size)
            try:
                article_writer.write_article(claim[0], {"mode": "run-probe"}) if claim else None
            except article_writer.WriterNotConfigured:
                manifest = build_manifest(batch_id, claim, rubric, facts, ownership, site)
                write_manifest(repo_root, manifest)
                print("WRITER_NOT_CONFIGURED: batch %s prepared as manifest; "
                      "no content generated." % batch_id)
                return article_writer.EXIT_WRITER_NOT_CONFIGURED
            todo = [r for r in rows
                    if (r.get("status") or "").strip() in ("WRITING", "QA", "REPAIR", "REVIEW")
                    and os.path.isfile(os.path.join(repo_root, r.get("output_path") or ""))]

        if not todo:
            print("Nothing to QA in %s (no unfinished article files)." % batch_id)
            return 0

        updates, articles = run_qa_for_rows(todo, matrix, ownership, facts,
                                            rubric, repo_root)
        # REVIEW -> BLOCKED after max recorded repair attempts
        for r in todo:
            if r["article_id"] in updates and updates[r["article_id"]]["status"] == "REVIEW":
                attempts = repair_attempts(r.get("notes", ""))
                if attempts + 1 >= MAX_REPAIR_ATTEMPTS:
                    updates[r["article_id"]]["status"] = "BLOCKED"
                    updates[r["article_id"]]["quality_status"] = "BLOCKED"
                    updates[r["article_id"]]["notes"] = note_repair(r.get("notes", ""), attempts + 1)
                else:
                    updates[r["article_id"]]["status"] = "REPAIR"
                    updates[r["article_id"]]["notes"] = note_repair(r.get("notes", ""), attempts + 1)
        update_matrix_statuses(repo_root, updates)

        for e in articles:
            if e["outcome"] == "REPAIR" or e["outcome"] == "REVIEW":
                e["outcome"] = updates.get(e["article_id"], {}).get("status", "REVIEW")
            if e["outcome"] in ("REVIEW", "REPAIR", "BLOCKED"):
                e["repair_attempts"] = repair_attempts(updates.get(e["article_id"], {}).get("notes", ""))

        report = {
            "batch_id": batch_id,
            "requested": len(todo),
            "written": len([a for a in articles if a["outcome"] != "NOT_WRITTEN"]),
            "pass": len([a for a in articles if a["outcome"] == "PASS"]),
            "published": 0,  # PUBLISHED is set only after the commit reaches MAIN
            "review": len([a for a in articles if a["outcome"] in ("REVIEW", "REPAIR")]),
            "fail": len([a for a in articles if a["outcome"] == "FAIL"]),
            "blocked": len([a for a in articles if a["outcome"] == "BLOCKED"]),
            "articles": articles,
        }
        rp = write_report(repo_root, report)
        print(json.dumps({k: v for k, v in report.items() if k != "articles"},
                         ensure_ascii=False))
        print("report: %s" % rp)
        if report["fail"]:
            return EXIT_FAILS
        if report["review"] or report["blocked"]:
            return EXIT_ISSUES
        return 0
    finally:
        release_lock(repo_root, batch_id)


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


if __name__ == "__main__":
    sys.exit(main_func())
