/* ============================================================
   CANONICAL CHATBOT EMBED — Mr Tú /shop/
   External assistant: https://thuexemayhanoi.github.io/aichatbot/

   Rules enforced here:
   - ONE launcher + ONE panel per page (idempotent init guard).
   - The external iframe is created ONLY on first open (lazy embed);
     nothing from the chatbot origin loads during initial page load.
   - Fallback link "Mở Hỗ trợ Agent" is always available in the panel
     footer; an iframe load error also shows a visible notice.
   - Accessibility: proper <button>, aria labels, Escape closes,
     focus moves to the close control on open and is restored on close,
     body scroll is locked while open.
   - Legacy entry points (AI_Guide.open(), MotoAI_v40_Home.open())
     are aliased to this canonical implementation so no page keeps a
     second, older chatbot system active.
   ============================================================ */
(function () {
    'use strict';

    if (window.MotoAIEmbedCanonical) { return; } // duplicate init guard
    window.MotoAIEmbedCanonical = true;

    var CHATBOT_URL = 'https://thuexemayhanoi.github.io/aichatbot/';

    var launcher = null;
    var panel = null;
    var iframe = null;
    var closeBtn = null;
    var lastFocus = null;

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (text !== undefined && text !== null) { node.textContent = text; }
        return node;
    }

    function ensureLauncher() {
        if (launcher && document.body.contains(launcher)) { return; }
        launcher = el('button', 'cb-launcher');
        launcher.type = 'button';
        launcher.id = 'chatbot-launcher';
        launcher.setAttribute('aria-label', 'Mở Hỗ trợ Agent');
        launcher.setAttribute('aria-expanded', 'false');
        launcher.setAttribute('aria-controls', 'chatbot-panel');

        var icon = el('span', 'cb-launcher-icon', '💬');
        icon.setAttribute('aria-hidden', 'true');
        launcher.appendChild(icon);
        launcher.appendChild(el('span', null, 'Hỗ trợ Agent'));
        launcher.addEventListener('click', function () { open(); });
        document.body.appendChild(launcher);
    }

    function ensurePanel() {
        if (panel && document.body.contains(panel)) { return; }
        panel = el('aside', 'cb-panel');
        panel.id = 'chatbot-panel';
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');
        panel.setAttribute('aria-label', 'Hỗ trợ Agent');

        var header = el('div', 'cb-header');
        var title = el('h3', 'cb-title', 'Hỗ trợ Agent');
        closeBtn = el('button', 'cb-close', '✕');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Đóng Hỗ trợ Agent');
        closeBtn.addEventListener('click', function () { close(); });
        header.appendChild(title);
        header.appendChild(closeBtn);

        var body = el('div', 'cb-body');
        body.id = 'chatbot-body';

        var notice = el('div', 'cb-notice',
            'Không tải được trợ lý trong trang. Bạn có thể mở trợ lý ở tab mới qua liên kết bên dưới.');
        notice.id = 'chatbot-notice';

        var fallback = el('div', 'cb-fallback');
        var link = el('a', null, 'Mở Hỗ trợ Agent');
        link.href = CHATBOT_URL;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        fallback.appendChild(link);

        panel.appendChild(header);
        panel.appendChild(body);
        panel.appendChild(notice);
        panel.appendChild(fallback);
        document.body.appendChild(panel);

        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && panel.classList.contains('cb-open')) {
                close();
            }
        });
    }

    function ensureIframe() {
        if (iframe) { return; }
        var body = document.getElementById('chatbot-body');
        if (!body) { return; }
        iframe = document.createElement('iframe');
        iframe.title = 'Hỗ trợ Agent';
        iframe.loading = 'lazy';
        iframe.referrerPolicy = 'strict-origin-when-cross-origin';
        iframe.setAttribute('allow', 'clipboard-write');
        iframe.addEventListener('error', function () {
            if (panel) { panel.classList.add('cb-error'); }
        });
        // src is assigned HERE, on first open only — never during page load.
        iframe.src = CHATBOT_URL;
        body.appendChild(iframe);
    }

    function open() {
        ensurePanel();
        ensureIframe();
        lastFocus = document.activeElement;
        panel.classList.add('cb-open');
        document.body.classList.add('cb-no-scroll');
        if (launcher) { launcher.setAttribute('aria-expanded', 'true'); }
        if (closeBtn) { closeBtn.focus(); }
    }

    function close() {
        if (!panel || !panel.classList.contains('cb-open')) { return; }
        panel.classList.remove('cb-open');
        document.body.classList.remove('cb-no-scroll');
        if (launcher) { launcher.setAttribute('aria-expanded', 'false'); }
        if (lastFocus && typeof lastFocus.focus === 'function') {
            lastFocus.focus();
        } else if (launcher) {
            launcher.focus();
        }
    }

    // Public canonical API + legacy aliases (single chatbot per page).
    window.MotoAIEmbed = { open: open, close: close, url: CHATBOT_URL };
    window.AI_Guide = { open: open };
    window.MotoAI_v40_Home = { open: open };

    function init() {
        ensureLauncher();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
