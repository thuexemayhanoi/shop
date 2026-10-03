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
  --next-chunk N     chunked writer mode: select the NEXT N (5 default,
                     10 max) unwritten WRITING rows deterministically,
                     write the chunk manifest + checkpoint (no re-claim)
  --chunk-complete   mark the current chunk terminal (checkpoint / --ids)
  --qa               deterministic QA of the batch's written files
                     (scoped to --ids when given)
  --publish          list the batch's PASS files (publish scope)
                     (scoped to --ids when given)
  --mark-published   flip the batch's PASS rows (files verified
                     present) to PUBLISHED + stamp published_date=today;
                     run ONLY after the push reached remote MAIN
  --acquire-writer-lock | --release-writer-lock | --writer-lock-status
                     writer-side logical lock (external writers)
  --checkpoint | --checkpoint-reset
                     show (reconciled with matrix truth) / delete the
                     resume checkpoint (data/batches/writer-checkpoint.json)
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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib
import taxonomy_lib as tlib

MAX_BATCH_SIZE = 50
MAX_REPAIR_ATTEMPTS = 3
ACTIVE_STATUSES = ("WRITING", "QA", "REPAIR", "REVIEW")

# Chunked writer mode: the external writer works in small chunks instead of
# write->publish per article. Default chunk 5, hard ceiling 10 (an explicit
# override is required to go higher; the CLI clamps to MAX_CHUNK_SIZE).
DEFAULT_CHUNK_SIZE = 5
MAX_CHUNK_SIZE = 10
# Writer-side logical lock TTL (minutes). The batch .lock file only guards a
# single machine/workspace; the writer lock guards concurrent EXTERNAL
# writers (e.g. two Mistral sessions) on the same active batch.
WRITER_LOCK_TTL_MINUTES = 120
# exclusive stale-reclaim guard TTL: a crashed reclaimer
# cannot deadlock recovery for longer than this
WRITER_RECOVERY_TTL_MINUTES = 5

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


# ---------------------------------------------------------------------------
# DEPLOY GATE (drafts): article files for rows that are NOT yet PUBLISHED
# live under _drafts/<output_path>. Jekyll never copies underscore
# directories into the deployed site, so an unreviewed article can never
# be fetched on the public URL. scripts/js/factory.mjs --publish promotes
# the draft file to the REAL output_path in the same transaction that
# flips the matrix row to PUBLISHED. Publish-gate tests live in
# tests/test_publish_gate.py.
# ---------------------------------------------------------------------------

DRAFTS_PREFIX = "_drafts/"


def draft_rel(output_path):
    """Non-published draft location for a row's output_path."""
    return DRAFTS_PREFIX + (output_path or "").strip().lstrip("/")


def draft_abs(repo_root, output_path):
    return os.path.join(repo_root, draft_rel(output_path))


def row_file_exists(repo_root, output_path):
    """True when the article file exists at the draft path OR the final
    path (PASS rows written before the gate, PUBLISHED rows)."""
    path = (output_path or "").strip()
    if not path:
        return False
    return (os.path.isfile(os.path.join(repo_root, path))
            or os.path.isfile(draft_abs(repo_root, path)))


def row_written_file(repo_root, output_path):
    """The file QA should read: draft first, final as fallback."""
    path = (output_path or "").strip()
    if not path:
        return None
    if os.path.isfile(draft_abs(repo_root, path)):
        return draft_abs(repo_root, path)
    if os.path.isfile(os.path.join(repo_root, path)):
        return os.path.join(repo_root, path)
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
                and row_file_exists(repo_root, path)):
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
        if path and row_file_exists(repo_root, path):
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


# Vietnam local time (Asia/Ho_Chi_Minh) as a REAL timezone-aware value.
# The old convention (UTC now + 7h, then formatting WITHOUT the offset)
# produced a naive timestamp that claimed to be Hanoi time but carried
# no zone evidence; the schema-2 contract requires an explicit +07:00.
HANOI_TZ = datetime.timezone(datetime.timedelta(hours=7), "+07:00")


def now_vn():
    """Timezone-aware current time in Hanoi (Asia/Ho_Chi_Minh, UTC+7)."""
    return datetime.datetime.now(HANOI_TZ)


def now_vn_iso():
    """Hanoi-local timestamp, timezone-aware, e.g.
    2026-09-30T10:15:30+07:00 (matches scripts/js/factory.mjs
    hanoiNowIso())."""
    return now_vn().isoformat(timespec="seconds")


def today():
    # Vietnam-local date (Asia/Ho_Chi_Minh), matching scripts/js/factory.mjs
    return now_vn().date().isoformat()


def source_head_sha():
    """The commit SHA of the INPUT tree this report was generated from.

    Schema-2 semantics: this is the HEAD the operator STARTED from (the
    pre-mutation input), typically the GITHUB_SHA of the running workflow.
    It is deliberately NOT a claim about the commit that will contain this
    file: a report cannot prove "this commit contains me" (self-reference
    is unstable), so the FINAL result SHA is recorded by the workflow in
    its step summary / outputs after the push, never inside this file.
    The legacy name matrix_commit_sha implied exactly that unstable claim
    and is gone (verify_factory_state.py rejects schema-1 reports).
    """
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        import subprocess
        p = subprocess.run(["git", "rev-parse", "HEAD"],
                           cwd=os.path.dirname(os.path.abspath(__file__)),
                           capture_output=True, text=True, timeout=10)
        if p.returncode == 0:
            return p.stdout.strip() or None
    except Exception:
        pass
    return None


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
    tax_fields = tlib.writer_taxonomy_fields(
        row.get("article_id"), repo_root or lib.ROOT) or {}
    out = {
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
        "draft_output_path": draft_rel(out_path),
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
            "target_min_words": int(length_cfg.get(
                "unpublished_target_min_words",
                length_cfg.get("target_min_words", 1500))),
            "target_max_words": int(length_cfg.get(
                "unpublished_target_max_words",
                length_cfg.get("target_max_words", 5000))),
            "review_min_words": int(length_cfg.get(
                "unpublished_review_min_words",
                length_cfg.get("review_min_words", 1100))),
            "review_max_words": int(length_cfg.get(
                "unpublished_review_max_words",
                length_cfg.get("review_max_words", 5400))),
            "scope": "main editorial content only",
            "policy": ("choose length inside the band by search intent; "
                       "never pad with repeated ideas, keyword stuffing "
                       "or invented facts"),
        },
        "taxonomy": {
            "parent_id": tax_fields.get("parent_id", ""),
            "parent_title": tax_fields.get("parent_title", ""),
            "parent_hub": tax_fields.get("parent_hub", ""),
            "child_cluster": tax_fields.get("child_cluster", ""),
            "child_title": tax_fields.get("child_title", ""),
            "child_slug": tax_fields.get("child_slug", ""),
            "child_hub": tax_fields.get("child_hub", ""),
            "taxonomy_version": tax_fields.get("taxonomy_version", ""),
            "policy": ("taxonomy is authoritative: the writer MUST NOT "
                       "invent categories or hubs; when child_hub is "
                       "non-empty, link the parent hub AND the child hub "
                       "contextually within the 3-8 link budget"),
        },
        "page_shell": {
            "chatbot_embed_required": True,
            "chatbot_embed_snippet": (
                '<link rel="stylesheet" href="/shop/assets/css/chatbot-embed.css">\n'
                '<script src="/shop/assets/js/chatbot-embed.js" defer></script>'),
            "chatbot_embed_position": "immediately before </body>, exactly once",
            "compact_footer_required": True,
            "compact_footer_snippet_path": "_snippets/footer-compact.html",
            "compact_footer_position": (
                "immediately after </main>, before the chatbot embed, "
                "exactly once; regenerate the file with "
                "scripts/build_footer_snippet.py and embed its content "
                "verbatim (class site-footer-compact)"),
            "policy": ("structural shell elements: never count as "
                        "contextual internal links; do not add any other "
                        "chatbot script or a second taxonomy footer"),
        },
        "link_standard": {
            "contextual_internal_links_min": int(link_cfg.get("min", 3)),
            "contextual_internal_links_max": int(link_cfg.get("max", 8)),
            "parent_hub_link_required": True,
            "child_hub_link_recommended": bool(tax_fields.get("child_hub")),
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
    return out


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
        "generated": now_vn_iso(),
        "writer": "external-agent",
        "writer_instructions": (
            "The Mistral agent writes these article files DIRECTLY (no API, "
            "no secrets). Write exactly the manifest rows. Each article: "
            "1500-5000 meaningful Vietnamese words (choose the length by "
            "search intent; never pad with repetition or invented facts), "
            "3-8 contextual internal "
            "links (parent hub required, max 1 true commercial link, other "
            "links informational and relevant), exactly 1 H1, self canonical "
            "(canonical_url), Article schema + BreadcrumbList, no invented "
            "facts/prices/laws, datePublished = date_published (actual date). "
            "requires_sources=true rows need an approved official source "
            "URL in a 'Nguồn tham khảo' section. Write each file to "
            "draft_output_path (_drafts/...): drafts are NEVER written to "
            "output_path, which stays public-URL space reserved for "
            "PUBLISHED articles (deploy gate). The page shell must carry "
            "the compact shared footer from _snippets/footer-compact.html "
            "exactly once (see page_shell.compact_footer_*)."),
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
    budget (notes repair:N); after MAX_REPAIR_ATTEMPTS they become BLOCKED.
    PASS verdicts are recorded as reusable QA evidence (content hash +
    config hash + validator version, see scripts/qa_scope.py) so later
    gates never re-scan unchanged PASS articles."""
    import qa_scope
    updates = {}
    articles = []
    evidence_entries = []
    cfg_sha = qa_scope.config_sha256(repo_root)
    for r in rows:
        aid = r.get("article_id")
        path = row_written_file(repo_root, r.get("output_path") or "")
        entry = {"article_id": aid, "output_path": r.get("output_path"),
                 "outcome": None, "score": None, "repair_attempts": 0,
                 "quality_failures": [], "cannibalization_failures": [],
                 "cannibalization_warnings": [], "qa_path": path}
        if not (r.get("output_path") and path):
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
            # Owner-approved 75/70/75 production band (config/article-
            # rubric.json): scores 75-100 are simply PASS - no EXCELLENT
            # tier, no QA warning score band.
            updates[aid] = {"status": "PASS", "quality_status": "PASS",
                            "score": str(res["score"]),
                            "last_checked": today()}
            if qa_scope.is_matrix_article(aid):
                try:
                    evidence_entries.append({
                        "article_id": aid,
                        "content_sha256": qa_scope.file_sha256(path),
                        "config_sha256": cfg_sha,
                        "validator_version": lib.VALIDATOR_VERSION,
                        "status": "PASS",
                        "score": res.get("score"),
                        "path": os.path.relpath(path, repo_root),
                        "last_checked": today(),
                    })
                except OSError:
                    pass
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
    if evidence_entries:
        try:
            qa_scope.record_evidence(repo_root, evidence_entries)
        except OSError:
            pass
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
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=HANOI_TZ)
            if now_vn() - ts < datetime.timedelta(hours=24):
                return False
        except ValueError:
            pass
    with io.open(lp, "w", encoding="utf-8") as f:
        f.write(now_vn_iso())
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
        "finished_at": now_vn_iso(),
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
        "schema_version": 2,
        "generated": now_vn_iso(),
        "source_head_sha": source_head_sha(),
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
# Chunked writer mode: chunk selection, checkpoint, writer lock, throughput
# ---------------------------------------------------------------------------

class ChunkError(Exception):
    """Deterministic tooling error (unknown id, wrong batch, wrong status)."""


def clamp_chunk_size(chunk_size):
    try:
        n = int(chunk_size)
    except (TypeError, ValueError):
        n = DEFAULT_CHUNK_SIZE
    return max(1, min(n, MAX_CHUNK_SIZE))


def select_next_chunk_rows(rows, repo_root, chunk_size=DEFAULT_CHUNK_SIZE):
    """NEXT WRITER CHUNK (deterministic, matrix order).

    Eligible rows: status WRITING whose article file does NOT exist yet.
    Skipped forever: PUBLISHED / PASS (never rewritten or re-claimed),
    FAIL / BLOCKED (unless explicitly requeued), REPAIR / REVIEW (repair
    path). WRITING rows that ALREADY have a file are NOT selected here:
    they belong to the scoped QA stage, not to a fresh write chunk.
    """
    n = clamp_chunk_size(chunk_size)
    out = []
    for r in rows:
        if len(out) >= n:
            break
        st = (r.get("status") or "").strip()
        path = (r.get("output_path") or "").strip()
        if st == "WRITING" and path \
                and not row_file_exists(repo_root, path):
            out.append(r)
    return out


def select_qa_rows_by_ids(rows, ids, repo_root):
    """Scoped QA selection for explicit article ids (this batch only).

    Errors (ChunkError): unknown id, id of another batch, duplicate id,
    PASS/PUBLISHED row (never re-QA'd), active row without a written file.
    """
    by_id = {}
    for r in rows:
        by_id.setdefault(r.get("article_id"), r)
    seen = set()
    out = []
    for i in ids:
        i = (i or "").strip()
        if not i:
            continue
        if i in seen:
            raise ChunkError("duplicate id in --ids: %s" % i)
        seen.add(i)
        r = by_id.get(i)
        if r is None:
            raise ChunkError("unknown article_id (or not in this batch): %s" % i)
        st = (r.get("status") or "").strip()
        path = (r.get("output_path") or "").strip()
        if st in ("PASS", "PUBLISHED"):
            raise ChunkError(
                "%s is %s — PASS/PUBLISHED rows are never re-QA'd" % (i, st))
        if st not in ACTIVE_STATUSES:
            raise ChunkError(
                "%s is %s — only active rows can be QA'd (requeue FAIL/"
                "BLOCKED explicitly via scripts/requeue_rows.py)" % (i, st))
        if not path or not row_file_exists(repo_root, path):
            raise ChunkError("%s has no written file (draft or final) at %s"
                             " — write it first"
                             % (i, path or "(empty output_path)"))
        out.append(r)
    return out


def checkpoint_path(repo_root):
    return os.path.join(batches_dir(repo_root), "writer-checkpoint.json")


def empty_checkpoint(batch_id, chunk_size=DEFAULT_CHUNK_SIZE):
    return {
        "schema_version": 1,
        "batch": batch_id,
        "head_at_start": None,
        "chunk_size": clamp_chunk_size(chunk_size),
        "current_chunk_ids": [],
        "completed_ids": [],
        "pending_qa_ids": [],
        "pending_repair_ids": [],
        "pending_publish_ids": [],
        "last_completed_step": None,
        "updated_at": None,
        "writer_session": None,
    }


def load_checkpoint(repo_root):
    p = checkpoint_path(repo_root)
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, encoding="utf-8") as f:
            cp = json.load(f)
        if isinstance(cp, dict) and cp.get("schema_version") == 1:
            return cp
    except ValueError:
        pass
    return None


def reconcile_checkpoint(cp, matrix, batch_id):
    """Reconcile a checkpoint against matrix truth. THE MATRIX ALWAYS WINS:
    a checkpoint row whose matrix status moved on (e.g. checkpoint says
    WRITING but the matrix says PUBLISHED) is dropped from the pending
    lists; a stale checkpoint of another batch is discarded entirely."""
    if not cp or cp.get("batch") != batch_id or cp.get("schema_version") != 1:
        cp = empty_checkpoint(batch_id,
                              (cp or {}).get("chunk_size")
                              if cp else DEFAULT_CHUNK_SIZE)
    rows = {r.get("article_id"): r for r in batch_rows(matrix, batch_id)}

    def keep(ids, statuses):
        out = []
        for i in ids or []:
            r = rows.get(i)
            if r is not None and (r.get("status") or "").strip() in statuses:
                out.append(i)
        return out

    cp["current_chunk_ids"] = keep(cp.get("current_chunk_ids"), ("WRITING",))
    cp["pending_qa_ids"] = keep(cp.get("pending_qa_ids"), ACTIVE_STATUSES)
    cp["pending_repair_ids"] = keep(cp.get("pending_repair_ids"),
                                    ("REPAIR", "REVIEW"))
    cp["pending_publish_ids"] = keep(cp.get("pending_publish_ids"), ("PASS",))
    cp["completed_ids"] = [i for i in (cp.get("completed_ids") or [])
                           if i in rows]
    return cp


def save_checkpoint(repo_root, cp):
    cp = dict(cp)
    cp["updated_at"] = now_vn_iso()
    return write_json(checkpoint_path(repo_root), cp)


def writer_lock_path(repo_root):
    return os.path.join(batches_dir(repo_root), "writer-lock.json")


def writer_recovery_path(repo_root):
    # Exclusive serialized-recovery mutex: stale-lock reclaims happen
    # only while holding this guard, so two readers that both see the
    # same stale lock cannot delete each other's fresh replacement.
    return os.path.join(batches_dir(repo_root), "writer-lock.recovery")


def _now_aware(dt):
    # Legacy locks/checkpoints stored naive timestamps; treat them as
    # Hanoi local time (+07:00) so comparisons with tz-aware now() work.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HANOI_TZ)
    return dt


def writer_lock_status(repo_root, now=None):
    """Returns (lock_dict_or_None, fresh_bool). A lock is fresh while
    younger than WRITER_LOCK_TTL_MINUTES; a stale lock may be recovered
    (after the caller reconciles with matrix/HEAD truth)."""
    p = writer_lock_path(repo_root)
    if not os.path.isfile(p):
        return None, False
    try:
        with io.open(p, encoding="utf-8") as f:
            lock = json.load(f)
    except ValueError:
        return None, False
    if not isinstance(lock, dict) or not lock.get("writer_session"):
        return None, False
    now = _now_aware(now or now_vn())
    try:
        age = (_now_aware(now)
               - _now_aware(datetime.datetime.fromisoformat(
                   lock.get("updated_at"))))
    except (TypeError, ValueError):
        return lock, False
    return lock, age < datetime.timedelta(minutes=WRITER_LOCK_TTL_MINUTES)


def _write_lock_fd(fd, lock):
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(lock, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _recovery_guard(repo_root, now):
    """Acquire the exclusive stale-reclaim mutex (O_CREAT|O_EXCL).

    Returns a callable that releases the guard, or None when another
    reclaimer holds it. A crashed reclaimer cannot deadlock recovery:
    a guard older than WRITER_RECOVERY_TTL_MINUTES is removed and the
    acquisition retried once.
    """
    gp = writer_recovery_path(repo_root)
    for _ in range(2):
        try:
            fd = os.open(gp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                with io.open(gp, encoding="utf-8") as f:
                    gts = _now_aware(datetime.datetime.fromisoformat(
                        f.read().strip()))
            except (OSError, ValueError):
                gts = None
            if (gts is None
                    or _now_aware(now) - gts
                    > datetime.timedelta(minutes=WRITER_RECOVERY_TTL_MINUTES)):
                try:
                    os.remove(gp)   # stale/unreadable guard of a crashed reclaimer
                except OSError:
                    pass
                continue
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_now_aware(now).isoformat(timespec="seconds"))

        def _release():
            try:
                os.remove(gp)
            except OSError:
                pass
        return _release
    return None


def acquire_writer_lock(repo_root, batch_id, writer_session=None, head=None,
                        now=None):
    """Atomic exclusive writer lock for EXTERNAL writers (outside GitHub
    Actions), schema 2.

    Contract (four-layer reliability hardening):
      - acquisition is ATOMIC: the lock file is created with
        O_CREAT|O_EXCL, so of N concurrent writers EXACTLY ONE wins;
        the losers read the winner's lock and refuse.
      - the lock carries a unique generation token; only the owner's
        token can refresh or release it.
      - a FRESH lock owned by another session is never overwritten.
      - a STALE lock is reclaimed only while holding the exclusive
        writer-lock.recovery guard, after re-reading and verifying the
        SAME stale token (CAS-like): if another writer already won the
        reclaim, their lock is never deleted or overwritten.
    Returns (bool_acquired, lock).
    """
    os.makedirs(batches_dir(repo_root), exist_ok=True)
    now = _now_aware(now or now_vn())
    session = (writer_session or "").strip() or ("writer-%s"
                                                 % now.strftime("%Y%m%dT%H%M%S"))
    lp = writer_lock_path(repo_root)
    token = "%d-%d" % (time.time_ns(), os.getpid())
    new_lock = {
        "schema_version": 2,
        "batch": batch_id,
        "writer_session": session,
        "token": token,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "head": head,
    }
    # ---- fast path: ATOMIC exclusive creation (the one winner) ----
    try:
        fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        pass
    else:
        _write_lock_fd(fd, new_lock)
        return True, new_lock
    # ---- lock file exists: read it and respect its owner ----
    lock, fresh = writer_lock_status(repo_root, now=now)
    if lock is not None and lock.get("writer_session") == session:
        # same-session heart-beat refresh: CAS-like replace, only when
        # the file still carries OUR token (never clobber a takeover)
        expected = lock.get("token")
        refreshed = dict(lock)
        refreshed.update({
            "batch": batch_id,
            "updated_at": now.isoformat(timespec="seconds"),
            "head": head,
        })
        if expected is None or _cas_replace_lock(lp, expected, refreshed):
            if expected is None:
                # legacy schema-1 lock (no token): rewrite under the
                # recovery guard so a concurrent upgrade cannot clobber
                release_guard = _recovery_guard(repo_root, now)
                if release_guard is None:
                    return False, lock
                try:
                    cur, _f = writer_lock_status(repo_root, now=now)
                    if (cur is None or cur.get("writer_session") != session):
                        return False, cur
                    _cas_replace_lock(lp, cur.get("token"), refreshed)
                finally:
                    release_guard()
            return True, refreshed
        # our token is gone: someone else owns the lock now
        return False, writer_lock_status(repo_root, now=now)[0]
    if lock is not None and fresh:
        return False, lock
    # ---- stale or unreadable lock: serialized CAS-like reclaim ----
    release_guard = _recovery_guard(repo_root, now)
    if release_guard is None:
        # another reclaimer is active: do not touch the lock
        return False, lock
    try:
        cur, cur_fresh = writer_lock_status(repo_root, now=now)
        if cur is None:
            # missing/unreadable: remove and race for exclusive creation
            try:
                os.remove(lp)
            except OSError:
                pass
        elif cur_fresh:
            return False, cur     # another writer won while we waited
        elif (lock is not None
              and (cur.get("writer_session") != lock.get("writer_session")
                   or (lock.get("token") is not None
                       and cur.get("token") != lock.get("token")))):
            return False, cur     # lock changed since we saw it stale
        else:
            # confirmed the SAME stale lock (same owner, same token):
            # safe to reclaim under the guard
            try:
                os.remove(lp)
            except OSError:
                pass
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False, writer_lock_status(repo_root, now=now)[0]
        _write_lock_fd(fd, new_lock)
        return True, new_lock
    finally:
        release_guard()


def _cas_replace_lock(path, expected_token, new_lock):
    """CAS-like replace: write a temp file, re-read the lock and only
    os.replace() it when it still carries expected_token. Returns False
    when another owner took over (their lock is never overwritten)."""
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(new_lock, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        with io.open(path, encoding="utf-8") as f:
            cur = json.load(f)
        if (not isinstance(cur, dict)
                or cur.get("token") != expected_token):
            return False
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def release_writer_lock(repo_root, writer_session=None, token=None):
    """Idempotent, ownership-safe release. With a session (and/or token),
    only a lock owned by that session/token is deleted — a foreign
    owner's lock is REFUSED, never deleted. Without a session (explicit
    operator action) any valid lock may be cleared; an unreadable lock
    file is removed only under the recovery guard."""
    lp = writer_lock_path(repo_root)
    lock, _fresh = writer_lock_status(repo_root)
    if lock is None:
        if os.path.exists(lp):
            release_guard = _recovery_guard(
                repo_root, _now_aware(now_vn()))
            if release_guard is None:
                return False
            try:
                cur, _f = writer_lock_status(repo_root)
                if cur is not None:
                    return False   # a valid lock appeared: not ours to judge
                try:
                    os.remove(lp)
                except OSError:
                    pass
            finally:
                release_guard()
        return True
    if writer_session and lock.get("writer_session") != writer_session:
        return False
    if token and lock.get("token") != token:
        return False
    try:
        os.remove(lp)
    except OSError:
        pass
    return True


def throughput_path(repo_root):
    return os.path.join(repo_root, "reports", "batches",
                        "factory-throughput.json")


def update_throughput(repo_root, batch_id, **deltas):
    """Lightweight cumulative throughput counters. Honest by construction:
    every counter is incremented only by deterministic tooling with the
    exact number of rows it verified. No estimated numbers are written."""
    p = throughput_path(repo_root)
    data = {}
    if os.path.isfile(p):
        try:
            with io.open(p, encoding="utf-8") as f:
                data = json.load(f) or {}
        except ValueError:
            data = {}
    if data.get("schema_version") != 1:
        data = {"schema_version": 1, "batches": {}}
    b = data["batches"].setdefault(batch_id, {
        "articles_written": 0, "articles_qa_checked": 0,
        "articles_published": 0, "chunks_completed": 0,
        "publish_operations": 0, "repair_count": 0,
        "qa_score_sum": 0, "qa_score_count": 0,
    })
    for k in ("articles_written", "articles_qa_checked", "articles_published",
              "chunks_completed", "publish_operations", "repair_count"):
        if deltas.get(k):
            b[k] = b.get(k, 0) + int(deltas[k])
    if deltas.get("qa_score_sum"):
        b["qa_score_sum"] = b.get("qa_score_sum", 0) + int(deltas["qa_score_sum"])
        b["qa_score_count"] = b.get("qa_score_count", 0) + int(
            deltas.get("qa_score_count") or (1 if deltas.get("qa_score_sum")
                                             else 0))
    b["average_qa_score"] = (round(b["qa_score_sum"] / b["qa_score_count"], 1)
                             if b.get("qa_score_count") else None)
    data["updated_at"] = now_vn_iso()
    write_json(p, data)
    return data


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
    ap.add_argument("--claim-ids", action="store_true",
                    help="claim EXACTLY the PLANNED rows listed in --ids "
                         "(explicit-ID claim for the event-driven "
                         "factory-publish workflow; never a blind "
                         "first-N claim; refuses non-PLANNED/unknown/"
                         "duplicate ids and scopes over 50)")
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
    # ---- chunked writer mode ----
    ap.add_argument("--next-chunk", type=int, default=None, metavar="N",
                    help="chunked writer mode: deterministically select the "
                         "next N (default 5, max 10) unwritten WRITING rows "
                         "and write the chunk manifest + checkpoint")
    ap.add_argument("--chunk-complete", action="store_true",
                    help="mark the current chunk (checkpoint or --ids) as "
                         "completed and update throughput counters")
    ap.add_argument("--ids",
                    help="explicit article ids (comma-separated) for scoped "
                         "--qa / --publish / --chunk-complete")
    ap.add_argument("--writer-session",
                    help="writer session identity for the writer lock")
    ap.add_argument("--acquire-writer-lock", action="store_true",
                    help="acquire data/batches/writer-lock.json for this "
                         "batch/session")
    ap.add_argument("--release-writer-lock", action="store_true",
                    help="release the writer lock (graceful completion)")
    ap.add_argument("--writer-lock-status", action="store_true",
                    help="print the current writer lock and freshness")
    ap.add_argument("--checkpoint", action="store_true",
                    help="print the checkpoint reconciled with matrix truth")
    ap.add_argument("--checkpoint-reset", action="store_true",
                    help="delete the checkpoint (matrix truth wins anyway)")
    ap.add_argument("--time-budget-remaining", type=int, default=None,
                    metavar="MIN",
                    help="remaining runtime budget in minutes; <=0 stops "
                         "cleanly before starting a new chunk")
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

    try:
        matrix = lib.load_matrix()
        ownership = lib.load_ownership()
        facts = lib.load_business_facts()
        rubric = lib.load_rubric()
        site = lib.load_site_config()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return EXIT_ERROR

    # -------- writer-lock / checkpoint utilities (no batch mutation) -----
    util_batch = args.batch or next_batch_id(matrix)
    if args.writer_lock_status:
        lock, fresh = writer_lock_status(repo_root)
        print(json.dumps({"lock": lock, "fresh": fresh}, ensure_ascii=False))
        return EXIT_OK
    if args.release_writer_lock:
        if not release_writer_lock(repo_root, args.writer_session):
            print("WRITER-LOCK: not released (owned by another writer "
                  "session).")
            return EXIT_USAGE
        print("WRITER-LOCK: released.")
        return EXIT_OK
    if args.acquire_writer_lock:
        if not util_batch:
            print("ERROR: writer lock needs a batch (--batch or --next).")
            return EXIT_USAGE
        ok, lock = acquire_writer_lock(repo_root, util_batch,
                                       args.writer_session)
        print(json.dumps({"acquired": ok, "lock": lock},
                         ensure_ascii=False))
        if not ok:
            return EXIT_USAGE
        return EXIT_OK
    if args.checkpoint:
        if not util_batch:
            print("ERROR: --checkpoint needs a batch (--batch or --next).")
            return EXIT_USAGE
        cp = reconcile_checkpoint(load_checkpoint(repo_root), matrix,
                                  util_batch)
        save_checkpoint(repo_root, cp)
        print(json.dumps(cp, ensure_ascii=False))
        return EXIT_OK
    if args.checkpoint_reset:
        try:
            os.remove(checkpoint_path(repo_root))
        except OSError:
            pass
        print("CHECKPOINT: reset (the matrix remains the source of truth).")
        return EXIT_OK

    # -------- kill switch: blocks PRODUCTION mutations only --------
    # Safety operations above (writer-lock status/acquire/release,
    # checkpoints, and the batch-less --progress report) run even when
    # the factory is paused; recovery of a pending transaction is a
    # SAFETY operation handled by scripts/js/factory.mjs --recover.
    kill = _load_kill_switch(repo_root)
    if not kill.get("enabled", True):
        print("FACTORY_PAUSED: config/content-factory.json enabled=false "
              "refuses claims/QA/publish with a non-zero exit. Safety "
              "operations still available: --writer-lock-status, "
              "--acquire-writer-lock, --release-writer-lock, --checkpoint, "
              "--checkpoint-reset, --progress, and factory --recover/"
              "--consistency. No changes made.")
        return EXIT_USAGE

    # -------- resolve batch identity ONCE --------
    if args.pilot:
        batch_id = "BATCH-001"
    elif (args.next or args.next_chunk is not None
          or (not args.batch and (args.prepare_agent or args.claim_ids
                                  or args.qa
                                  or args.chunk_complete))):
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
        if args.next_chunk is not None:
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
        chunk = (select_next_chunk_rows(rows, repo_root, args.next_chunk)
                 if args.next_chunk is not None else None)
        print("DRY RUN %s: %d PLANNED claimable, %d QA-able, %d PASS "
              "publishable, statuses: %s" %
              (batch_id, len(claim), len(qa), len(pub),
               sorted({(r.get("status") or "?") for r in rows})))
        if chunk is not None:
            print("DRY RUN %s: next writer chunk = %d row(s): %s" %
                  (batch_id, len(chunk),
                   ",".join(r["article_id"] for r in chunk)))
        if args.progress:
            write_factory_progress(repo_root, matrix)
        return EXIT_OK

    if not acquire_lock(repo_root, batch_id):
        print("LOCKED: another runner holds %s (data/batches/%s.lock, <24h)."
              % (batch_id, batch_id))
        return EXIT_USAGE

    try:
        started_at = now_vn_iso()

        # ---------------- claim-ids (exact-ID claim) ----------------
        # Event-driven factory-publish contract: the push-scope selector
        # (scripts/factory_push_selection.py) derived the EXACT article
        # ids whose files the writer added; claim exactly those rows -
        # never a blind first-N claim of rows whose files do not exist.
        if args.claim_ids:
            wanted = [t.strip() for t in (args.ids or "").split(",")
                      if t.strip()]
            if not wanted:
                print("ERROR: --claim-ids requires --ids with explicit "
                      "article ids.")
                return EXIT_USAGE
            if len(wanted) != len(set(wanted)):
                print("ERROR: duplicate id in --ids: %s"
                      % ", ".join(sorted({i for i in wanted
                                          if wanted.count(i) > 1})))
                return EXIT_USAGE
            if len(wanted) > batch_size:
                print("ERROR: --claim-ids refuses to claim %d rows at "
                      "once (max %d per micro push)."
                      % (len(wanted), batch_size))
                return EXIT_USAGE
            by_id = {}
            for r in rows:
                by_id.setdefault(r.get("article_id"), r)
            claim = []
            for i in wanted:
                r = by_id.get(i)
                if r is None:
                    print("ERROR: %s is not a row of %s - refusing the "
                          "whole claim scope." % (i, batch_id))
                    return EXIT_USAGE
                st = (r.get("status") or "").strip()
                if st != "PLANNED":
                    print("ERROR: %s is %s - --claim-ids only claims "
                          "PLANNED rows (never re-claims; PASS rows "
                          "publish, FAIL/BLOCKED rows need an explicit "
                          "requeue). Refusing the whole claim scope."
                          % (i, st))
                    return EXIT_USAGE
                claim.append(r)
            manifest = build_manifest(batch_id, claim, matrix, ownership,
                                      facts, rubric, site, repo_root)
            write_manifest(repo_root, manifest)
            update_matrix_statuses(repo_root,
                                   {r["article_id"]: {"status": "WRITING"}
                                    for r in claim})
            print("CLAIMED-IDS %s: %d row(s) claimed WRITING: %s. "
                  "Manifest: data/batches/%s.json."
                  % (batch_id, len(claim), ",".join(wanted), batch_id))
            return EXIT_OK

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

        # ---------------- next-chunk (chunked writer mode) ----------------
        if args.next_chunk is not None:
            cp = reconcile_checkpoint(load_checkpoint(repo_root), matrix,
                                      batch_id)
            if (args.time_budget_remaining is not None
                    and args.time_budget_remaining <= 0):
                cp["last_completed_step"] = "time-budget-stop"
                save_checkpoint(repo_root, cp)
                print("TIME-BUDGET: no runtime budget remaining — "
                      "checkpoint saved, NOT starting a new chunk.")
                return EXIT_OK
            if args.writer_session:
                ok, lock = acquire_writer_lock(repo_root, batch_id,
                                               args.writer_session)
                if not ok:
                    print("WRITER-LOCK: %s is owned by fresh session %s. "
                          "Aborting cleanly (never two writers on one "
                          "batch). Checkpoint untouched." %
                          (batch_id, lock.get("writer_session")))
                    return EXIT_USAGE
            chunk = select_next_chunk_rows(rows, repo_root, args.next_chunk)
            if not chunk:
                cp["last_completed_step"] = "no-eligible-chunk"
                save_checkpoint(repo_root, cp)
                print("NO-CHUNK: no unwritten WRITING rows in %s. Run "
                      "scoped QA on the written ones (--ids ... --qa), "
                      "publish the PASS rows together, or --prepare-agent "
                      "if PLANNED rows remain." % batch_id)
                return EXIT_OK
            cp["chunk_size"] = clamp_chunk_size(args.next_chunk)
            cp["current_chunk_ids"] = [r["article_id"] for r in chunk]
            # ordered, duplicate-free union (deterministic matrix order)
            cp["pending_qa_ids"] = list(dict.fromkeys(
                (cp.get("pending_qa_ids") or [])
                + cp["current_chunk_ids"]))
            cp["last_completed_step"] = "chunk-prepared"
            save_checkpoint(repo_root, cp)
            manifest = build_manifest(batch_id, chunk, matrix, ownership,
                                      facts, rubric, site, repo_root)
            manifest["chunk"] = {
                "chunk_size": len(chunk),
                "chunk_ids": list(cp["current_chunk_ids"]),
            }
            write_json(os.path.join(batches_dir(repo_root),
                                    batch_id + "-chunk.json"), manifest)
            print("CHUNK-PREPARED %s: %d row(s): %s. Manifest: "
                  "data/batches/%s-chunk.json. Write these files, then run "
                  "scoped QA: --ids %s --qa" %
                  (batch_id, len(chunk), ",".join(cp["current_chunk_ids"]),
                   batch_id, ",".join(cp["current_chunk_ids"])))
            return EXIT_OK

        # ---------------- chunk-complete ----------------
        if args.chunk_complete:
            cp = reconcile_checkpoint(load_checkpoint(repo_root), matrix,
                                      batch_id)
            ids = ([s.strip() for s in (args.ids or "").split(",")
                    if s.strip()] or cp.get("current_chunk_ids") or [])
            if not ids:
                print("CHUNK-COMPLETE: nothing to complete (no --ids, no "
                      "current chunk in the checkpoint).")
                return EXIT_OK
            by_id = {r.get("article_id"): r for r in rows}
            terminal = ("PASS", "PUBLISHED", "FAIL", "BLOCKED")
            done = [i for i in ids
                    if (by_id.get(i) or {}).get("status", "").strip()
                    in terminal]
            cp["completed_ids"] = sorted(
                set(cp.get("completed_ids") or []) | set(done))
            cp["current_chunk_ids"] = [i for i in
                                       cp.get("current_chunk_ids") or []
                                       if i not in done]
            cp["pending_qa_ids"] = [i for i in
                                    cp.get("pending_qa_ids") or []
                                    if i not in done]
            cp["last_completed_step"] = "chunk-completed"
            save_checkpoint(repo_root, cp)
            if done:
                update_throughput(repo_root, batch_id,
                                  articles_written=len(done), chunks_completed=1)
                if args.writer_session:
                    release_writer_lock(repo_root, args.writer_session)
            print("CHUNK-COMPLETE %s: %d row(s) terminal: %s" %
                  (batch_id, len(done), ",".join(done)))
            return EXIT_OK

        # ---------------- QA (batch-wide or scoped --ids) ----------------
        if args.qa:
            if args.ids:
                try:
                    qa_rows = select_qa_rows_by_ids(
                        rows,
                        [s.strip() for s in args.ids.split(",") if s.strip()],
                        repo_root)
                except ChunkError as e:
                    print("ERROR: %s" % e)
                    return EXIT_USAGE
            else:
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
            # checkpoint: matrix truth wins; QA'd ids leave pending_qa,
            # PASS ids become pending_publish, REPAIR/REVIEW pending_repair
            cp = reconcile_checkpoint(load_checkpoint(repo_root), matrix,
                                      batch_id)
            qa_ids = {r.get("article_id") for r in qa_rows}
            status_by_id = {r.get("article_id"):
                            (r.get("status") or "").strip() for r in rows}
            cp["pending_qa_ids"] = [i for i in
                                    cp.get("pending_qa_ids") or []
                                    if i not in qa_ids]
            for i in sorted(qa_ids):
                st = status_by_id.get(i, "")
                if st == "PASS":
                    cp["pending_publish_ids"] = sorted(
                        set(cp.get("pending_publish_ids") or []) | {i})
                elif st in ("REPAIR", "REVIEW"):
                    cp["pending_repair_ids"] = sorted(
                        set(cp.get("pending_repair_ids") or []) | {i})
            cp["last_completed_step"] = "qa-completed"
            save_checkpoint(repo_root, cp)
            score_sum = sum(a.get("score") for a in articles
                            if isinstance(a.get("score"), int))
            score_n = sum(1 for a in articles
                          if isinstance(a.get("score"), int))
            repairs = sum(1 for a in articles
                          if a.get("outcome") in ("REVIEW", "BLOCKED"))
            update_throughput(repo_root, batch_id,
                              articles_qa_checked=len(articles),
                              qa_score_sum=score_sum,
                              qa_score_count=score_n,
                              repair_count=repairs)
            # CUMULATIVE batch report: every reserved member of the batch,
            # counts derived from the current matrix truth (never just the
            # rows of this run)
            report = build_cumulative_report(
                batch_id, rows, articles, started_at, repo_root)
            write_report(repo_root, report)
            print(json.dumps({k: v for k, v in report.items()
                              if k != "articles"}, ensure_ascii=False))
            # STATE SYNC (never optional): after every QA mutation both
            # reports regenerate from the CURRENT matrix truth, so
            # factory-progress.json and the batch report can never
            # disagree (PASS/WRITING/REPAIR/PUBLISHED counts always match).
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
            if args.ids:
                wanted = [s.strip() for s in args.ids.split(",")
                          if s.strip()]
                known = {r.get("article_id") for r in rows}
                for i in wanted:
                    if i not in known:
                        print("ERROR: %s is not a row of %s — refusing the "
                              "whole publish scope." % (i, batch_id))
                        return EXIT_USAGE
                    if i not in {r.get("article_id") for r in pub}:
                        print("ERROR: %s is not a PASS row of %s with an "
                              "existing file — refusing the whole publish "
                              "scope." % (i, batch_id))
                        return EXIT_USAGE
                pub = [r for r in pub
                       if r.get("article_id") in set(wanted)]
            for r in pub:
                print(r["output_path"])
            print("# publish scope: %s (%d PASS files; other batches' PASS "
                  "rows are NEVER included)" % (batch_id, len(pub)))
            print("# NOTE (deploy gate): factory.mjs --publish promotes any "
                  "draft at _drafts/<output_path> to <output_path> in the "
                  "same transaction — drafts never deploy before publish.")
            if pub:
                print("# grouped publish (all ids in ONE operation):")
                print("node scripts/js/factory.mjs --publish %s --dry-run"
                      % ",".join(r["article_id"] for r in pub))
                print("node scripts/js/factory.mjs --publish %s"
                      % ",".join(r["article_id"] for r in pub))
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