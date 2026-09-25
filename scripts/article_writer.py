#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neutral external-writer boundary for the content factory.

The Mistral agent (or a human) is the writer. This repository contains NO
AI API provider, NO credentials and NO template generator: scripts in this
repo are deterministic planning / validation / QA / publishing tools only.

Calling write_article() raises WriterNotConfigured with instructions for
the external agent. Rows are never faked: callers must stop, not fabricate
content or states.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_WRITER_NOT_CONFIGURED = 5


class WriterNotConfigured(Exception):
    """Raised when this module is asked to write. The external Mistral
    agent writes article files itself — there is no in-repo writer."""


def write_article(matrix_row, context=None):
    raise WriterNotConfigured(
        "There is no in-repo writer. The Mistral agent writes article "
        "files DIRECTLY: run scripts/run_article_batch.py --prepare-agent, "
        "read the manifest (data/batches/BATCH-XXX.json), write each "
        "article per docs/ARTICLE-RULES.md at its output_path, then run "
        "--qa. No API, no secrets required. Refusing to fabricate content.")


def repair_article(matrix_row, context=None, html=None, qa_report=None):
    raise WriterNotConfigured(
        "There is no in-repo writer. The Mistral agent repairs REVIEW "
        "articles itself using the exact QA report, then re-runs --qa.")


if __name__ == "__main__":
    try:
        write_article({"article_id": "?"})
    except WriterNotConfigured as e:
        print("WRITER_NOT_CONFIGURED: %s" % e)
        sys.exit(EXIT_WRITER_NOT_CONFIGURED)
