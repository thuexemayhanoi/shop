#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scoped QA: change-based candidate selection + QA-evidence reuse.

WHY THIS EXISTS: the Article Quality Gate used to re-scan EVERY production
article on every push, and the publish step re-scanned every PUBLISHED
article a second time. With 400+ articles that is minutes of redundant
work per chunk of 5-10 drafts. This module implements the approved
scoped-QA contract:

  * SCOPE selection (`select_scope`):
      - A change to any globally-affecting file (engine scripts, tests,
        rubric, business facts, ownership, source policy, site config,
        shared templates/includes, the gate workflows themselves) forces
        a FULL scan of every production article.
      - Otherwise only the articles touched by the change are candidates:
        new/modified drafts, new/modified production files (repairs).
        Candidate selection is derived from the matrix + the real repo
        paths (draft first, final as fallback), never from memory.
      - The ALWAYS-GLOBAL checks stay global in every run regardless of
        scope: matrix invariants, duplicate-URL/cannibalization corpus,
        factory consistency, lock/transaction integrity, publish
        hash-QA. They live outside this module (validate_content_matrix,
        factory.mjs --consistency, check_cannibalization corpus checks).

  * FULL is still available and REQUIRED at: manual workflow_dispatch,
    batch-completion milestones, and any global-affecting change.

  * EVIDENCE reuse (`record_evidence` / `evidence_is_reusable`):
      A QA verdict is reusable ONLY while ALL THREE still match:
        1. the article file's content hash (sha256 of bytes),
        2. the QA config hash (rubric + business facts + ownership +
           source policy + site config),
        3. the validator version (article_lib.VALIDATOR_VERSION).
      A changed article, a changed rubric/engine, or a new validator
      version always invalidates old evidence. Old evidence is NEVER used
      for changed content. Evidence only ever records PASS verdicts for
      REAL production matrix article ids; anything else must be
      re-validated.

Deterministic. Standard library only. No network. No AI.
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib  # noqa: E402

REPO = lib.ROOT
EVIDENCE_PATH = os.path.join(REPO, "reports", "article-quality",
                             "qa-evidence.json")

# Changes to any of these affect EVERY article, so they force FULL scope.
# (data/content-matrix.csv is deliberately NOT here: normal chunk
# operations flip a few row statuses per run and the always-global
# matrix/consistency checks cover ledger integrity; per-row truth is
# enforced through the content hash of each candidate file.)
GLOBAL_AFFECTING = (
    "scripts/",
    "tests/",
    "config/article-rubric.json",
    "config/business-facts.json",
    "config/seo-ownership.json",
    "config/source-policy.json",
    "config/site.json",
    "config/content-factory.json",
    "docs/ARTICLE-RULES.md",
    "_includes/",
    "_snippets/",
    "assets/css/",
    ".github/workflows/article-quality.yml",
    ".github/workflows/factory-operator.yml",
)

EVIDENCE_CONFIG_FILES = (
    "config/article-rubric.json",
    "config/business-facts.json",
    "config/seo-ownership.json",
    "config/source-policy.json",
    "config/site.json",
)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def config_sha256(repo_root=None):
    """Hash of every QA-affecting config, in a canonical order."""
    root = repo_root or REPO
    h = hashlib.sha256()
    for rel in EVIDENCE_CONFIG_FILES:
        p = os.path.join(root, rel)
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                h.update(f.read())
        h.update(b"\x00")
    return h.hexdigest()


def is_global_affecting(changed_files):
    for f in changed_files or []:
        f = (f or "").strip().lstrip("/")
        if not f:
            continue
        for pat in GLOBAL_AFFECTING:
            if f == pat or f.startswith(pat):
                return f
    return None


def production_matrix_rows(matrix=None):
    matrix = matrix if matrix is not None else lib.load_matrix()
    return [r for r in matrix if not lib.is_sample_row(r)]


def is_matrix_article(article_id, matrix=None):
    """True for a REAL production matrix article id. QA evidence is only
    ever recorded for real matrix articles (never synthetic test ids)."""
    aid = (article_id or "").strip()
    if not aid:
        return False
    for r in production_matrix_rows(matrix):
        if (r.get("article_id") or "").strip() == aid:
            return True
    return False


def _existing_candidate_path(repo_root, output_path):
    """Draft first, then the final path — mirrors row_written_file()."""
    p = (output_path or "").strip()
    if not p:
        return None
    draft = os.path.join(repo_root, "_drafts", p.lstrip("/"))
    final = os.path.join(repo_root, p)
    if os.path.isfile(draft):
        return draft
    if os.path.isfile(final):
        return final
    return None


def full_candidates(matrix=None, repo_root=None):
    """FULL scope: every production row with a written file (draft or
    final). Same population the old whole-repo gate used, plus drafts."""
    root = repo_root or REPO
    out = []
    for r in production_matrix_rows(matrix):
        path = _existing_candidate_path(root, r.get("output_path"))
        if path:
            out.append(path)
    return sorted(out)


def changed_candidates(changed_files, matrix=None, repo_root=None):
    """Scoped candidates: only rows whose draft or final file changed.

    Returns (candidate_paths, matched_changed_files)."""
    root = repo_root or REPO
    changed = set((f or "").strip().lstrip("/") for f in changed_files or []
                  if (f or "").strip())
    out = []
    matched = set()
    for r in production_matrix_rows(matrix):
        op = (r.get("output_path") or "").strip()
        if not op:
            continue
        draft = os.path.join("_drafts", op).replace("\\", "/")
        if op in changed or draft in changed or draft.lstrip("/") in changed:
            path = _existing_candidate_path(root, op)
            if path:
                out.append(path)
                matched.add(op)
    return sorted(out), sorted(matched)


def select_scope(changed_files, matrix=None, repo_root=None, force_full=False):
    """Decide the QA scope for a run.

    Returns dict:
      scope: "full" | "changed"
      reason: human-readable explanation
      candidates: list of article file paths to validate/score
      reused: list of candidate paths skipped via matching evidence
      checked: list of candidate paths actually re-checked
      matrix_rows_selected: len(candidates)
    Evidence reuse applies inside BOTH scopes: an unchanged article with
    matching content/config/validator hashes is skipped unless the run
    is a forced FULL re-validation (force_full=True disables reuse so a
    manual FULL really revalidates everything).
    """
    root = repo_root or REPO
    trigger = is_global_affecting(changed_files)
    if force_full:
        candidates = full_candidates(matrix, root)
        return _scope_result("full", "manual FULL re-validation",
                             candidates, root, reuse=False)
    if trigger:
        candidates = full_candidates(matrix, root)
        return _scope_result(
            "full", "global-affecting change: %s" % trigger,
            candidates, root, reuse=True)
    candidates, _m = changed_candidates(changed_files, matrix, root)
    if not candidates:
        return {
            "scope": "changed", "reason": "no article files changed",
            "candidates": [], "reused": [], "checked": [],
            "matrix_rows_selected": 0,
        }
    return _scope_result("changed", "article-scoped change",
                         candidates, root, reuse=True)


def _scope_result(scope, reason, candidates, repo_root, reuse):
    cfg = config_sha256(repo_root)
    reused, checked = [], []
    for p in candidates:
        if reuse and _reusable_for_path(p, cfg, repo_root):
            reused.append(p)
        else:
            checked.append(p)
    return {
        "scope": scope,
        "reason": reason,
        "candidates": candidates,
        "reused": reused,
        "checked": checked,
        "matrix_rows_selected": len(candidates),
    }


def _reusable_for_path(path, cfg_sha, repo_root):
    entry = find_evidence_for_path(path, repo_root)
    return bool(entry) and evidence_is_reusable(entry, path, cfg_sha)


def load_evidence(repo_root=None):
    p = os.path.join(repo_root or REPO,
                     "reports", "article-quality", "qa-evidence.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def find_evidence_for_path(path, repo_root=None, matrix=None):
    """Evidence is keyed by article_id; resolve the row for this path."""
    rel = os.path.relpath(os.path.abspath(path), repo_root or REPO)
    ev = load_evidence(repo_root)
    if not ev:
        return None
    for r in production_matrix_rows(matrix):
        op = (r.get("output_path") or "").strip()
        if not op:
            continue
        draft = os.path.join("_drafts", op).replace("\\", "/")
        fin = op
        norm = rel.replace("\\", "/")
        if norm in (draft.lstrip("./"), fin, draft, fin.lstrip("./")):
            return ev.get((r.get("article_id") or "").strip())
    return None


def evidence_is_reusable(entry, path, cfg_sha=None):
    """Reuse only when content hash, config hash and validator version
    ALL still match, and the recorded verdict was PASS."""
    if not isinstance(entry, dict):
        return False
    if entry.get("status") != "PASS":
        return False
    if entry.get("validator_version") != lib.VALIDATOR_VERSION:
        return False
    if not os.path.isfile(path):
        return False
    if entry.get("content_sha256") != file_sha256(path):
        return False
    if entry.get("config_sha256") != (cfg_sha or config_sha256()):
        return False
    return True


def record_evidence(repo_root, entries):
    """Merge PASS evidence entries (list of dicts with article_id,
    content_sha256, config_sha256, validator_version, status, score,
    path, last_checked). Non-PASS entries and non-matrix article ids are
    ignored (they must always be re-validated)."""
    p = os.path.join(repo_root or REPO,
                     "reports", "article-quality", "qa-evidence.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = load_evidence(repo_root)
    for e in entries:
        aid = (e.get("article_id") or "").strip()
        if not aid or e.get("status") != "PASS":
            continue
        if not is_matrix_article(aid):
            continue
        data[aid] = {
            "article_id": aid,
            "content_sha256": e["content_sha256"],
            "config_sha256": e["config_sha256"],
            "validator_version": e["validator_version"],
            "status": "PASS",
            "score": e.get("score"),
            "path": e.get("path"),
            "last_checked": e.get("last_checked"),
        }
    data = {k: data[k] for k in sorted(data)}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p


def record_published_evidence(repo_root, ids, today=None):
    """Record PASS evidence for freshly published production files.
    Called by the factory-operator publish step AFTER the scoped publish
    gate re-validated them at their REAL production paths."""
    import datetime
    by_id = {r.get("article_id"): r for r in production_matrix_rows()}
    cfg = config_sha256(repo_root)
    entries = []
    for i in ids:
        r = by_id.get((i or "").strip())
        if not r:
            continue
        op = (r.get("output_path") or "").strip()
        p = os.path.join(repo_root, op) if op else None
        if not p or not os.path.isfile(p):
            continue
        entries.append({
            "article_id": i.strip(),
            "content_sha256": file_sha256(p),
            "config_sha256": cfg,
            "validator_version": lib.VALIDATOR_VERSION,
            "status": "PASS",
            "score": (r.get("score") or "").strip() or None,
            "path": op,
            "last_checked": today or datetime.date.today().isoformat(),
        })
    if entries:
        record_evidence(repo_root, entries)
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--changed-files", help="file with newline-separated "
                    "changed paths (use /dev/stdin or - for stdin)")
    ap.add_argument("--scope", choices=("auto", "full"), default="auto",
                    help="auto = derive from changed files; full = force "
                    "FULL re-validation (manual/batch-end audits)")
    ap.add_argument("--record-published", help="comma-separated article "
                    "ids just published: refresh their evidence")
    args = ap.parse_args()

    if args.record_published:
        ids = [s.strip() for s in args.record_published.split(",")
               if s.strip()]
        entries = record_published_evidence(REPO, ids)
        print("EVIDENCE-RECORDED %d article(s): %s"
              % (len(entries), ", ".join(e["article_id"] for e in entries)))
        return 0

    changed = []
    if args.changed_files:
        src = sys.stdin if args.changed_files in ("-", "/dev/stdin") \
            else open(args.changed_files, encoding="utf-8")
        with src:
            changed = [ln.strip() for ln in src if ln.strip()]
    result = select_scope(changed, force_full=(args.scope == "full"))
    payload = {
        "scope": result["scope"],
        "reason": result["reason"],
        "candidates": result["candidates"],
        "reused": result["reused"],
        "checked": result["checked"],
        "matrix_rows_selected": result["matrix_rows_selected"],
        "validator_version": lib.VALIDATOR_VERSION,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
