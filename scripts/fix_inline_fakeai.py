#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retire the legacy fake-Gemini logic inlined in legacy HTML pages.

Same semantics as scripts/fix_appjs_fakeai.py but for inline copies of
the old Render app inside HTML pages:
  1. removes the inlined "MotoAI Local Smart Upgrade" block
  2. replaces callGeminiWithRetry with the deterministic smartReply
  3. rewires Render.callGeminiWithRetry( -> Render.smartReply(
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_appjs_fakeai import METHOD_RE, SMART, CONTACT

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INLINE_TOP_RE = re.compile(
    r"    /\* ===== MotoAI Local Smart Upgrade.*?"
    r"(?=    // --- ICONS \(SVG\) ---)", re.S)

FILES = ["nhap.html", "faq.html", "longbien.html", "phoco.html",
         "gioithieu.html", "caugiay.html", "dongda.html"]


def fix(path):
    raw = open(path, encoding="utf-8").read()
    out, n_top = INLINE_TOP_RE.subn("", raw, count=1)
    smart = SMART % {"contact": CONTACT}
    out, n_m = METHOD_RE.subn(lambda _m: smart, out, count=1)
    out = out.replace("Render.callGeminiWithRetry(", "Render.smartReply(")
    open(path, "w", encoding="utf-8").write(out)
    # motoai_removed is False for nhap.html (block already absent there)
    return {"motoai_removed": n_top == 1 or "MotoAI Local Smart Upgrade" not in out,
            "method_replaced": n_m == 1}


def main():
    ok = True
    for rel in FILES:
        path = os.path.join(REPO, rel)
        res = fix(path)
        ok = ok and res["method_replaced"]
        print(rel, res)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
