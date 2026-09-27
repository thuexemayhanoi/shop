#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot deterministic patch for gioithieu.html (desktop header wrap).

Applied to the RESTORED known-good content. Pure string replacements,
no content/SEO/canonical/schema changes. Fails loudly if any anchor is
missing so a bad state can never be committed silently.
"""
import io
import sys

REPLACEMENTS = [
    ("padding: 8px 12px; border-radius: 100px;\n        transition: 0.3s; box-shadow: 0 10px 30px rgba(0,0,0,0.05);",
     "padding: 8px 12px; border-radius: 100px; flex-wrap: nowrap;\n        transition: 0.3s; box-shadow: 0 10px 30px rgba(0,0,0,0.05);"),
    (".desktop-nav { display: flex; gap: 4px; }",
     ".desktop-nav { display: flex; gap: 4px; flex-wrap: nowrap; white-space: nowrap; }"),
    ("padding: 8px 16px; border-radius: 20px; font-size: 0.95rem; font-weight: 600;",
     "padding: 8px 11px; border-radius: 20px; font-size: 0.9rem; font-weight: 600;"),
    (".logo-title { font-size: 1.1rem; font-weight: 800; margin: 0; line-height: 1; display: block; color: var(--text-main); }",
     ".logo-title { font-size: 1.1rem; font-weight: 800; margin: 0; line-height: 1; display: block; color: var(--text-main); white-space: nowrap; }"),
    (".logo-text span { font-size: 0.75rem; font-weight: 600; color: var(--text-sub); letter-spacing: 1px; display: block; }",
     ".logo-text span { font-size: 0.75rem; font-weight: 600; color: var(--text-sub); letter-spacing: 1px; display: block; white-space: nowrap; }"),
    (".status-text { font-size: 0.75rem; font-weight: 700; color: var(--text-main); white-space: nowrap; }",
     ".status-text { font-size: 0.75rem; font-weight: 700; color: var(--text-main); white-space: nowrap; }\n    @media (max-width: 1280px) { .status-widget { display: none; } }\n    @media (max-width: 1180px) { .search-input { width: 130px; } .search-input:focus { width: 170px; } }"),
]

def main():
    path = "gioithieu.html"
    with io.open(path, encoding="utf-8") as f:
        text = f.read()
    missing = [old for old, _ in REPLACEMENTS if old not in text]
    if missing:
        for m in missing:
            sys.stderr.write("MISSING ANCHOR: %s...\n" % m[:60])
        return 1
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    if not text.rstrip().endswith("</html>"):
        sys.stderr.write("restored file truncated: no closing </html>\n")
        return 1
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("gioithieu.html restored + patched (%d bytes)" % len(text.encode("utf-8")))
    return 0

if __name__ == "__main__":
    sys.exit(main())
