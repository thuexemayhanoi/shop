#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_factory_state.py — deterministic production-invariant verifier.

The EXACT-FINAL-SHA quality contract of the four-layer hardening:

    INPUT_SHA  -> (operator mutation) -> OP_RESULT_SHA -> push -> FINAL_MAIN_SHA

A workflow exiting 0 is NOT production success. Success is: on the EXACT
tree that was (or will be) pushed, every semantic factory invariant holds
AND the operation's target mutation actually advanced the state.

This tool verifies, on the tree it is pointed at:

  1. matrix invariant        matrix parses; unique ids/slugs/paths; known
                             statuses only
  2. factory consistency     PUBLISHED rows have their public file;
                             non-PUBLISHED rows have no file at the FINAL
                             public path (no unpublished public leaks)
  3. transaction clean       no PENDING recovery marker under
                             data/batches/txn/
  4. sitemap truth           sitemap article namespace == PUBLISHED rows
  5. hub truth               every category hub lists exactly the
                             PUBLISHED articles of its category
  6. report truth            reports/batches/factory-progress.json is
                             schema 2 (+07:00 timestamps, source_head_sha,
                             no legacy matrix_commit_sha) and its counts
                             equal the matrix counts
  7. operation postcondition op-specific: qa recorded QA results for the
                             target rows; publish made every target id
                             PUBLISHED (file + sitemap); requeue requeued
                             the eligible target ids; prepare-next left
                             an active batch (or completed the factory)

Exit contract (fail-closed):
  0  every invariant holds on this exact tree
  1  one or more invariants failed (each problem is printed with ::error)
  2  usage error (bad --op, unknown flags)

Deterministic only: reads repository files, no network, no mutation.
"""
import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import article_lib as lib

HANOI_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+07:00$")
KNOWN_STATUSES = {"PLANNED", "WRITING", "QA", "REPAIR", "REVIEW", "PASS",
                  "PUBLISHED", "FAIL", "BLOCKED"}
ACTIVE_STATUSES = ("WRITING", "QA", "REPAIR", "REVIEW")
QA_RECORDED = ("PASS", "PUBLISHED", "FAIL", "REPAIR", "REVIEW", "BLOCKED")
PROD_ID_RE = re.compile(r"^[A-Z]{2}-\d{4}$")


# --------------------------------------------------------------------- input

def load_rows(repo_root):
    p = os.path.join(repo_root, "data", "content-matrix.csv")
    with io.open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def production_rows(rows):
    return [r for r in rows if not lib.is_sample_row(r)]


def draft_abs(repo_root, output_path):
    return os.path.join(repo_root, "_drafts",
                        (output_path or "").strip())


def final_abs(repo_root, output_path):
    return os.path.join(repo_root, (output_path or "").strip())


def row_written(repo_root, output_path):
    path = (output_path or "").strip()
    if not path:
        return False
    return (os.path.isfile(final_abs(repo_root, path))
            or os.path.isfile(draft_abs(repo_root, path)))


def site_url(repo_root):
    p = os.path.join(repo_root, "config", "site.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("site_url") or ""
    except (OSError, ValueError):
        return ""


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def read_txn_marker(repo_root):
    """Returns the pending-transaction marker dict, or None when clean."""
    p = os.path.join(repo_root, "data", "batches", "txn", "txn.json")
    if not os.path.isfile(p):
        return None
    try:
        m = load_json(p)
    except ValueError:
        return {"state": "CORRUPT"}
    if not isinstance(m, dict):
        return {"state": "CORRUPT"}
    return m


def sitemap_locs(repo_root):
    p = os.path.join(repo_root, "sitemap.xml")
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8") as f:
        return re.findall(r"<loc>([^<]+)</loc>", f.read())


def baseurl(repo_root):
    p = os.path.join(repo_root, "config", "site.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("baseurl") or ""
    except (OSError, ValueError):
        return ""


def hub_article_links(repo_root, hub_file):
    """hrefs of matrix articles inside the hub's ARTICLE-LIST block.

    Hub hrefs are prefixed with the Jekyll baseurl (e.g. /shop/), so the
    prefix is stripped before comparing with matrix output_path values.
    """
    p = os.path.join(repo_root, hub_file)
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"<!--\s*ARTICLE-LIST:START\s*-->(.*?)"
                  r"<!--\s*ARTICLE-LIST:END\s*-->", html, re.S)
    block = m.group(1) if m else html
    bl = baseurl(repo_root).rstrip("/")
    links = set()
    for href in re.findall(r'href="([^"]+)"', block):
        if bl and href.startswith(bl + "/"):
            href = href[len(bl) + 1:]
        links.add(href)
    return links


def active_batch(rows):
    for r in rows:
        if (r.get("status") or "").strip() in ACTIVE_STATUSES:
            return (r.get("batch_id") or "").strip()
    return None


def matrix_counts(rows):
    c = {}
    for r in rows:
        st = (r.get("status") or "").strip() or "unknown"
        c[st] = c.get(st, 0) + 1
    return c


# ----------------------------------------------------------------- invariants

def check_matrix(rows, problems):
    prod = production_rows(rows)
    seen = {}
    for f in ("article_id", "slug", "output_path"):
        for r in prod:
            v = (r.get(f) or "").strip()
            if not v:
                problems.append("matrix: production row missing %s (%r)"
                                % (f, r.get("article_id")))
                continue
            seen.setdefault(f, {})
            seen[f][v] = seen[f].get(v, 0) + 1
    for f, vals in seen.items():
        dups = [v for v, n in vals.items() if n > 1]
        if dups:
            problems.append("matrix: duplicate %s values: %d"
                            % (f, len(dups)))
    for r in prod:
        st = (r.get("status") or "").strip()
        if st not in KNOWN_STATUSES:
            problems.append("matrix: unknown status %r on %s"
                            % (st, r.get("article_id")))


def check_public_files(repo_root, rows, problems):
    for r in production_rows(rows):
        st = (r.get("status") or "").strip()
        op = (r.get("output_path") or "").strip()
        if not op:
            continue
        if st == "PUBLISHED":
            if not os.path.isfile(final_abs(repo_root, op)):
                problems.append("published article missing its public file: "
                                "%s (%s)" % (r.get("article_id"), op))
        else:
            # non-PUBLISHED rows may keep a DRAFT, never the public file
            if os.path.isfile(final_abs(repo_root, op)):
                problems.append(
                    "unpublished public leak: %s is %s but the file exists "
                    "at the public path %s" % (r.get("article_id"), st, op))


def check_txn(repo_root, problems):
    marker = read_txn_marker(repo_root)
    if marker is not None:
        problems.append("pending transaction marker present "
                        "(data/batches/txn/, state=%s) — run factory "
                        "--recover before anything else"
                        % (marker or {}).get("state"))


def check_sitemap(repo_root, rows, problems):
    prod = production_rows(rows)
    base = site_url(repo_root)
    if not base:
        problems.append("sitemap: config/site.json has no site_url")
        return
    locs = sitemap_locs(repo_root)
    if locs is None:
        problems.append("sitemap.xml missing")
        return
    by_url = {}
    for r in prod:
        op = (r.get("output_path") or "").strip()
        if op:
            by_url["%s/%s" % (base.rstrip("/"), op)] = r
    sm_articles = {u for u in locs if u in by_url}
    published_urls = {u for u, r in by_url.items()
                      if (r.get("status") or "").strip() == "PUBLISHED"}
    missing = published_urls - sm_articles
    extra = sm_articles - published_urls
    if missing:
        problems.append("sitemap: %d PUBLISHED article(s) missing from "
                        "sitemap.xml" % len(missing))
    if extra:
        problems.append("sitemap: %d non-PUBLISHED article URL(s) leaked "
                        "into sitemap.xml" % len(extra))


def check_hubs(repo_root, rows, problems):
    """Hub truth mirrors the canonical generator (factory.mjs hubBlock):
    the hub's ARTICLE-LIST block lists EXACTLY the first PER_PAGE (50)
    PUBLISHED rows of the category, in matrix order — plus a 'trang 2'
    continuation link when the category has more than 50 published."""
    per_page = 50
    prod = production_rows(rows)
    by_cat = {}
    for r in prod:
        cat = (r.get("category") or "").strip()
        hub = lib.CATEGORIES.get(cat)
        if not hub:
            problems.append("hub: unknown category %r on %s"
                            % (cat, r.get("article_id")))
            continue
        by_cat.setdefault(hub, []).append(r)
    for hub, rs in sorted(by_cat.items()):
        links = hub_article_links(repo_root, hub)
        if links is None:
            problems.append("hub: %s missing" % hub)
            continue
        op_set = {(r.get("output_path") or "").strip() for r in rs}
        op_set.discard("")
        listed = {l for l in links if l in op_set}
        published = [(r.get("output_path") or "").strip() for r in rs
                     if (r.get("status") or "").strip() == "PUBLISHED"]
        published = [p for p in published if p]
        expected = set(published[:per_page])
        missing = expected - listed
        leaked = listed - expected
        if missing:
            problems.append("hub %s: %d of the first %d PUBLISHED "
                            "article(s) not listed"
                            % (hub, len(missing), len(expected)))
        if leaked:
            problems.append("hub %s: %d non-PUBLISHED/overflow article "
                            "link(s) listed" % (hub, len(leaked)))


def check_progress_report(repo_root, rows, problems):
    """Schema-2 progress report whose counts equal the matrix truth."""
    prod = production_rows(rows)
    p = os.path.join(repo_root, "reports", "batches",
                    "factory-progress.json")
    if not os.path.isfile(p):
        problems.append("reports/batches/factory-progress.json missing")
        return
    try:
        prog = load_json(p)
    except ValueError:
        problems.append("factory-progress.json is not valid JSON")
        return
    if not isinstance(prog, dict):
        problems.append("factory-progress.json is not an object")
        return
    # schema-2 SHA semantics (schema-1 is REJECTED)
    if "matrix_commit_sha" in prog:
        problems.append("schema-1 field 'matrix_commit_sha' must not be "
                        "present (schema-2 records source_head_sha = the "
                        "INPUT sha, never an unstable self-reference)")
    if "source_head_sha" not in prog:
        problems.append("schema-2 field 'source_head_sha' missing")
    if prog.get("schema_version") != 2:
        problems.append("factory-progress.json schema_version != 2")
    if not HANOI_RE.match(prog.get("generated") or ""):
        problems.append("progress 'generated' is not a timezone-aware "
                        "Hanoi timestamp (+07:00): %r"
                        % (prog.get("generated"),))
    # counts must equal the matrix (a stale/hand-patched report is a lie)
    c = matrix_counts(prod)
    for key, st in (("published", "PUBLISHED"), ("pass", "PASS"),
                    ("writing", "WRITING"), ("planned", "PLANNED"),
                    ("fail", "FAIL"), ("blocked", "BLOCKED"),
                    ("qa", "QA"), ("review", "REVIEW"),
                    ("repair", "REPAIR")):
        if prog.get(key) != c.get(st, 0):
            problems.append("progress report %s=%r but matrix has %d %s "
                            "row(s) — the report is stale or hand-patched"
                            % (key, prog.get(key), c.get(st, 0), st))
    if prog.get("total") != len(prod):
        problems.append("progress report total=%r but matrix has %d "
                        "production rows" % (prog.get("total"), len(prod)))
    act = active_batch(prod)
    if prog.get("active_batch") != act:
        problems.append("progress report active_batch=%r but the matrix "
                        "active batch is %r"
                        % (prog.get("active_batch"), act))


def check_batch_report(repo_root, rows, batch_id, problems):
    """The active/asked batch report must be schema-2 and match the matrix."""
    if not batch_id:
        return
    p = os.path.join(repo_root, "reports", "batches", batch_id + ".json")
    if not os.path.isfile(p):
        return   # not every batch has a report yet; progress is the truth
    try:
        rep = load_json(p)
    except ValueError:
        problems.append("%s.json is not valid JSON" % batch_id)
        return
    if not HANOI_RE.match(rep.get("finished_at") or ""):
        problems.append("%s report 'finished_at' is not a timezone-aware "
                        "Hanoi timestamp (+07:00): %r"
                        % (batch_id, rep.get("finished_at")))
    prod = production_rows(rows)
    brows = [r for r in prod
             if (r.get("batch_id") or "").strip() == batch_id]
    c = matrix_counts(brows)
    for key, st in (("published", "PUBLISHED"), ("pass", "PASS"),
                    ("writing", "WRITING"), ("fail", "FAIL"),
                    ("blocked", "BLOCKED"), ("review", "REVIEW"),
                    ("repair", "REPAIR")):
        if key in rep and rep.get(key) != c.get(st, 0):
            problems.append("%s report %s=%r but the matrix batch rows "
                            "have %d %s row(s)"
                            % (batch_id, key, rep.get(key),
                               c.get(st, 0), st))


# -------------------------------------------------------- op postconditions

def _target_rows(rows, ids, batch_id, problems):
    prod = production_rows(rows)
    by_id = {r.get("article_id"): r for r in prod}
    if ids:
        out = []
        for i in ids:
            r = by_id.get(i)
            if r is None:
                problems.append("operation target id %s is not a "
                                "production row" % i)
            else:
                out.append(r)
        return out
    if batch_id:
        brows = [r for r in prod
                 if (r.get("batch_id") or "").strip() == batch_id]
        if not brows:
            problems.append("operation target batch %s does not exist"
                            % batch_id)
        return brows
    return prod


def check_op_postcondition(repo_root, rows, op, ids, batch_id, problems):
    targets = _target_rows(rows, ids, batch_id, problems)

    if op == "qa":
        # every QA'd row that has a written file must carry a QA-recorded
        # status; rows the writer has not written yet may stay WRITING.
        for r in targets:
            st = (r.get("status") or "").strip()
            if st in ("WRITING", "QA") and row_written(
                    repo_root, r.get("output_path")):
                problems.append("qa postcondition: %s has a written file "
                                "but is still %s (QA result was not "
                                "recorded)" % (r.get("article_id"), st))

    elif op == "publish":
        if not ids:
            problems.append("publish postcondition: --ids required")
            return
        base = site_url(repo_root)
        locs = set(sitemap_locs(repo_root) or [])
        for r in targets:
            st = (r.get("status") or "").strip()
            op_path = (r.get("output_path") or "").strip()
            if st != "PUBLISHED":
                problems.append("publish postcondition: %s is still %s"
                                % (r.get("article_id"), st))
                continue
            if not os.path.isfile(final_abs(repo_root, op_path)):
                problems.append("publish postcondition: %s has no public "
                                "file at %s" % (r.get("article_id"), op_path))
            if base and "%s/%s" % (base.rstrip("/"), op_path) not in locs:
                problems.append("publish postcondition: %s missing from "
                                "sitemap.xml" % r.get("article_id"))

    elif op == "requeue":
        if not ids:
            problems.append("requeue postcondition: --ids required")
            return
        for r in targets:
            st = (r.get("status") or "").strip()
            if st in ("REPAIR", "REVIEW"):
                problems.append("requeue postcondition: %s is still %s "
                                "(the requeue did not happen)"
                                % (r.get("article_id"), st))
            # PLANNED = requeued; PASS/PUBLISHED/FAIL/BLOCKED = the tool
            # legitimately refused (exit 3) and recorded the refusal.

    elif op == "prepare-next":
        # after a successful prepare-next either an active batch exists
        # (rows claimed WRITING) or the factory has no claimable rows left
        prod = production_rows(rows)
        has_active = any((r.get("status") or "").strip() in ACTIVE_STATUSES
                         for r in prod)
        has_planned = any((r.get("status") or "").strip() == "PLANNED"
                          for r in prod)
        if has_planned and not has_active:
            problems.append("prepare-next postcondition: PLANNED rows "
                            "remain but no active batch exists — the "
                            "claim did not happen")

    elif op == "consistency":
        pass   # state invariants only

    else:
        problems.append("unknown op %r" % op)


# ------------------------------------------------------------------- driver

def verify(repo_root, op="consistency", ids=None, batch_id=None):
    """Returns (problems, ok). Read-only; never mutates anything."""
    problems = []
    rows = load_rows(repo_root)
    prod = production_rows(rows)

    check_matrix(rows, problems)
    check_public_files(repo_root, rows, problems)
    check_txn(repo_root, problems)
    check_sitemap(repo_root, rows, problems)
    check_hubs(repo_root, rows, problems)
    check_progress_report(repo_root, rows, problems)
    act = batch_id or active_batch(prod)
    check_batch_report(repo_root, rows, act, problems)
    check_op_postcondition(repo_root, rows, op, ids, batch_id, problems)
    return problems, not problems


def main_func(argv=None):
    ap = argparse.ArgumentParser(
        description="Verify the semantic factory state of an exact tree.")
    ap.add_argument("--repo-root", default=ROOT,
                    help="repository root to verify (default: this repo)")
    ap.add_argument("--op", default="consistency",
                    choices=["consistency", "qa", "publish", "requeue",
                              "prepare-next"],
                    help="the operation whose postcondition must hold")
    ap.add_argument("--ids", default="",
                    help="comma-separated target article ids")
    ap.add_argument("--batch", default="",
                    help="target batch id (qa/prepare-next)")
    args = ap.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    ids = [s.strip() for s in (args.ids or "").split(",") if s.strip()]
    problems, ok = verify(repo_root, op=args.op, ids=ids,
                          batch_id=(args.batch or "").strip() or None)
    for p in problems:
        print("::error::[verify_factory_state] %s" % p)
    if ok:
        print("PRODUCTION_INVARIANT=PASS (op=%s on %s)"
              % (args.op, repo_root))
        return 0
    print("PRODUCTION_INVARIANT=FAIL (%d problem(s), op=%s)"
          % (len(problems), args.op))
    return 1


if __name__ == "__main__":
    sys.exit(main_func())