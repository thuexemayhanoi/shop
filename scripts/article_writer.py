#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writer provider interface for the content factory.

The QA tools in this repo are deterministic. Writing high-quality Vietnamese
articles requires a real AI writer (e.g. a Mistral agent) or a human author.
This module ONLY provides the provider abstraction — it deliberately does NOT
generate fake "template" content.

Provider contract:
    class Provider:
        name = "..."
        def write_article(self, matrix_row, context) -> str:
            -> full HTML article body (utf-8)

Provider selection:
    env WRITER_PROVIDER=<registered name>   # registration is manual,
    no credentials are ever committed to this repo.

If no real provider is configured, write_article() raises
WriterNotConfigured and callers must stop with WRITER_NOT_CONFIGURED
(exit code 5). Never fabricate content, never embed API keys.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_WRITER_NOT_CONFIGURED = 5


class WriterNotConfigured(Exception):
    """Raised when no authorized writing provider is available."""


class _NullProvider(object):
    """Placeholder: refuses to write. Never generates content."""

    name = "none"

    def write_article(self, matrix_row, context):
        raise WriterNotConfigured(
            "No writing provider configured. Set up an authorized AI writer "
            "(e.g. Mistral agent via external credentials) or write articles "
            "manually. Refusing to fabricate content.")


_REGISTRY = {}  # populated only by explicitly installed providers


def get_provider():
    """Return the configured provider or a refusing NullProvider."""
    name = os.environ.get("WRITER_PROVIDER", "").strip()
    if name and name in _REGISTRY:
        return _REGISTRY[name]
    return _NullProvider()


def write_article(matrix_row, context=None):
    """Write one article from a matrix row. Raises WriterNotConfigured
    when no provider is configured — callers must stop, not fake content."""
    provider = get_provider()
    return provider.write_article(matrix_row, context or {})


if __name__ == "__main__":
    row = {"article_id": "?", "working_title": "?"}
    try:
        write_article(row)
    except WriterNotConfigured as e:
        print("WRITER_NOT_CONFIGURED: %s" % e)
        sys.exit(EXIT_WRITER_NOT_CONFIGURED)
    print("provider wrote article")  # unreachable without a provider
