#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI integration tests: canonical footer taxonomy, menu source, and the
single lazy MotoAI chatbot embed.

Covers the shop UI integration contract:
- one canonical footer taxonomy source (_data/content-taxonomy.json ==
  data/content-taxonomy.json, rendered by _includes/footer.html)
- one canonical menu source (assets/js/nav-data.js) consumed by every
  renderer, so app.js / app-info.js / app-rental.js cannot drift
- ONE chatbot implementation per rendered page: canonical lazy embed
  present exactly once, old chatbots (MotoAI v40 bubble scripts, AI Guide
  modal) absent, fallback link present, iframe never preloaded
- factory pages (child hubs, topic index, published articles) inherit the
  embed; the factory template and the writer rules require it
"""
import glob
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
import sys
sys.path.insert(0, SCRIPTS)

import article_lib as lib  # noqa: E402

CHATBOT_URL = "https://thuexemayhanoi.github.io/aichatbot/"
EMBED_JS = "assets/js/chatbot-embed.js"
EMBED_CSS = "assets/css/chatbot-embed.css"

def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()

def root_pages():
    return sorted(p for p in glob.glob(os.path.join(ROOT, "*.html")))

def all_public_pages():
    pages = [p for p in root_pages()]
    pages += glob.glob(os.path.join(ROOT, "cam-nang", "**", "*.html"),
                       recursive=True)
    return sorted(pages)

class TaxonomySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax = json.loads(read("data/content-taxonomy.json"))
        cls.parents = cls.tax["parents"]

    def test_data_copy_is_byte_identical(self):
        self.assertEqual(read("_data/content_taxonomy.json"),
                         read("data/content-taxonomy.json"),
                         "_data/content_taxonomy.json must stay a "
                         "byte-identical copy of data/content-taxonomy.json")

    def test_six_parents(self):
        self.assertEqual(len(self.parents), 6)

    def test_56_children_each_with_exactly_one_parent(self):
        seen = {}
        for parent in self.parents:
            for child in parent["children"]:
                self.assertNotIn(child["child_id"], seen,
                                 "child in more than one parent")
                seen[child["child_id"]] = parent["parent_id"]
        self.assertEqual(len(seen), 56)

    def test_parent_hub_files_exist(self):
        for parent in self.parents:
            hub = parent["parent_hub"].replace("/shop/", "")
            self.assertTrue(os.path.isfile(os.path.join(ROOT, hub)),
                            hub)

    def test_child_hub_files_exist(self):
        for parent in self.parents:
            for child in parent["children"]:
                hub = child["child_hub_url"].replace("/shop/", "")
                self.assertTrue(os.path.isfile(os.path.join(ROOT, hub)), hub)

    def test_topic_index_exists(self):
        self.assertTrue(os.path.isfile(
            os.path.join(ROOT, "cam-nang", "chu-de", "index.html")))

class FooterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.footer = read("_includes/footer.html")
        cls.tax = json.loads(read("data/content-taxonomy.json"))

    def test_footer_compact_cam_nang_section(self):
        # Compact contract: SIX parent category links + the topic-index
        # link only. The 56 child topics must NOT be inlined in the footer.
        self.assertIn("footer-taxonomy", self.footer)
        self.assertIn("Xem tất cả chủ đề", self.footer)
        self.assertIn("/shop/cam-nang/chu-de/", self.footer)
        for hub in ("kinhnghiem.html", "antoan.html", "xemay.html",
                    "dulich.html", "cungduong.html", "hoidap.html"):
            self.assertIn("/shop/%s" % hub, self.footer)

    def test_footer_does_not_inline_child_taxonomy(self):
        # The full taxonomy stays on category pages / topic index, never
        # as a wall of child links in the footer.
        self.assertNotIn("<details", self.footer)
        self.assertNotIn("child_hub_url", self.footer)

    def test_every_root_page_uses_canonical_footer_include(self):
        for page in root_pages():
            html = open(page, encoding="utf-8").read()
            self.assertIn("{% include footer.html %}", html,
                          "%s must use the canonical footer include" % page)

    def test_no_hard_coded_24_7_claim(self):
        for page in root_pages() + [os.path.join(ROOT, "_includes",
                                                 "footer.html")]:
            html = open(page, encoding="utf-8").read()
            self.assertNotIn("24/7", html,
                             "%s must not claim 24/7 support" % page)

class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav = read("assets/js/nav-data.js")

    def test_menu_contains_all_parent_hubs(self):
        for hub in ("kinhnghiem.html", "antoan.html", "xemay.html",
                    "dulich.html", "cungduong.html", "hoidap.html"):
            self.assertIn(hub, self.nav)

    def test_menu_has_topic_index(self):
        self.assertIn("Tất cả chủ đề", self.nav)
        self.assertIn("cam-nang/chu-de/", self.nav)

    def test_all_renderers_consume_site_nav(self):
        for js in ("assets/js/app.js", "assets/js/app-info.js",
                   "assets/js/app-rental.js"):
            src = read(js)
            self.assertIn("window.SITE_NAV", src,
                          "%s must take its menu from window.SITE_NAV" % js)

    def test_no_renderer_duplicates_footer_taxonomy(self):
        for js in ("assets/js/app.js", "assets/js/app-info.js",
                   "assets/js/app-rental.js"):
            src = read(js)
            self.assertNotIn("createCol('Cẩm nang'", src,
                              "%s must not render a second taxonomy footer "
                              "column" % js)

class ChatbotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.embed_js = read(EMBED_JS)
        cls.include = read("_includes/chatbot-embed.html")

    def test_embed_assets_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, EMBED_JS)))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, EMBED_CSS)))

    def test_include_is_canonical_insertion(self):
        self.assertIn(EMBED_JS, self.include)
        self.assertIn(EMBED_CSS, self.include)

    def test_every_root_page_has_exactly_one_embed(self):
        for page in root_pages():
            html = open(page, encoding="utf-8").read()
            self.assertIn("{% include chatbot-embed.html %}", html, page)
            self.assertEqual(html.count("chatbot-embed.html"), 1, page)
            # canonical position: immediately before </body>
            self.assertGreater(html.index("{% include chatbot-embed.html %}"),
                               html.rindex("</footer>") if "</footer>" in html
                               else 0, page)

    def test_no_old_chatbot_scripts_on_any_page(self):
        for page in all_public_pages():
            html = open(page, encoding="utf-8").read()
            self.assertNotIn("motoai_v40_bm25plus_final.js", html, page)
            self.assertNotIn("motoai-config.js", html, page)
            self.assertNotIn("motoai_v39", html, page)
            self.assertNotIn("motoai_v41", html, page)

    def test_old_ai_guide_modal_removed(self):
        self.assertNotIn('id="ai-modal"', read("_includes/ai-modals.html"))
        # matchmaker widget stays
        self.assertIn('id="mm-modal"', read("_includes/ai-modals.html"))

    def test_embed_js_lazy_and_accessible(self):
        src = self.embed_js
        # lazy: iframe src is assigned only inside ensureIframe (first open)
        self.assertIn("if (iframe) { return; }", src)
        self.assertIn("iframe.src = CHATBOT_URL;", src)
        self.assertIn("iframe.loading = 'lazy'", src)
        # guard against double init
        self.assertIn("window.MotoAIEmbedCanonical", src)
        # accessibility
        self.assertIn("Escape", src)
        self.assertIn("aria-label", src)
        self.assertIn("aria-modal", src)
        # fallback link
        self.assertIn("Mở Hỗ trợ Agent", src)
        self.assertIn("link.rel = 'noopener noreferrer'", src)
        # legacy entry points aliased to the canonical embed
        self.assertIn("window.AI_Guide = { open: open };", src)
        self.assertIn("window.MotoAI_v40_Home = { open: open };", src)

    def test_fallback_target_is_external_assistant(self):
        self.assertIn(CHATBOT_URL, self.embed_js)
        self.assertIn(CHATBOT_URL, read("_includes/chatbot-embed.html"))

    def test_factory_generated_pages_inherit_embed(self):
        pages = (glob.glob(os.path.join(ROOT, "cam-nang", "chu-de", "*.html"))
                 + [os.path.join(ROOT, "cam-nang", "chu-de", "index.html")])
        pages = sorted(set(pages))
        self.assertEqual(len(pages), 57)
        for page in pages:
            html = open(page, encoding="utf-8").read()
            self.assertEqual(html.count(EMBED_JS), 1, page)
            self.assertEqual(html.count(EMBED_CSS), 1, page)

    def test_published_articles_have_exactly_one_embed(self):
        matrix = lib.load_matrix()
        published = [r for r in matrix
                     if not lib.is_sample_row(r)
                     and (r.get("status") or "").strip() == "PUBLISHED"
                     and r.get("output_path")]
        self.assertTrue(published)
        for row in published:
            path = os.path.join(ROOT, row["output_path"].lstrip("/"))
            self.assertTrue(os.path.isfile(path), row["output_path"])
            html = open(path, encoding="utf-8").read()
            self.assertEqual(html.count(EMBED_JS), 1,
                             "%s must embed the canonical chatbot once"
                             % row["output_path"])

    def test_factory_template_requires_embed(self):
        self.assertIn("CHATBOT_SNIPPET", read("scripts/js/factory.mjs"))

    def test_writer_rules_require_embed(self):
        rules = read("docs/ARTICLE-RULES.md")
        self.assertIn(EMBED_JS, rules)
        manifest_src = read("scripts/run_article_batch.py")
        self.assertIn("chatbot_embed_snippet", manifest_src)

class FactorySafetyTests(unittest.TestCase):
    def test_matrix_untouched_shape(self):
        matrix = lib.load_matrix()
        prod = [r for r in matrix if not lib.is_sample_row(r)]
        self.assertEqual(len(prod), 2000)

    def test_sitemap_contains_hubs_and_topic_index(self):
        sm = read("sitemap.xml")
        self.assertIn("/cam-nang/chu-de/", sm)
        for parent in ("kinhnghiem", "antoan", "xemay", "dulich",
                       "cungduong", "hoidap"):
            self.assertIn("/%s.html" % parent, sm)

if __name__ == "__main__":
    unittest.main()
