#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retire the legacy fake-Gemini logic from the shared Render apps.

What it does per file (app.js / app-rental.js / app-info.js):
  1. Removes the leading "MotoAI Local Smart Upgrade" block (MOTO_AI_CTX,
     motoAI_Action, motoAI_Upgrade, action lock) up to the ICONS section.
  2. Replaces callGeminiWithRetry (which never called any API and could
     recommend unsupported inventory such as XR150) with smartReply: a
     deterministic, business-fact-safe responder built only from
     approved facts (prices, contact).
  3. Rewires Render.callGeminiWithRetry( call sites to Render.smartReply(.

It must NOT pretend to call Gemini/AI and must NOT recommend inventory
that business truth does not confirm.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOP_RE = re.compile(r"\A.*?(?=    // --- ICONS \(SVG\) ---)", re.S)

METHOD_RE = re.compile(
    r' *// --- CORE: FAKE "GEMINI" OFFLINE(?:, KHÔNG CẦN API)? ---\n'
    r" *async callGeminiWithRetry\(prompt, systemInstruction, "
    r"onLoading, onSuccess, onError\).*?"
    r"\n *\},\n[ \t]*\n"
    r"(?= *(?:// --- [^\n]* ---\n)? *setupAI\(\) \{)",
    re.S)

CONTACT = ("Liên hệ Mr Tú qua Zalo/điện thoại 0816659199 để xác nhận "
           "thông tin hiện tại.")

SMART = '''        // --- Deterministic local assistant (no AI, no API) ---
        // Business-fact-safe: prices from the approved pricing truth,
        // everything else defers to direct contact with Mr Tú.
        smartReply(prompt, systemInstruction, onLoading, onSuccess, onError) {
            try {
                onLoading();
                const text = String(prompt || " ").toLowerCase();
                const wrap = (msg) => msg.replace(/\\s+/g, " ").trim();

                let answer;
                if (/giá|bao nhiêu|price|cost|tầm bao|budget|ngân sách/.test(text)) {
                    answer = wrap(
                        "Giá thuê hiện hành: Honda Wave / Yamaha Sirius / Honda Click / Yamaha Mio 150.000đ/ngày; " +
                        "Honda Vision / Honda Air Blade / xe điện 200.000đ/ngày. " +
                        "Giá theo tuần/tháng và các dòng xe khác: %(contact)s"
                    );
                } else if (/xe|thuê|đi|chuyến|máy/.test(text)) {
                    answer = wrap(
                        "Em hỗ trợ thông tin thuê xe máy tại Hà Nội. Dòng xe và tình trạng sẵn có thay đổi theo từng ngày, " +
                        "nên anh/chị cho em biết nhu cầu, em sẽ xác nhận xe phù hợp. %(contact)s"
                    );
                } else {
                    answer = wrap(
                        "Em hỗ trợ thông tin thuê xe máy tại Hà Nội. %(contact)s"
                    );
                }
                setTimeout(() => onSuccess(answer), 400);
            } catch (err) {
                if (onError) onError(err.message || "Local assistant error");
            }
        },
'''

FILES = ["assets/js/app.js", "assets/js/app-rental.js", "assets/js/app-info.js"]


def fix(path):
    raw = open(path, encoding="utf-8").read()
    out = TOP_RE.sub("", raw, count=1)
    smart = SMART % {"contact": CONTACT}
    out, n = METHOD_RE.subn(lambda _m: smart, out, count=1)
    out = out.replace("Render.callGeminiWithRetry(", "Render.smartReply(")
    out = out.replace("this.callGeminiWithRetry(", "this.smartReply(")
    open(path, "w", encoding="utf-8").write(out)
    return {"top_removed": not out.lstrip().startswith("/*"),
            "method_replaced": n == 1}


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
