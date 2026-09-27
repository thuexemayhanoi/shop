# PROC-UX-PERF-A11Y — UX, Mobile, Accessibility & Performance

## Objective

Keep the site usable across breakpoints, keyboard-accessible, and fast:
header/footer/navigation, chatbot, tap targets, keyboard focus, dark/light
schemes, horizontal overflow, image ALT, image weight, fonts and resource
loading. This procedure defines what IS verified, with which tools, and —
critically — what is NOT.

## Preconditions

- Know the tooling reality of this environment: verification is
  text/byte-level (curl, grep, node syntax checks, unit tests). There is
  NO browser, NO device farm, NO Lighthouse run in CI.
- Read README §4 performance rules (non-negotiable) and §3 chatbot/nav
  architecture.

## Canonical data sources

- `tests/test_ui_integration.py` — enforces one chatbot embed, taxonomy
  footer wiring, menu single-source.
- `assets/js/chatbot-embed.js` — the canonical chatbot embed (focus trap
  lives here; verified `node --check` clean).
- `gioithieu.html` responsive header tiers (breakpoints 1281–1440px,
  1025–1280px, ≤1024px; status-widget hidden ≤1440px).

## Steps (verified commands & checks)

1. **Structural UI regression gate** (every change):

   ```bash
   python3 -m unittest discover tests   # includes test_ui_integration + test_publish_gate
   node --check assets/js/chatbot-embed.js   # syntax sanity for the chatbot JS
   ```

2. **Chatbot embed integrity on any page** (source or live):

   ```bash
   grep -c 'chatbot-embed' <page.html>          # exactly one embed pair
   grep -c 'site-footer-compact' <page.html>    # exactly one compact footer (count the full tag string)
   ```

   Keyboard/focus contract of the canonical embed (implemented in
   `chatbot-embed.js`, code-reviewed): the focus trap cycles only real
   focusable controls, Tab/Shift+Tab wrap both directions, focus escaping
   the dialog is recaptured at document level while open, the iframe is
   created lazily on first open (nothing from the chatbot origin loads at
   page load).
3. **Responsive-header checks (deployed fix, code-level verified)**:
   `gioithieu.html` contains `.header-left,.desktop-nav,.header-actions{min-width:0}`,
   `.desktop-nav{flex:0 1 auto}`, two compact header tiers and the
   status-widget hidden at ≤1440px. Verified via source inspection +
   live 200 + byte-identity; the header overflow fix is commit 81fe78c2.
4. **Image hygiene (source sweep)**:

   ```bash
   grep -rL 'alt=' --include='*.html' . | grep -v _drafts | head    # pages with img tags missing alt (review each)
   du -sh IMG_*.jpeg                                                  # repo-root images ~440 KB total; do not add unoptimized hero images
   ```
   Rules: every `<img>` needs a meaningful alt; no new large images on
   `index.html`; keep JPEGs compressed.
5. **Performance rules enforcement** (policy + tests): no background
   crawling, no new infinite animations, no heavier startup scripts on
   the homepage, previously disabled hero blur / logo spin stay disabled.
   Violations = FAIL regardless of any other score.
6. **Breakpoint review discipline**: changes to layout must state WHICH
   breakpoints were checked (representative: ~375, ~768, ~1024, ~1280,
   ~1440, >1440) and with what tool. If only code inspection was done,
   the change MUST be reported as "code-verified, visual NOT VERIFIED"
   — exactly as the gioithieu header fix is reported in
   `docs/MASTER-FIX-MATRIX.md`.

## Expected results

- Test suites green; one chatbot embed + one compact footer per page;
  no layout change reported as visually verified unless a real rendering
  tool was used.

## PASS/FAIL criteria

- PASS: tests green + structural greps correct + performance rules
  intact + honest verification labeling.
- FAIL: duplicate chatbot/footer, broken chatbot JS syntax, layout change
  shipped with a false "tested on devices" claim, any re-enabled heavy
  animation/startup script.

## Error handling

- Focus-trap or embed defect → fix `chatbot-embed.js`, `node --check`,
  re-run test suite, push; never modify the chatbot URL/contact content.
- Header overflow regression → the tiered CSS in `gioithieu.html` is the
  fix pattern; extend to other pages only with the same verification
  discipline.
- A rendering-level defect reported by a real user on a real device →
  reproduce with the available evidence (screenshot from user), fix,
  record in the fix matrix with device/browser info.

## Checkpoint

- Evidence in the report: exact test output, grep counts, commit sha,
  and an explicit line of which breakpoints/devices were or were NOT
  checked.

## Rollback

- UI fixes are forward-only (restore previous file content if a fix
  regresses — the pre-fix content is always recoverable from git history
  via a content push).

## Known limits / NOT VERIFIED (must be stated, never implied)

- NO visual/browser testing exists in this pipeline. Desktop-emulated
  checks are NOT Safari/iPhone tests; never call them that.
- Lighthouse (lab) is NOT IMPLEMENTED in CI; Core Web Vitals (field,
  real users) data source is NOT CONNECTED. Lab scores ≠ field data;
  neither exists here today — see `docs/PROC-POST-PUBLISH.md` TODOs.
- Dark/light scheme: pages are single-scheme (light); there is no theme
  switcher to test (N/A — do not invent one).
- TODO: add a CI Lighthouse (lab, headless) step for representative
  pages; TODO: connect real-device visual spot-checks when a tool exists.
