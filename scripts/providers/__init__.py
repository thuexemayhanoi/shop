#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writer provider package for the content factory.

Provider contract (see scripts/article_writer.py):

    class Provider:
        name = "mistral"            # registry key, selected via WRITER_PROVIDER
        def is_configured(self) -> bool
        def write_article(self, matrix_row, context) -> str   # full HTML
        def repair_article(self, matrix_row, context, html, qa_report) -> str

Providers must NEVER fabricate content when they are not configured: they
raise WriterNotConfigured / WriterSecretMissing instead. Credentials come
from the environment / GitHub Actions Secrets ONLY — never from the repo.

Registry: providers register themselves in PROVIDER_REGISTRY below. New
providers (OpenAI, Anthropic, human-relay, ...) follow the same contract.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from article_writer import WriterNotConfigured, WriterSecretMissing  # noqa: F401

PROVIDER_REGISTRY = {}


def register(provider_cls):
    """Class decorator: add a provider class to the registry by its .name."""
    PROVIDER_REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def load_configured_provider(env=None):
    """Instantiate the provider named by WRITER_PROVIDER (or None)."""
    env = env if env is not None else os.environ
    name = (env.get("WRITER_PROVIDER") or "").strip().lower()
    if not name:
        return None
    # Import the provider module by convention: providers/<name>_writer.py
    mod_name = "providers.%s_writer" % name.replace("-", "_")
    try:
        __import__(mod_name)
    except ImportError:
        return None
    cls = PROVIDER_REGISTRY.get(name)
    return cls(env=env) if cls else None
