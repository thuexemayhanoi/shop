# MotoAI — RETIRED (historical note)

This file documents a RETIRED feature. It is kept for history only.

## Status

The legacy MotoAI "local smart upgrade" (MOTO_AI_CTX, motoAI_Action,
motoAI_Upgrade, callGeminiWithRetry) was a simulated offline chat that
never called any AI API and could recommend inventory not confirmed by
business truth (e.g. XR150). It has been removed from:

- `assets/js/app.js`, `assets/js/app-rental.js`, `assets/js/app-info.js`
- the inline copies in `nhap.html`, `faq.html`, `longbien.html`,
  `phoco.html`, `gioithieu.html`, `caugiay.html`, `dongda.html`

Do not restore it.

## Current customer assistant

The canonical customer-facing assistant is the separate agent chatbot
integration:

- `assets/js/chatbot-embed.js` (loaded by `_includes/chatbot-embed.html`)

Legacy files `motoai_v39_*.js`, `motoai_v40_*.js`, `motoai_v41_*.js`
in the repo root are not loaded by any page and are retained only as
history. There is no auto learning and no price crawling.

## Deterministic local fallback

The legacy Render UI (search, calculator, modal openers) still ships a
deterministic `smartReply()` helper. It is NOT AI:

- no network calls, no simulated "Gemini" responses
- pricing answers are built only from the approved pricing truth in
  `assets/js/prices.js`
- anything unverified defers to: "Liên hệ Mr Tú qua Zalo/điện thoại
  0816659199 để xác nhận thông tin hiện tại."
- it must never recommend vehicle models that business truth does not
  confirm
