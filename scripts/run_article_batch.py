#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch controller for the API-free article factory.

Deterministic planner / QA / ledger / publisher. The Mistral agent (or a
human) is the WRITER: it reads the manifest and writes the article files
itself. This script never calls an AI API and never fabricates content.

Lifecycle (one row):
  PLANNED -> (agent claims via --prepare-agent) WRITING -> agent writes
  the file -> --qa -> PASS / FAIL / REVIEW -> (agent repairs the file,
  <= MAX_REPAIR_ATTEMPTS, notes carry repair:N) -> PASS | BLOCKED ->
  --publish lists the batch's PASS files -> agent pushes them to MAIN ->
  --mark-published flips them to PUBLISHED (published_date stamped).

Hard invariants:
  - The batch id is resolved ONCE per run and reused by every mode.
  - PASS / PUBLISHED rows are never rewritten or re-QA'd.
  - One bad article never blocks the others (per-article isolation).
  - Publish scope = PASS rows of THIS batch only, never other batches'.
  - An active unfinished batch (WRITING/QA/REPAIR/REVIEW) is resumed
    before any new PLANNED batch is started; FAIL/BLOCKED never block.
  - datePublished handed to the writer is the ACTUAL date (today),
    never the future planned_date (planning metadata only).
  - Repair budget: a REVIEW row gets at most MAX_REPAIR_ATTEMPTS repair
    passes; afterwards it is BLOCKED and never published.

Modes:
  --batch BATCH-001 | --next | --pilot (BATCH-001 only, max 50)
  --prepare-agent    claim PLANNED rows as WRITING + write the manifest
  --qa               deterministic QA of the batch's written files
  --publish          list the batch's PASS files (publish scope)
  --mark-published   flip the batch's PASS rows (files verified
                     present) to PUBLISHED + stamp published_date=today;
                     run ONLY after the push reached remote MAIN
  --dry-run          show what would run, change nothing durable
  --progress         write reports/batches/factory-progress.json

Reports: reports/batches/BATCH-XXX.{json,md} + factory-progress.json.

Exit codes:
  0 ok
  1 tool/config error
  2 usage error / locked batch
  3 batch had FAIL articles
  4 non-blocking issues (REVIEW/BLOCKED present)
"""
import argparse
import csv
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib

MAX_BATCH_SIZE = 50
MAX_REPAIR_ATTEMPTS = 3
ACTIVE_STATUSES = ("WRITING", "QA", "REPAIR", "REVIEW")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_FAILS = 3
EXIT_ISSUES = 4


# ---------------------------------------------------------------------------
# Matrix helpers (pure, unit-testable)
# ---------------------------------------------------------------------------

def production_rows(matrix):
    return [r for r in matrix if not lib.is_sample_row(r)]


def batch_rows(matrix, batch_id):
    return [r for r in production_rows(matrix)
            if (r.get("batch_id") or "").strip() == batch_id]


def active_batch_id(matrix):
    """First batch with unfinished rows (WRITING/QA/REPAIR/REVIEW), or None.
    FAIL/BLOCKED do NOT count as active — they never block later batches."""
    for r in production_rows(matrix):
        if (r.get("status") or "").strip() in ACTIVE_STATUSES:
            return (r.get("batch_id") or "").strip()
    return None


def next_batch_id(matrix):
    """Resolution order for --next: resume any active batch FIRST; only
    when no batch is unfinished select the first batch with PLANNED rows."""
    active = active_batch_id(matrix)
    if active:
        return active
    for r in production_rows(matrix):
        if (r.get("status") or "").strip() == "PLANNED":
            return (r.get("batch_id") or "").strip()
    return None


def select_claim_rows(rows, batch_size=MAX_BATCH_SIZE):
    batch_size = min(int(batch_size), MAX_BATCH_SIZE)
    return [r for r in rows
            if (r.get("status") or "").strip() == "PLANNED"][:batch_size]


def select_qa_rows(rows, repo_root, batch_size=MAX_BATCH_SIZE):
    """Rows to QA: this batch's active rows (WRITING/QA/REPAIR/REVIEW)
    whose file exists on disk at the REAL repository path."""
    batch_size = min(int(batch_size), MAX_BATCH_SIZE)
    out = []
    for r in rows:
        st = (r.get("status") or "").strip()
        path = r.get("output_path") or ""
        if (st in ACTIVE_STATUSES and path
                and os.path.isfile(os.path.join(repo_root, path))):
            out.append(r)
    return out[:batch_size]


def select_publish_rows(rows, repo_root):
    """PUBLISH SCOPE: PASS rows of THIS batch only, with existing files.
    Never returns rows of another batch."""
    out = []
    for r in rows:
        if (r.get("status") or "").strip() != "PASS":
            continue
        path = r.get("output_path") or ""
        if path and os.path.isfile(os.path.join(repo_root, path)):
            out.append(r)
    return out


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


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Writer context / manifest (deterministic; no prose)
# ---------------------------------------------------------------------------

def build_writer_context(row, matrix, ownership, facts, rubric, site,
                         repo_root=None):
    """Full production context for ONE article, handed to the external
    writer via the manifest. datePublished = ACTUAL publication date
    (today), NEVER the planned_date, which is planning metadata only."""
    rubric = rubric or {}
    length_cfg = rubric.get("article_length", {})
    link_cfg = rubric.get("contextual_internal_links", {})
    base = (site.get("site_url") or "").rstrip("/")
    out_path = (row.get("output_path") or "").strip()
    protected = []
    for p in (ownership or {}).get("protected_pages", []):
        for intent in p.get("primary_intents", []):
            protected.append({"page": p.get("path"), "intent": intent})
    trusted = dict(facts or {})
    trusted.pop("requires_owner_confirmation", None)  # never leak unverified
    return {
        "article_id": row.get("article_id"),
        "batch_id": row.get("batch_id"),
        "category": row.get("category"),
        "category_label": row.get("category"),
        "working_title": row.get("working_title"),
        "primary_keyword": row.get("primary_keyword"),
        "secondary_keywords": row.get("secondary_keywords") or "",
        "search_intent": row.get("search_intent"),
        "slug": row.get("slug"),
        "output_path": out_path,
        "parent_hub": row.get("parent_hub"),
        "eligible_internal_link_targets": (row.get("internal_link_targets")
                                           or "").replace(";", ", "),
        "commercial_link_target": row.get("commercial_link_target") or "",
        "requires_sources": row.get("requires_sources"),
        "source_notes": row.get("source_notes") or "",
        "source_requirements": ("cite >=1 approved official source URL "
            "(config/source-policy.json) in a visible 'Nguồn tham khảo' "
            "section; verify via web research; if unavailable BLOCK the "
            "article") if str(row.get("requires_sources", "")).strip().lower()
            in ("true", "yes", "1") else "none",
        "protected_intents": protected,
        "business_facts_policy": ("use ONLY config/business-facts.json "
            "trusted section; never assert unverified owner facts (hours, "
            "delivery, late-return policy); unapproved models must use the "
            "standard 'liên hệ để xác nhận giá hiện tại' wording"),
        "word_standard": {
            "target_min_words": int(length_cfg.get("target_min_words", 1600)),
            "target_max_words": int(length_cfg.get("target_max_words", 2000)),
            "review_min_words": int(length_cfg.get("review_min_words", 1200)),
            "review_max_words": int(length_cfg.get("review_max_words", 2300)),
            "scope": "main editorial content only",
        },
        "link_standard": {
            "contextual_internal_links_min": int(link_cfg.get("min", 3)),
            "contextual_internal_links_max": int(link_cfg.get("max", 5)),
            "parent_hub_link_required": True,
            "commercial_links_max": int(rubric.get("commercial_links_max", 1)),
            "anchors": "descriptive, diverse; no generic anchors",
        },
        "canonical_url": "%s/%s" % (base, out_path) if out_path else base,
        "date_published": today(),  # ACTUAL publication date, never planned
        "planned_date_note": "planned_date is planning metadata ONLY and "
                             "must never be used as datePublished",
        "url_base": base,
        "baseurl": site.get("baseurl", "/shop"),
        "author": row.get("author") or "Mr Tú",
        "neighbor_topics": neighboring_topics(matrix, row),
    }


def neighboring_topics(matrix, row, limit=6):
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


def build_manifest(batch_id, rows, matrix, ownership, facts, rubric, site,
                   repo_root=None):
    return {
        "batch_id": batch_id,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "writer": "external-agent",
        "writer_instructions": (
            "The Mistral agent writes these article files DIRECTLY (no API, "
            "no secrets). Write exactly the manifest rows. Each article: "
            "1600-2000 meaningful Vietnamese words, 3-5 contextual internal "
            "links (parent hub required, max 1 true commercial link, other "
            "links informational and relevant), exactly 1 H1, self canonical "
            "(canonical_url), Article schema + BreadcrumbList, no invented "
            "facts/prices/laws, datePublished = date_published (actual date). "
            "requires_sources=true rows need an approved official source "
            "URL in a 'Nguồn tham khảo' section."),
        "articles": [build_writer_context(r, matrix, ownership, facts,
                                           rubric, site, repo_root)
                     for r in rows],
    }


# ---------------------------------------------------------------------------
# Deterministic QA
# ---------------------------------------------------------------------------

def qa_article(html_path, matrix, ownership, facts, rubric):
    """Run the 3 gate tools on one article. Returns result dict."""
    article = lib.Article(html_path)
    errors = lib.validate_article(article, matrix, ownership, facts, rubric)
    fails, warns, flags = lib.check_cannibalization(article, ownership,
                                                    matrix, facts)
    import score_article as score_article_module
    (score, status, sections, criticals, warnings, recs, rflags, prod) = \
        score_article_module.score_article(article, matrix, ownership,
                                           facts, rubric)
    if errors or criticals:
        status = "FAIL"
    return {
        "article_id": None,
        "path": html_path,
        "validation_errors": errors,
        "cannibalization_failures": fails,
        "cannibalization_warnings": warns,
        "score": score,
        "status": status,
        "critical_failures": criticals,
        "review_flags": rflags,
        "warnings": warnings,
    }


def run_qa_for_batch(rows, matrix, ownership, facts, rubric, repo_root):
    """QA every unfinished row with a written file. Per-article isolation:
    one failure never blocks the others. REVIEW rows consume their repair
    budget (notes repair:N); after MAX_REPAIR_ATTEMPTS they become BLOCKED."""
    updates = {}
    articles = []
    for r in rows:
        aid = r.get("article_id")
        path = os.path.join(repo_root, r.get("output_path") or "")
        entry = {"article_id": aid, "output_path": r.get("output_path"),
                 "outcome": None, "score": None, "repair_attempts": 0,
                 "quality_failures": [], "cannibalization_failures": [],
                 "cannibalization_warnings": []}
        if not (r.get("output_path") and os.path.isfile(path)):
            entry["outcome"] = "NOT_WRITTEN"
            articles.append(entry)
            continue
        res = qa_article(path, matrix, ownership, facts, rubric)
        entry["score"] = res.get("score")
        entry["quality_failures"] = \
            (res.get("validation_errors") or []) + \
            (res.get("critical_failures") or [])[:10]
        entry["cannibalization_failures"] = res.get("cannibalization_failures") or []
        entry["cannibalization_warnings"] = res.get("cannibalization_warnings") or []
        if res["status"] == "PASS":
            entry["outcome"] = "PASS"
            updates[aid] = {"status": "PASS", "quality_status": "PASS",
                            "score": str(res["score"]),
                            "last_checked": today()}
        elif res["status"] == "FAIL":
            entry["outcome"] = "FAIL"
            updates[aid] = {"status": "FAIL", "quality_status": "FAIL",
                            "score": str(res["score"]),
                            "last_checked": today()}
        else:  # REVIEW
            attempts = repair_attempts(r.get("notes", ""))
            entry["repair_attempts"] = attempts
            if attempts + 1 >= MAX_REPAIR_ATTEMPTS:
                entry["outcome"] = "BLOCKED"
                updates[aid] = {"status": "BLOCKED",
                                 "quality_status": "BLOCKED",
                                 "score": str(res["score"]),
                                 "notes": note_repair(r.get("notes", ""),
                                                     attempts + 1),
                                 "last_checked": today()}
            else:
                entry["outcome"] = "REVIEW"
                updates[aid] = {"status": "REPAIR",
                                 "quality_status": "REVIEW",
                                 "score": str(res["score"]),
                                 "notes": note_repair(r.get("notes", ""),
                                                      attempts + 1),
                                 "last_checked": today()}
        articles.append(entry)
    return updates, articles


# ---------------------------------------------------------------------------
# File IO
# ---------------------------------------------------------------------------

def batches_dir(repo_root):
    return os.path.join(repo_root, "data", "batches")


def lock_path(repo_root, batch_id):
    return os.path.join(batches_dir(repo_root), batch_id + ".lock")


def acquire_lock(repo_root, batch_id):
    os.makedirs(batches_dir(repo_root), exist_ok=True)
    lp = lock_path(repo_root, batch_id)
    if os.path.exists(lp):
        try:
            ts = datetime.datetime.fromisoformat(
                io.open(lp, encoding="utf-8").read().strip())
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


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_report(repo_root, report):
    write_json(os.path.join(repo_root, "reports", "batches",
                            report["batch_id"] + ".json"), report)
    md = os.path.join(repo_root, "reports", "batches",
                      report["batch_id"] + ".md")
    with io.open(md, "w", encoding="utf-8") as f:
        f.write(report_markdown(report))
    return md


def _existing_report(repo_root, batch_id):
    p = os.path.join(repo_root, "reports", "batches", batch_id + ".json")
    if os.path.isfile(p):
        try:
            with io.open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _repair_attempts_from_notes(notes):
    m = re.search(r"repair:(\d+)", notes or "")
    return int(m.group(1)) if m else 0


def _parse_score(v):
    try:
        return int(str(v or "").strip())
    except ValueError:
        return None


def _resolve_published_sha(repo_root, prev):
    """Resolve the durable published_commit_sha for a batch report, in
    order: the previous batch report's recorded value (audit trail wins
    once set), then the publish checkpoint in factory-progress.json, then
    None. Mirrors scripts/js/factory.mjs resolvePublishedSha()."""
    if prev.get("published_commit_sha"):
        return prev.get("published_commit_sha")
    p = os.path.join(repo_root, "reports", "batches",
                     "factory-progress.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("published_commit_sha")
    except Exception:
        return None


def build_cumulative_report(batch_id, rows, run_articles, started_at,
                            repo_root):
    """CUMULATIVE batch report derived from the matrix rows of the batch.

    Every reserved member of the batch appears (not just the rows of the
    latest run); all state counts, scores and pass_publishable_now are
    computed from the CURRENT matrix truth, so the report can never claim
    fewer (or more) members than the ledger reserves. Run-level details of
    the current QA run are merged in; durable per-article details and the
    published_commit_sha audit trail are carried over from the previous
    report. Mirrors scripts/js/factory.mjs rebuildBatchReport().
    """
    prev = _existing_report(repo_root, batch_id) or {}
    prev_by_id = {a.get("article_id"): a
                  for a in (prev.get("articles") or [])}
    run_by_id = {a.get("article_id"): a for a in (run_articles or [])}
    members = sorted(rows, key=lambda r: r.get("article_id") or "")
    req_sources = lambda r: str(r.get("requires_sources") or "").strip().lower() in ("true", "yes", "1")  # noqa: E731
    articles = []
    for r in members:
        old = prev_by_id.get(r.get("article_id")) or {}
        run = run_by_id.get(r.get("article_id")) or {}
        articles.append({
            "article_id": r.get("article_id"),
            "output_path": r.get("output_path"),
            "outcome": (r.get("status") or "").strip(),
            "score": _parse_score(r.get("score")),
            "repair_attempts": (run.get("repair_attempts")
                                if run.get("repair_attempts") is not None
                                else (old.get("repair_attempts")
                                      if old.get("repair_attempts") is not None
                                      else _repair_attempts_from_notes(
                                          r.get("notes")))),
            "quality_failures": (run.get("quality_failures")
                                 or old.get("quality_failures") or []),
            "cannibalization_failures": (run.get("cannibalization_failures")
                                         or old.get(
                                             "cannibalization_failures")
                                         or []),
            "cannibalization_warnings": (old.get("cannibalization_warnings")
                                         or []),
        })
    count = lambda st: sum(1 for r in members
                          if (r.get("status") or "").strip() == st)  # noqa: E731
    planned = count("PLANNED")
    writing = count("WRITING")
    scores = [a["score"] for a in articles if isinstance(a["score"], int)]
    scores_sum = sum(scores)
    avg = round(scores_sum / len(scores), 1) if scores else None
    if isinstance(avg, float) and avg == int(avg):
        avg = int(avg)  # match Node JSON (98.0 -> 98)
    pub = select_publish_rows(members, repo_root)
    return {
        "batch_id": batch_id,
        "started_at": prev.get("started_at") or started_at,
        "finished_at": datetime.datetime.now().isoformat(
            timespec="seconds"),
        "writer": prev.get("writer") or "external-agent",
        "processed": len(members) - planned,
        "written": len(members) - planned - writing,
        "pass": count("PASS"),
        "published": count("PUBLISHED"),
        "writing": writing,
        "review": count("REVIEW"),
        "repair": count("REPAIR"),
        "fail": count("FAIL"),
        "blocked": count("BLOCKED"),
        "average_score": avg,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "repair_count": sum((a["repair_attempts"] or 0)
                            for a in articles),
        "source_gate_pass": sum(
            1 for r in members if req_sources(r)
            and (r.get("status") or "").strip() in ("PASS", "PUBLISHED")),
        "source_gate_blocked": sum(
            1 for r in members if req_sources(r)
            and (r.get("status") or "").strip() == "BLOCKED"),
        "published_commit_sha": _resolve_published_sha(repo_root, prev),
        "pass_publishable_now": len(pub),
        "articles": articles,
    }


def report_markdown(report):
    L = ["# Batch report %s" % report.get("batch_id"), ""]
    L.append("- started_at: %s | finished_at: %s" %
             (report.get("started_at"), report.get("finished_at")))
    L.append("- writer: %s | batch resolved once: %s" %
             (report.get("writer"), report.get("batch_id")))
    L.append("- processed: %s | written: %s | pass: %s | published: %s" %
             (report.get("processed"), report.get("written"),
              report.get("pass"), report.get("published")))
    L.append("- writing: %s | review: %s | repair: %s | fail: %s | blocked: %s" %
             (report.get("writing", 0), report.get("review"),
              report.get("repair"), report.get("fail"),
              report.get("blocked")))
    L.append("- scores: avg %s | min %s | max %s | repair_count: %s" %
             (report.get("average_score"), report.get("min_score"),
              report.get("max_score"), report.get("repair_count")))
    L.append("- source_gate: pass %s | blocked %s" %
             (report.get("source_gate_pass"), report.get("source_gate_blocked")))
    L.append("- published_commit_sha: %s" % (
        report.get("published_commit_sha")
        if report.get("published_commit_sha") is not None else "null"))
    L.append("")
    L.append("| article_id | output_path | status | score | repairs | notes |")
    L.append("|---|---|---|---|---|---|")
    for a in report.get("articles", []):
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            a.get("article_id"), a.get("output_path"), a.get("outcome"),
            a.get("score") if a.get("score") is not None else "",
            a.get("repair_attempts"),
            "; ".join((a.get("quality_failures") or [])[:2])))
    return "\n".join(L) + "\n"


def write_manifest(repo_root, manifest):
    return write_json(os.path.join(batches_dir(repo_root),
                                   manifest["batch_id"] + ".json"), manifest)


def write_factory_progress(repo_root, matrix, published_commit_sha=None):
    """reports/batches/factory-progress.json — deterministic global state."""
    prod = production_rows(matrix)
    counts = {}
    for r in prod:
        st = (r.get("status") or "").strip().lower() or "unknown"
        counts[st] = counts.get(st, 0) + 1
    per_batch = {}
    for r in prod:
        bid = (r.get("batch_id") or "").strip()
        st = (r.get("status") or "").strip()
        b = per_batch.setdefault(bid, {"total": 0, "planned": 0, "active": 0,
                                       "pass": 0, "published": 0,
                                       "fail": 0, "blocked": 0})
        b["total"] += 1
        if st == "PLANNED":
            b["planned"] += 1
        elif st in ACTIVE_STATUSES:
            b["active"] += 1
        elif st == "PASS":
            b["pass"] += 1
        elif st == "PUBLISHED":
            b["published"] += 1
        elif st == "FAIL":
            b["fail"] += 1
        elif st == "BLOCKED":
            b["blocked"] += 1
    completed = sum(1 for b in per_batch.values()
                    if b["published"] + b["fail"] + b["blocked"] == b["total"]
                    and b["total"] > 0)
    progress = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "total": len(prod),
        "planned": counts.get("planned", 0),
        "writing": counts.get("writing", 0),
        "qa": counts.get("qa", 0),
        "review": counts.get("review", 0),
        "repair": counts.get("repair", 0),
        "pass": counts.get("pass", 0),
        "published": counts.get("published", 0),
        "fail": counts.get("fail", 0),
        "blocked": counts.get("blocked", 0),
        "completed_batches": completed,
        "active_batch": active_batch_id(matrix),
        "next_batch": next_batch_id(matrix),
        "published_commit_sha": published_commit_sha,
    }
    return write_json(os.path.join(repo_root, "reports", "batches",
                                   "factory-progress.json"), progress), progress


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_kill_switch(repo_root):
    p = os.path.join(repo_root, "config", "content-factory.json")
    if not os.path.isfile(p):
        return {"enabled": True}
    try:
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"enabled": True}


def main_func(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--batch", help="batch id, e.g. BATCH-001 (resolved once)")
    mode.add_argument("--next", action="store_true",
                      help="resolve batch: active unfinished batch first, "
                           "else first batch with PLANNED rows")
    ap.add_argument("--prepare-agent", action="store_true",
                    help="claim PLANNED rows + write the agent manifest")
    ap.add_argument("--qa", action="store_true",
                    help="deterministic QA of written files in the batch")
    ap.add_argument("--publish", action="store_true",
                    help="list the batch's PASS files (publish scope)")
    ap.add_argument("--mark-published", action="store_true",
                    help="flip the batch's PASS rows to PUBLISHED "
                         "(ONLY after files reached remote MAIN)")
    ap.add_argument("--pilot", action="store_true",
                    help="pilot mode: BATCH-001 only, max 50, no chaining")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--progress", action="store_true",
                    help="write reports/batches/factory-progress.json")
    ap.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    args = ap.parse_args(argv)

    repo_root = lib.ROOT
    batch_size = min(args.batch_size, MAX_BATCH_SIZE)

    # --progress alone: batch-less global progress report
    if (args.progress and not (args.prepare_agent or args.qa or args.publish
                               or args.mark_published or args.batch
                               or args.next or args.pilot)):
        matrix = lib.load_matrix()
        _, progress = write_factory_progress(repo_root, matrix)
        print(json.dumps(progress, ensure_ascii=False))
        return EXIT_OK

    kill = _load_kill_switch(repo_root)
    if not kill.get("enabled", True):
        print("FACTORY_PAUSED: config/content-factory.json enabled=false. "
              "No changes made.")
        return EXIT_OK

    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return EXIT_ERROR

    # -------- resolve batch identity ONCE --------
    if args.pilot:
        batch_id = "BATCH-001"
    elif args.next or (not args.batch and (args.prepare_agent or args.qa)):
        batch_id = next_batch_id(matrix)
        if not batch_id:
            if args.progress:
                _, progress = write_factory_progress(repo_root, matrix)
                print("FACTORY_COMPLETE: no PLANNED or active rows.")
                print(json.dumps(progress, ensure_ascii=False))
                return EXIT_OK
            print("FACTORY_COMPLETE: no PLANNED rows left and no active "
                  "batch. Nothing to do.")
            return EXIT_OK
        if args.next:
            active = active_batch_id(matrix)
            print("resolved batch: %s%s" %
                  (batch_id, " (resumed active batch)" if active == batch_id
                   else " (first with PLANNED rows)"))
    else:
        batch_id = args.batch
    if not batch_id:
        print("ERROR: no batch id given. Use --batch BATCH-XXX or --next.")
        return EXIT_USAGE
    if args.batch and args.pilot and args.batch != "BATCH-001":
        print("ERROR: pilot mode may only run BATCH-001.")
        return EXIT_USAGE

    rows = batch_rows(matrix, batch_id)
    if not rows:
        print("ERROR: batch %s not found" % batch_id)
        return EXIT_USAGE

    if args.dry_run:
        claim = select_claim_rows(rows, batch_size)
        qa = select_qa_rows(rows, repo_root, batch_size)
        pub = select_publish_rows(rows, repo_root)
        print("DRY RUN %s: %d PLANNED claimable, %d QA-able, %d PASS "
              "publishable, statuses: %s" %
              (batch_id, len(claim), len(qa), len(pub),
               sorted({(r.get("status") or "?") for r in rows})))
        if args.progress:
            write_factory_progress(repo_root, matrix)
        return EXIT_OK

    if not acquire_lock(repo_root, batch_id):
        print("LOCKED: another runner holds %s (data/batches/%s.lock, <24h)."
              % (batch_id, batch_id))
        return EXIT_USAGE

    try:
        started_at = datetime.datetime.now().isoformat(timespec="seconds")

        # ---------------- prepare-agent ----------------
        if args.prepare_agent:
            claim = select_claim_rows(rows, batch_size)
            if not claim:
                print("No PLANNED rows in %s (statuses: %s)"
                      % (batch_id,
                         sorted({(r.get("status") or "?") for r in rows})))
                return EXIT_OK
            if args.dry_run:
                print("DRY RUN: would claim %d rows of %s" %
                      (len(claim), batch_id))
                return EXIT_OK
            manifest = build_manifest(batch_id, claim, matrix, ownership,
                                      facts, rubric, site, repo_root)
            write_manifest(repo_root, manifest)
            update_matrix_statuses(repo_root,
                                   {r["article_id"]: {"status": "WRITING"}
                                    for r in claim})
            print("PREPARED-AGENT %s: %d articles claimed WRITING. Manifest: "
                  "data/batches/%s.json. External writer: write EXACTLY "
                  "these files, then run --qa." %
                  (batch_id, len(claim), batch_id))
            return EXIT_OK

        # ---------------- QA ----------------
        if args.qa:
            qa_rows = select_qa_rows(rows, repo_root, batch_size)
            if not qa_rows:
                print("Nothing to QA in %s (no written files for active "
                      "rows). Run --prepare-agent and write the articles "
                      "first." % batch_id)
                return EXIT_OK
            updates, articles = run_qa_for_batch(qa_rows, matrix, ownership,
                                                 facts, rubric, repo_root)
            update_matrix_statuses(repo_root, updates)
            matrix = lib.load_matrix()
            rows = batch_rows(matrix, batch_id)
            pub = select_publish_rows(rows, repo_root)
            # CUMULATIVE batch report: every reserved member of the batch,
            # counts derived from the current matrix truth (never just the
            # rows of this run)
            report = build_cumulative_report(
                batch_id, rows, articles, started_at, repo_root)
            write_report(repo_root, report)
            print(json.dumps({k: v for k, v in report.items()
                              if k != "articles"}, ensure_ascii=False))
            if args.progress:
                write_factory_progress(repo_root, matrix)
            # exit codes reflect THIS RUN's QA outcomes (not cumulative
            # history) so a clean run of an older batch is not penalised
            run_fail = len([a for a in articles
                            if a["outcome"] == "FAIL"])
            run_review = len([a for a in articles
                              if a["outcome"] == "REVIEW"])
            run_blocked = len([a for a in articles
                               if a["outcome"] == "BLOCKED"])
            if run_fail:
                return EXIT_FAILS
            if run_review or run_blocked:
                return EXIT_ISSUES
            return EXIT_OK

        # ---------------- publish (scope: THIS batch) ----------------
        if args.publish:
            pub = select_publish_rows(rows, repo_root)
            for r in pub:
                print(r["output_path"])
            print("# publish scope: %s (%d PASS files; other batches' PASS "
                  "rows are NEVER included)" % (batch_id, len(pub)))
            return EXIT_OK

        # ---------------- mark-published (scope: THIS batch) --------
        if args.mark_published:
            pub = select_publish_rows(rows, repo_root)
            if not pub:
                print("No PASS-with-file rows in %s to mark PUBLISHED."
                      % batch_id)
                return EXIT_OK
            update_matrix_statuses(repo_root, {
                r["article_id"]: {"status": "PUBLISHED",
                                  "published_date": today()}
                for r in pub})
            print("PUBLISHED %d articles of %s (files verified present; "
                  "push them to MAIN BEFORE running this step). Rows stamped "
                  "published_date=%s." % (len(pub), batch_id, today()))
            return EXIT_OK

        # ---------------- progress ----------------
        if args.progress:
            _, progress = write_factory_progress(repo_root, matrix)
            print(json.dumps(progress, ensure_ascii=False))
            return EXIT_OK

        print("Nothing to do for %s (no mode given). Use --prepare-agent, "
              "--qa, --publish, --mark-published or --progress." % batch_id)
        return EXIT_OK
    finally:
        release_lock(repo_root, batch_id)


if __name__ == "__main__":
    sys.exit(main_func())
