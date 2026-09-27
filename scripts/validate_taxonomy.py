#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the canonical content taxonomy against repository truth.

Checks (all deterministic, no network):
  1. taxonomy files exist (data/content-taxonomy.json + -map.csv)
  2. exactly 2000 production rows mapped, no orphan production row
  3. every production row maps to exactly one parent + one child
  4. every child cluster belongs to exactly one parent (no child reuse)
  5. no orphan child cluster (child with zero mapped articles)
  6. no duplicate child ids / slugs / hub URLs
  7. child's parent agrees with the matrix category of its articles
  8. child hub URL pattern is /shop/cam-nang/chu-de/<child-slug>.html
  9. taxonomy count reconciles with the parent/child article_count fields
  10. map CSV references only production article ids that exist
  11. no cross-repository URLs (/blog/, /aichatbot/) in the taxonomy
  12. taxonomy_version consistency between json and map

Exit 0 = valid, 4 = violation (mirrors validate_content_matrix.py).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_lib as lib
import taxonomy_lib as tlib

EXPECTED_PROD_ROWS = 2000
HUB_RE = re.compile(r"^/shop/cam-nang/chu-de/[a-z0-9-]+\.html$")


def validate(matrix):
    errors = []
    repo_root = lib.ROOT
    tax = tlib.load_taxonomy(repo_root)
    mapping = tlib.load_taxonomy_map(repo_root)

    if not tax:
        return ["data/content-taxonomy.json missing or unreadable"]
    if not mapping:
        return ["data/content-taxonomy-map.csv missing or unreadable"]

    prod = [r for r in matrix if not lib.is_sample_row(r)]
    prod_ids = {r.get("article_id") for r in prod}

    # 2 + 10: exactly the production rows are mapped, nothing else
    if set(mapping) != prod_ids:
        missing = prod_ids - set(mapping)
        extra = set(mapping) - prod_ids
        if missing:
            errors.append("unmapped production rows (%d): %s"
                          % (len(missing), sorted(missing)[:5]))
        if extra:
            errors.append("map rows that are not production ids (%d): %s"
                          % (len(extra), sorted(extra)[:5]))

    # build child -> parent + counts from the map + matrix
    parents = tax.get("parents") or []
    child_to_parent = {}
    child_meta = {}
    for p in parents:
        for c in p.get("children") or []:
            if c["child_id"] in child_to_parent:
                errors.append("duplicate child_id across parents: %s"
                              % c["child_id"])
            child_to_parent[c["child_id"]] = p["parent_id"]
            child_meta[c["child_id"]] = c

    # 6: duplicate slugs / hub urls
    slugs, hubs = {}, {}
    for cid, c in child_meta.items():
        slugs.setdefault(c["child_slug"], []).append(cid)
        hubs.setdefault(c["child_hub_url"], []).append(cid)
    for s, ids in slugs.items():
        if len(ids) > 1:
            errors.append("duplicate child_slug %s: %s" % (s, ids))
    for h, ids in hubs.items():
        if len(ids) > 1:
            errors.append("duplicate child_hub_url %s: %s" % (h, ids))

    # 8: hub url pattern + slug agreement
    for cid, c in child_meta.items():
        want = "/shop/cam-nang/chu-de/%s.html" % c["child_slug"]
        if c["child_hub_url"] != want:
            errors.append("child %s: hub url %s != expected %s"
                          % (cid, c["child_hub_url"], want))
        if not HUB_RE.match(c["child_hub_url"] or ""):
            errors.append("child %s: bad hub url pattern" % cid)
        if c.get("child_slug") != cid.lower().replace("_", "-"):
            errors.append("child %s: slug/child_id mismatch" % cid)

    # 3, 4, 7: per-row checks
    counts = {}
    status_of = {}
    for r in prod:
        aid = r.get("article_id")
        e = mapping.get(aid)
        if not e:
            continue
        if not e["parent_id"] or not e["child_id"]:
            errors.append("row %s: empty parent/child in map" % aid)
            continue
        if e["child_id"] not in child_to_parent:
            errors.append("row %s: unknown child_id %s"
                          % (aid, e["child_id"]))
            continue
        if child_to_parent[e["child_id"]] != e["parent_id"]:
            errors.append("row %s: parent %s does not own child %s"
                          % (aid, e["parent_id"], e["child_id"]))
        if e["child_hub"] != child_meta[e["child_id"]]["child_hub_url"]:
            errors.append("row %s: child_hub disagrees with taxonomy" % aid)
        counts[e["child_id"]] = counts.get(e["child_id"], 0) + 1

    # 5: orphan child clusters
    for cid in child_meta:
        if counts.get(cid, 0) == 0:
            errors.append("orphan child cluster (no articles): %s" % cid)

    # 9: article_count reconciliation
    for cid, c in child_meta.items():
        if c.get("article_count") != counts.get(cid, 0):
            errors.append("child %s: article_count %s != mapped %s"
                          % (cid, c.get("article_count"), counts.get(cid, 0)))

    # 12: taxonomy version agreement
    versions = {e["taxonomy_version"] for e in mapping.values()
                if e["taxonomy_version"]}
    if versions != {tax.get("taxonomy_version") or ""}:
        errors.append("taxonomy_version mismatch between json (%s) and map (%s)"
                      % (tax.get("taxonomy_version"), sorted(versions)))

    # 2: total count
    if len(mapping) != EXPECTED_PROD_ROWS:
        errors.append("map has %d rows, expected %d"
                      % (len(mapping), EXPECTED_PROD_ROWS))

    # 11: no cross-repo URLs anywhere in the taxonomy json
    raw = open(os.path.join(repo_root, "data", "content-taxonomy.json"),
               encoding="utf-8").read()
    for bad in ("/blog/", "/aichatbot/", "vanchinh"):
        if bad in raw:
            errors.append("cross-repository reference %r in taxonomy json" % bad)

    return errors


def main():
    try:
        matrix = lib.load_matrix()
    except lib.ConfigError as e:
        print("ERROR: %s" % e)
        return 4
    errors = validate(matrix)
    if errors:
        print("TAXONOMY INVALID (%d problem(s)):" % len(errors))
        for e in errors:
            print("  ! %s" % e)
        return 4
    print("TAXONOMY OK: taxonomy + map consistent with the 2000-row matrix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
