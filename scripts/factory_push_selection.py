#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory_push_selection.py - deterministic push-scope selection for the
event-driven factory-publish workflow (Simple Production Mode).

Ported from the thuexemayhanoi/vanchinh design and adapted to the /shop
deploy-gate drafts model: article files for rows that are NOT yet
PUBLISHED live under _drafts/<output_path>; scripts/js/factory.mjs
--publish promotes a draft to its REAL output_path inside the same
transaction. The selector therefore maps BOTH forms (_drafts/<path> and
the final <path>) back to the row's output_path.

The workflow MUST claim/QA/publish exactly the article IDs whose files
the writer actually added/modified in the push - never a blind
limit-based claim that grabs PLANNED rows whose files do not exist.

Inputs (newline-separated path lists, one path per line):
  --added <file>     paths ADDED in this push    (git diff --diff-filter=A)
  --modified <file>  paths MODIFIED in this push (git diff --diff-filter=M)

Output: JSON on stdout describing the exact, verifiable scope:
  {
    "proceed": bool,          # false => workflow skips everything
    "mode": "new"|"repair"|"backlog"|"skip",
    "batch": "BATCH-012"|null,
    "claim_ids": [...],      # PLANNED -> WRITING claim targets (never >50)
    "qa_ids": [...],         # explicit scoped-QA targets (claim + repair)
    "publish_ids": [...],    # already-PASS touched rows (publish, no re-QA)
    "refuse": null|"reason", # non-null => the push violates the contract
    "published_edits": [...],  # audit: PUBLISHED-row edits (ignored)
    "unmapped_paths": [...]   # audit: touched paths without a matrix row
  }

Selection rules (deterministic, matrix truth):
  NEW mode:     PLANNED rows of the active batch whose output_path is in
                the touched list (added or modified, draft or final
                form) AND the file exists. More than 50 => REFUSE (the
                writer must push at most 50 new article files per
                commit; the production micro-loop pushes 2). A PLANNED
                row whose file is NOT touched (or missing) is NEVER
                claimed.
  REPAIR mode:  rows of the active batch in WRITING/QA/REVIEW/REPAIR
                whose file is touched AND exists -> scoped QA targets;
                PASS rows touched -> direct publish targets. A repair
                push NEVER claims fresh PLANNED rows.
  BACKLOG mode: nothing claimable/repairable in this push, but PLANNED
                rows of the active batch already have files in the repo
                (e.g. a previous pipeline failure before the claim).
                Deterministic first-50 by article_id.
  SKIP:         nothing to do (e.g. tooling-only push, or the factory's
                own state commit re-triggering this workflow on the
                promoted PUBLISHED files).
  REFUSE:       > 50 new article files, or the push touches rows of a
                batch OTHER than the active batch (the writer must
                write the active batch's rows only). Edits to PUBLISHED
                rows (shell rebuilds, repair-in-place) are IGNORED and
                never claim anything.

Exit codes: 0 ok, 3 refuse (contract violation; state unchanged).
"""
import argparse
import json
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import article_lib as lib

TERMINAL = ("PUBLISHED", "BLOCKED", "FAIL")
ACTIVE = ("WRITING", "QA", "REVIEW", "REPAIR")
MAX_CLAIM = 50  # hard cap per push (= one full batch); the production
                # micro-loop pushes exactly 2 new drafts per pair

DRAFTS_PREFIX = "_drafts/"


def read_paths(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [line.strip() for line in p.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def article_output_path(repo_path):
    """Map a repository path to a matrix output_path.

    _drafts/cam-nang/<cat>/<slug>.html -> cam-nang/<cat>/<slug>.html
    cam-nang/<cat>/<slug>.html          -> itself
    anything else (hubs, taxonomies, tooling) -> None
    """
    p = (repo_path or "").strip()
    if p.startswith(DRAFTS_PREFIX):
        p = p[len(DRAFTS_PREFIX):]
    if p.startswith("cam-nang/"):
        return p
    return None


def production_rows():
    return [r for r in lib.load_matrix() if not lib.is_sample_row(r)]


def active_or_next_batch(rows):
    """Same resolution order as run_article_batch.next_batch_id():
    resume the active batch (WRITING/QA/REPAIR/REVIEW rows) first; only
    when no batch is unfinished select the first batch with PLANNED
    rows. FAIL/BLOCKED never block later batches."""
    order = []
    for r in rows:
        b = (r.get("batch_id") or "").strip()
        if b and b not in order:
            order.append(b)
    for b in order:
        if any((r.get("status") or "").strip() in ACTIVE
               for r in rows if (r.get("batch_id") or "").strip() == b):
            return b
    for b in order:
        if any((r.get("status") or "").strip() == "PLANNED"
               for r in rows if (r.get("batch_id") or "").strip() == b):
            return b
    return None


def row_has_file(row):
    """The row's article file exists at the draft or the final path."""
    op = (row.get("output_path") or "").strip()
    if not op:
        return False
    if pathlib.Path(lib.repo_path("_drafts", op.lstrip("/"))).is_file():
        return True
    return pathlib.Path(lib.repo_path(op.lstrip("/"))).is_file()


def select(added, modified):
    rows = production_rows()
    batch = active_or_next_batch(rows)
    out = {"proceed": False, "mode": "skip", "batch": batch,
           "claim_ids": [], "qa_ids": [], "publish_ids": [],
           "refuse": None, "published_edits": [], "unmapped_paths": []}
    if batch is None:
        return out
    by_output_path = {}
    for r in rows:  # duplicate output paths are a matrix violation; first wins
        op = (r.get("output_path") or "").strip()
        if op:
            by_output_path.setdefault(op, r)

    touched_paths = [p for p in (added + modified) if p]
    mapped = []       # (repo_path, output_path, row_or_None)
    for p in touched_paths:
        op = article_output_path(p)
        if op is None:
            continue  # structural/tooling path - not an article row
        mapped.append((p, op, by_output_path.get(op)))

    for p, op, row in mapped:
        if row is None:
            out["unmapped_paths"].append(p)  # audit only; never blocks
            continue
        st = (row.get("status") or "").strip()
        rb = (row.get("batch_id") or "").strip()
        if st == "PUBLISHED":
            out["published_edits"].append(p)  # shell/rebuild edits - ignored
            continue
        if rb != batch:
            out["refuse"] = (
                "push touches %s row %s of batch %s while %s is the "
                "active batch - write only rows of the active batch"
                % (st or "unknown-status", row.get("article_id"), rb, batch))
            return out
    touched_output_paths = {op for _, op, _ in mapped}

    br = [r for r in rows if (r.get("batch_id") or "").strip() == batch]

    # NEW: PLANNED rows of the active batch whose file was touched.
    new_ids = sorted(r["article_id"] for r in br
                     if (r.get("status") or "").strip() == "PLANNED"
                     and (r.get("output_path") or "").strip()
                     in touched_output_paths
                     and row_has_file(r))
    # REPAIR: active (WRITING/QA/REVIEW/REPAIR) rows touched -> scoped QA.
    repair_ids = sorted(r["article_id"] for r in br
                        if (r.get("status") or "").strip() in ACTIVE
                        and (r.get("output_path") or "").strip()
                        in touched_output_paths
                        and row_has_file(r))
    # Already-PASS rows touched -> publish directly (never re-QA'd).
    pass_ids = sorted(r["article_id"] for r in br
                      if (r.get("status") or "").strip() == "PASS"
                      and (r.get("output_path") or "").strip()
                      in touched_output_paths
                      and row_has_file(r))

    if new_ids and len(new_ids) > MAX_CLAIM:
        out["refuse"] = ("push adds %d new article files; max %d per "
                         "commit - split the push deterministically"
                         % (len(new_ids), MAX_CLAIM))
        return out
    if new_ids:
        out["mode"] = "new"
        out["claim_ids"] = new_ids
        out["qa_ids"] = sorted(set(new_ids) | set(repair_ids))
        out["publish_ids"] = pass_ids
        out["proceed"] = True
        return out
    if repair_ids or pass_ids:
        # repair/resume push: process EXACTLY these IDs; never claim
        # fresh PLANNED rows on a repair push.
        out["mode"] = "repair"
        out["qa_ids"] = repair_ids
        out["publish_ids"] = pass_ids
        out["proceed"] = True
        return out
    # BACKLOG: PLANNED rows whose files already exist (no files in this
    # push) - recovery for a pipeline failure between file add and claim.
    backlog = sorted((r["article_id"] for r in br
                      if (r.get("status") or "").strip() == "PLANNED"
                      and row_has_file(r)))[:MAX_CLAIM]
    if backlog:
        out["mode"] = "backlog"
        out["claim_ids"] = backlog
        out["qa_ids"] = backlog
        out["proceed"] = True
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--added", default=None,
                    help="file with newline-separated added paths")
    ap.add_argument("--modified", default=None,
                    help="file with newline-separated modified paths")
    args = ap.parse_args()
    added = read_paths(args.added) if args.added else []
    modified = read_paths(args.modified) if args.modified else []
    out = select(added, modified)
    print(json.dumps(out, ensure_ascii=False))
    return 3 if out["refuse"] else 0


if __name__ == "__main__":
    sys.exit(main())
