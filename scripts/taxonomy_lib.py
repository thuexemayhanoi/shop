#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared loader for the canonical content taxonomy.

Single source of truth for taxonomy data across factory tooling:

  - data/content-taxonomy.json      parents + child clusters (canonical)
  - data/content-taxonomy-map.csv   article_id -> parent/child mapping

Nothing here mutates the content matrix. If the taxonomy files are absent
(pre-structure repositories / test fixtures), the loaders return empty
structures and callers must degrade gracefully: taxonomy is required for
PRODUCTION runs (validate_taxonomy.py enforces it) but must never break
tooling that only reads the matrix.
"""
import csv
import io
import json
import os

import article_lib as lib


def taxonomy_path(repo_root):
    return os.path.join(repo_root, "data", "content-taxonomy.json")


def map_path(repo_root):
    return os.path.join(repo_root, "data", "content-taxonomy-map.csv")


def load_taxonomy(repo_root=None):
    """Return the taxonomy dict, or {} when the file does not exist."""
    repo_root = repo_root or lib.ROOT
    p = taxonomy_path(repo_root)
    if not os.path.exists(p):
        return {}
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def load_taxonomy_map(repo_root=None):
    """Return {article_id: {parent_id, child_id, child_hub, taxonomy_version}}.

    Empty dict when the map file does not exist.
    """
    repo_root = repo_root or lib.ROOT
    p = map_path(repo_root)
    if not os.path.exists(p):
        return {}
    out = {}
    with io.open(p, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out[r["article_id"]] = {
                "parent_id": (r.get("parent_id") or "").strip(),
                "child_id": (r.get("child_id") or "").strip(),
                "child_hub": (r.get("child_hub") or "").strip(),
                "taxonomy_version": (r.get("taxonomy_version") or "").strip(),
            }
    return out


def child_index(taxonomy):
    """{child_id: child dict} across all parents."""
    out = {}
    for parent in (taxonomy or {}).get("parents", []):
        for c in parent.get("children", []):
            out[c["child_id"]] = c
    return out


def writer_taxonomy_fields(article_id, repo_root=None):
    """Taxonomy fields for one article manifest, or None when unmapped."""
    mapping = load_taxonomy_map(repo_root)
    entry = mapping.get(article_id)
    if not entry:
        return None
    tax = load_taxonomy(repo_root)
    child = child_index(tax).get(entry["child_id"])
    parent = None
    for p in (tax or {}).get("parents", []):
        if p.get("parent_id") == entry.get("parent_id"):
            parent = p
            break
    return {
        "parent_id": entry["parent_id"],
        "parent_title": (parent or {}).get("parent_title", ""),
        "parent_hub": (parent or {}).get("parent_hub", ""),
        "child_cluster": entry["child_id"],
        "child_title": (child or {}).get("child_title", ""),
        "child_slug": (child or {}).get("child_slug", ""),
        "child_hub": entry["child_hub"],
        "taxonomy_version": entry["taxonomy_version"],
    }
