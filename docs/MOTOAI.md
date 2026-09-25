# MotoAI — Technical Documentation

Historical technical detail for the site chatbot, updated to match CURRENT
production behavior. The old README sections describing autolearn/price
crawling as active behavior are obsolete; this file supersedes them.

## Current production state

- Active chatbot: `motoai_v40_bm25plus_final.js` (MotoAI v40, BM25+ local
  search). Loaded by `lienhe.html` and other info pages; lazy-loaded on
  `index.html` only after the user taps the AI button.
- Legacy files `motoai_v39_*.js`, `motoai_v40_bm25plus_search.js`,
  `motoai_v41_*.js` in the repo root are NOT loaded by any page. Do not load
  them; do not restore v39.
- Production config on every page (defined in
  `assets/js/motoai-config.js`, loaded before v40):

```
window.MotoAI_CONFIG = {
  autolearn: false,
  debug: false,
  smart: { autoPriceLearn: false }
}
```

- v40's internal defaults were also changed to these production-safe values
  as a defensive fallback.
- Manual learning APIs (`learnNow()` etc.) remain present but unused; they
  must not be triggered automatically anywhere.

## Price behavior

- Approved price source: `assets/js/prices.js`
  (`window.MotoTusPrices.MODELS`): Wave, Sirius, Click, Mio, Vision,
  Air Blade, E-bike.
- v40's price lookup uses `MotoTusPrices` when available. It does not crawl
  the hostname and does not relearn/overwrite prices.
- Unknown/unapproved models (50cc, Lead, Janus, Attila, NVX, SH, côn/PKL,
  …) answer "Liên hệ để xác nhận giá hiện tại".
- Deposit answers use the standardized wording from
  `config/business-facts.json`. Stale wordings ("2–3tr xe số, 3–5tr xe ga",
  "giảm cọc khi đủ giấy tờ", "500k–1 triệu") have been removed and must not
  return.

## Homepage integration (index.html)

- v40 is NOT a startup script. On first AI interaction, the homepage
  dynamically injects `motoai_v40_bm25plus_final.js`, waits for load, then
  calls `window.MotoAI_v40.open()`. A loading-promise state guard prevents
  duplicate script insertion; subsequent taps reuse the loaded instance.
- The legacy homepage AI Guide modal (`AI_Guide`, `setupAI()`, old inline
  chatbot) was removed. All AI entry buttons open the same MotoAI v40
  instance — exactly one primary chatbot experience.
- The homepage Bike Matchmaker ("Tìm Xe Chân Ái") is a separate tool, kept
  intentionally: all three inputs (experience, destination, height) affect
  the recommendation, only established models (Wave/Sirius, Vision,
  Air Blade) or "Liên hệ để được tư vấn" are suggested, no invented prices,
  no fake confidence scores.

## Child pages

Pages that show the chatbot load, in order:

```html
<script src=".../assets/js/motoai-config.js"></script>
<script src="motoai_v40_bm25plus_final.js" defer></script>
```

## API surface

- `window.MotoAI_v40.open()` — open the chat UI
- `window.MotoAI_v40.send(text)` — programmatic message
- `window.MotoAI_v40.clear()` — clear conversation

## Performance invariants

- No background crawling, no sitemap fetching, no auto learning at startup.
- No continuous effects introduced by the chatbot; the homepage stays
  startup-light (v40 loads only on user intent).
