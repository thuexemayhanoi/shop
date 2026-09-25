/* MotoAI production config — loaded BEFORE motoai_v40_bm25plus_final.js on every page.
   Disables background autolearn, debug and auto price learning site-wide.
   Safe deep merge: never overwrites nested keys from an existing page-specific config. */
(function () {
    'use strict';
    var cfg = window.MotoAI_CONFIG || {};
    cfg.smart = cfg.smart || {};
    cfg.autolearn = false;
    cfg.debug = false;
    cfg.smart.autoPriceLearn = false;
    window.MotoAI_CONFIG = cfg;
})();
