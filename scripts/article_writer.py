#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writer provider interface for the content factory.

The QA tools in this repo are deterministic. Writing high-quality Vietnamese
articles requires a real AI writer (e.g. the Mistral provider) or a human
author. This module provides the provider abstraction — it NEVER generates
fake "template" content.

Provider contract:
    class Provider:
        name = "..."                    # registry key via WRITER_PROVIDER
        def is_configured(self) -> bool
        def write_article(matrix_row, context) -> str    # full HTML article
        def repair_article(matrix_row, context, html, qa_report) -> str

Provider selection:
    env WRITER_PROVIDER=<registered name>  e.g. WRITER_PROVIDER=mistral
    Providers live in scripts/providers/<name>_writer.py and register
    themselves. Credentials come from the environment / GitHub Actions
    Secrets ONLY — never committed.

Error policy (safe stop, never fake content):
    - no provider configured        -> WriterNotConfigured  / exit 5
    - provider configured but its
      secret (e.g. MISTRAL_API_KEY)
      is missing                    -> WriterSecretMissing  / exit 6
    Rows always stay safe (PLANNED) — callers must NOT fabricate states.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_WRITER_NOT_CONFIGURED = 5
EXIT_WRITER_SECRET_MISSING = 6


class WriterNotConfigured(Exception):
    """Raised when no authorized writing provider is available."""


class WriterSecretMissing(Exception):
    """Raised when a provider is selected but its API key is absent."""


class _NullProvider(object):
    """Placeholder: refuses to write. Never generates content."""

    name = "none"

    def is_configured(self):
        return False

    def write_article(self, matrix_row, context):
        raise WriterNotConfigured(
            "No writing provider configured. Set WRITER_PROVIDER (e.g. "
            "WRITER_PROVIDER=mistral plus MISTRAL_API_KEY via environment "
            "or GitHub Actions Secrets) or write articles manually. "
            "Refusing to fabricate content.")

    def repair_article(self, matrix_row, context, html, qa_report):
        raise WriterNotConfigured(
            "No writing provider configured. Repair is impossible; "
            "refusing to fabricate content.")


def get_provider():
    """Return the configured provider or a refusing NullProvider."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from providers import load_configured_provider
        provider = load_configured_provider()
        if provider is not None:
            return provider
    except ImportError:
        pass
    return _NullProvider()


def write_article(matrix_row, context=None):
    """Write one article from a matrix row. Raises WriterNotConfigured /
    WriterSecretMissing when no authorized provider is available — callers
    must stop, not fake content."""
    provider = get_provider()
    return provider.write_article(matrix_row, context or {})


if __name__ == "__main__":
    row = {"article_id": "?", "working_title": "?"}
    try:
        write_article(row)
    except WriterNotConfigured as e:
        print("WRITER_NOT_CONFIGURED: %s" % e)
        sys.exit(EXIT_WRITER_NOT_CONFIGURED)
    except WriterSecretMissing as e:
        print("WRITER_SECRET_MISSING: %s" % e)
        sys.exit(EXIT_WRITER_SECRET_MISSING)
    print("provider wrote article")  # only with a real configured provider
