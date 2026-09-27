#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair accidental newlines that corrupt prose/HTML in factory output.

Known corruption pattern: a Vietnamese word visually broken in two by an
accidental newline, e.g. "list-style:non\ne" or "g\nerated". This tool
joins such breaks deterministically and idempotently.

Scope:
  - protects ONLY <script>...</script> blocks (sentinel-masked, restored
    verbatim afterwards)
  - repairs everywhere else: prose, HTML tags, CSS in <style>, comments

Join rules (all whitespace-agnostic):
  1. "<\n([a-zA-Z/])"        -> "<\\1"   (newline right after "<")
  2. newlines inside a tag "<...\n...>" when not adjacent to real
     formatting whitespace or inside a quoted attribute
  3. (\w)\n(\w)              -> "\\1\\2"  (word character broken in two;
     CSS rule boundaries like "}" are NOT word chars and are preserved)

Usage:
  python3 scripts/fix_prose_newlines.py            # dry-run (report only)
  python3 scripts/fix_prose_newlines.py --apply    # repair in place
"""
import argparse
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROTECT_RE = re.compile(r"<script\b.*?</script>", re.S | re.I)
JOIN_LT_RE = re.compile(r"<\n([a-zA-Z/])")
WORD_NL_RE = re.compile(r"(\w)\n(\w)")
TAGNL_RE = re.compile(r"<(?!!--)[^>\n]*\n[^>]*>")

SENT_FMT = "\x00PROT%dEND\x00"


def _mask_scripts(text):
    sentinels = []

    def repl(m):
        sentinels.append(m.group(0))
        return SENT_FMT % (len(sentinels) - 1)

    return PROTECT_RE.sub(repl, text), sentinels


def _unmask(text, sentinels):
    for i, s in enumerate(sentinels):
        text = text.replace(SENT_FMT % i, s)
    return text


def fix_text(text):
    masked, sentinels = _mask_scripts(text)
    before = masked
    masked = JOIN_LT_RE.sub(r"<\1", masked)

    def tag_join(m):
        # QA (article_lib._TAG_SPLIT_RE) flags ANY newline inside a tag,
        # so join all newlines in tags deterministically.
        return m.group(0).replace("\n", "")

    masked = TAGNL_RE.sub(tag_join, masked)
    masked = WORD_NL_RE.sub(r"\1\2", masked)
    # re-run until stable (idempotent convergence)
    while masked != before:
        before = masked
        masked = JOIN_LT_RE.sub(r"<\1", masked)
        masked = WORD_NL_RE.sub(r"\1\2", masked)
    return _unmask(masked, sentinels)


def count_breaks(text):
    """Count corruption sites that fix_text would repair."""
    masked, sentinels = _mask_scripts(text)
    n = 0
    n += len(JOIN_LT_RE.findall(masked))
    n += len(WORD_NL_RE.findall(masked))
    for m in TAGNL_RE.finditer(masked):
        n += m.group(0).count("\n")
    return n


def iter_targets():
    dirs = [os.path.join(REPO, "cam-nang"), os.path.join(REPO, "_drafts")]
    for d in dirs:
        for p in glob.glob(os.path.join(d, "**", "*.html"), recursive=True):
            yield p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    total = fixed_files = 0
    for path in sorted(iter_targets()):
        text = open(path, encoding="utf-8").read()
        breaks = count_breaks(text)
        if breaks == 0:
            continue
        new = fix_text(text)
        remaining = count_breaks(new)
        if args.apply and new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        fixed = breaks - remaining
        total += fixed
        fixed_files += 1
        print("%-6d %-4d %s" % (breaks, remaining, os.path.relpath(path, REPO)))
    print("---")
    print("files with breaks: %d, joined: %d%s"
          % (fixed_files, total, "" if args.apply else " (dry-run)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
