#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export the gitignored batch manifest as small committed per-row JSON files.

The external operator (the Mistral agent) reads repository files through a
channel with a small size limit, so the one-shot ``data/batches/BATCH-*.json``
manifest (gitignored, and large for 50 rows) is split into
``reports/batches/<BATCH>/rows/<article_id>.json`` files that the operator can
read individually. Deterministic, read-only on the manifest, no network, no AI.
"""
import glob
import json
import os
import sys


def find_articles(node):
    """Find the list of per-article entry dicts inside the manifest."""
    if (
        isinstance(node, list)
        and node
        and all(isinstance(x, dict) for x in node)
        and any(("article_id" in x) or ("id" in x) for x in node)
    ):
        return node
    if isinstance(node, dict):
        for value in node.values():
            found = find_articles(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = find_articles(value)
            if found:
                return found
    return None


def main():
    paths = sorted(glob.glob("data/batches/BATCH-*.json"))
    if not paths:
        print("no batch manifest found", file=sys.stderr)
        return 1
    manifest_path = paths[-1]
    with open(manifest_path, encoding="utf-8") as handle:
        data = json.load(handle)
    batch = os.path.basename(manifest_path)[:-5]
    articles = find_articles(data)
    if not articles:
        print("no article entries found in manifest", file=sys.stderr)
        return 1
    out_dir = os.path.join("reports", "batches", batch, "rows")
    os.makedirs(out_dir, exist_ok=True)
    ids = []
    for entry in articles:
        article_id = entry.get("article_id") or entry.get("id")
        if not article_id:
            continue
        ids.append(article_id)
        with open(
            os.path.join(out_dir, article_id + ".json"), "w", encoding="utf-8"
        ) as handle:
            json.dump(entry, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "_ids.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {"batch": batch, "manifest": manifest_path, "ids": ids},
            handle,
            ensure_ascii=False,
            indent=1,
        )
    print("exported %d rows for %s -> %s" % (len(ids), batch, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
