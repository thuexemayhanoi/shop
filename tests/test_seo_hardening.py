"""Regression tests for the SEO hardening tooling.

All tests run against temporary fixture trees. The production matrix,
batch state, drafts and article prose are NEVER touched.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "seo"))

import seo_audit
import seo_fix_matrix
import seo_regression
import safe_fix

BASE = seo_audit.BASE_URL  # https://thuexemayhanoi.github.io/shop/

def page(root, rel, canon=None, title="T", desc="D", body_extra="", schema_extra=""):
    canon = canon or (BASE if rel == "index.html" else BASE + rel)
    html = f"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canon}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":"{title}","mainEntityOfPage":"{canon}"}}
</script>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Home","item":"{BASE}"}}]}}
</script>
</head><body>
<h1>{title}</h1>
<p id="target">x</p>
</body></html>
"""
    if body_extra:
        html = html.replace("</body></html>", body_extra + "</body></html>")
    if schema_extra:
        html = html.replace("</head>", schema_extra + "</head>")
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def sitemap(root, locs):
    urls = "".join(f"<url><loc>{u}</loc><lastmod>2026-09-27</lastmod></url>" for u in locs)
    with open(os.path.join(root, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='utf-8'?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + urls + "</urlset>")


def config(root, excludes=True):
    with open(os.path.join(root, "_config.yml"), "w", encoding="utf-8") as f:
        f.write("exclude:\n" + "".join(f"  - {p}\n" for p in (["AGENTS.md", "README.md", "ARCHITECTURE.md", "config/", "data/", "docs/", "reports/", "scripts/", "tests/"] if excludes else [])))


class FixtureBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="seo_fixture_")
        self.addCleanup(shutil.rmtree, self.root)
        config(self.root, excludes=False)
        for d in ("tests", "docs", "reports", "scripts", "config", "data"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        page(self.root, "index.html")

    def audit(self):
        return seo_audit.run_audit(self.root)

    def rules(self, report):
        return {f["rule"]: f for f in report["findings"]}


class TestSeoAudit(FixtureBase):
    def test_valid_page_passes(self):
        page(self.root, "a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertEqual(r["summary"]["P0"], 0)
        self.assertEqual(r["summary"]["P1"], 0)

    def test_bad_canonical_detected(self):
        page(self.root, "a.html", canon=BASE + "wrong-route.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("canonical.wrong", self.rules(r))
        self.assertEqual(r["summary"]["P1"] >= 1, True)

    def test_shop_shop_detected(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        f = self.rules(r)["canonical.shop-shop"]
        self.assertTrue(f["safe_to_auto_fix"])
        self.assertEqual(f["severity"], "P0")

    def test_dotslash_canonical_detected(self):
        page(self.root, "a.html", canon=BASE + "../a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("canonical.parent-dotslash", self.rules(r))

    def test_broken_internal_route_detected(self):
        page(self.root, "a.html", body_extra='<a href="/shop/ghost.html">g</a>')
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("links.broken-internal", self.rules(r))

    def test_broken_anchor_detected(self):
        page(self.root, "a.html", body_extra='<a href="/shop/other.html#nope">x</a>')
        page(self.root, "other.html")
        sitemap(self.root, [BASE, BASE + "a.html", BASE + "other.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("links.broken-fragment", self.rules(r))

    def test_stale_schema_url_detected(self):
        page(self.root, "a.html", schema_extra='<script type="application/ld+json">'
             '{"@context":"https://schema.org","@type":"Article","mainEntityOfPage":"' + BASE + 'stale-slug.html"}</script>')
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("schema.stale-url", self.rules(r))

    def test_sitemap_missing_published_url_detected(self):
        page(self.root, "a.html")
        sitemap(self.root, [BASE])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("sitemap.missing-pages", self.rules(r))

    def test_noindex_detected(self):
        html_head = '<meta name="robots" content="noindex">'
        page(self.root, "a.html", schema_extra=html_head)
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("robots.noindex", self.rules(r))
        self.assertEqual(self.rules(r)["robots.noindex"]["severity"], "P0")

    def test_operational_file_exposure_detected(self):
        page(self.root, "a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=False)  # no excludes at all
        r = self.audit()
        self.assertIn("deploy.operational-unexcluded", self.rules(r))

    def test_dedup_by_root_cause(self):
        # 3 pages all with the same wrong-canonical root cause -> ONE finding
        for i in range(3):
            page(self.root, f"a{i}.html", canon=BASE + "shared-bug.html")
        sitemap(self.root, [BASE] + [BASE + f"a{i}.html" for i in range(3)])
        config(self.root, excludes=True)
        r = self.audit()
        f = self.rules(r)["canonical.wrong"]
        self.assertEqual(f["affected_count"], 3)
        self.assertEqual(sum(1 for x in r["findings"] if x["rule"] == "canonical.wrong"), 1)


class TestFixMatrix(FixtureBase):
    def matrix(self):
        report = self.audit()
        return report, seo_fix_matrix.build_matrix(report)

    def test_duplicate_root_cause_collapses(self):
        for i in range(3):
            page(self.root, f"a{i}.html", canon=BASE + "shared.html")
        sitemap(self.root, [BASE])
        config(self.root, excludes=True)
        _, rows = self.matrix()
        wrong = [r for r in rows if r["rule"] == "canonical.wrong"]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]["affected_count"], 3)

    def test_severity_deterministic(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        _, rows = self.matrix()
        by_rule = {r["rule"]: r["severity"] for r in rows}
        self.assertEqual(by_rule.get("canonical.shop-shop"), "P0")
        self.assertTrue(all(r["severity"] in ("P0", "P1", "P2", "P3") for r in rows))

    def test_affected_urls_aggregated(self):
        for i in range(5):
            page(self.root, f"b{i}.html", title="", desc="")
        sitemap(self.root, [BASE])
        config(self.root, excludes=True)
        _, rows = self.matrix()
        tm = [r for r in rows if r["rule"] == "title.missing"]
        self.assertEqual(len(tm), 1)
        self.assertEqual(tm[0]["affected_count"], 5)

    def test_execution_status_review_by_default(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        _, rows = self.matrix()
        self.assertTrue(all(r["execution_status"] == "REVIEW" for r in rows))


class TestRegressionGuard(FixtureBase):
    def guard_files(self, audit_report):
        os.makedirs(os.path.join(self.root, "reports", "seo"), exist_ok=True)
        with open(os.path.join(self.root, "reports", "seo", "audit.json"), "w") as f:
            json.dump(audit_report, f)

    def make_report(self, broken=1):
        return {"summary": {"P0": 0, "P1": 0, "P2": broken, "P3": 0},
                "scores": {}, "metrics": {"broken_internal_link_count": broken,
                                          "published_pages": 10,
                                          "sitemap_url_count": 10}}

    def test_worse_state_fails(self):
        good, bad = self.make_report(1), self.make_report(5)
        self.guard_files(good)
        bl = os.path.join(self.root, "reports", "seo", "baseline.json")
        with open(bl, "w") as f:
            json.dump({"metrics": good["metrics"], "scores": {}}, f)
        self.guard_files(bad)
        rc = seo_regression.main(["--root", self.root])
        self.assertEqual(rc, 1)

    def test_equal_state_passes(self):
        rep = self.make_report(1)
        self.guard_files(rep)
        bl = os.path.join(self.root, "reports", "seo", "baseline.json")
        with open(bl, "w") as f:
            json.dump({"metrics": rep["metrics"], "scores": {}}, f)
        self.assertEqual(seo_regression.main(["--root", self.root]), 0)

    def test_better_state_passes(self):
        good, better = self.make_report(5), self.make_report(1)
        self.guard_files(better)
        bl = os.path.join(self.root, "reports", "seo", "baseline.json")
        with open(bl, "w") as f:
            json.dump({"metrics": good["metrics"], "scores": {}}, f)
        self.assertEqual(seo_regression.main(["--root", self.root]), 0)

    def test_p0_cannot_be_hidden_by_baselining(self):
        rep = self.make_report(1)
        rep["summary"]["P0"] = 2
        self.guard_files(rep)
        rc = seo_regression.main(["--root", self.root, "--update-baseline"])
        self.assertEqual(rc, 3)
        bl = os.path.join(self.root, "reports", "seo", "baseline.json")
        self.assertFalse(os.path.exists(bl))


class TestSafeFix(FixtureBase):
    def test_deterministic_case_repaired(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        before = open(os.path.join(self.root, "a.html")).read()
        changed = safe_fix.fix_canonical_shopshop(self.root, seo_audit.site_pages(self.root), apply=False)
        self.assertEqual(changed, ["a.html"])
        # after apply the canonical equals the live route
        safe_fix.fix_canonical_shopshop(self.root, seo_audit.site_pages(self.root), apply=True)
        after = open(os.path.join(self.root, "a.html")).read()
        self.assertIn(f'href="{BASE}a.html"', after)
        self.assertNotIn('rel="canonical" href="' + BASE + "shop/", after)
        # only the canonical line differs
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))

    def test_ambiguous_case_not_repaired(self):
        # double duplication is not unambiguous -> refused
        page(self.root, "a.html", canon=BASE + "shop/shop/a.html")
        changed = safe_fix.fix_canonical_shopshop(self.root, seo_audit.site_pages(self.root), apply=False)
        self.assertEqual(changed, [])

    def test_factory_state_not_touched(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        matrix_path = os.path.join(self.root, "data", "content-matrix.csv")
        with open(matrix_path, "w") as f:
            f.write("article_id,status\nX,PUBLISHED\n")
        with open(os.path.join(self.root, "sitemap.xml"), "w") as f:
            f.write("<?xml version='1.0'?><urlset></urlset>")
        safe_fix.fix_canonical_shopshop(self.root, seo_audit.site_pages(self.root), apply=True)
        safe_fix.fix_sitemap_duplicates(self.root, apply=True)
        with open(matrix_path) as f:
            self.assertEqual(f.read(), "article_id,status\nX,PUBLISHED\n")

    def test_guard_refuses_factory_paths(self):
        p = os.path.join(self.root, "data", "batches", "writer-checkpoint.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("{}")
        with self.assertRaises(RuntimeError):
            safe_fix.guard_paths(self.root, [p])

    def test_fix_type_allowlist_enforced(self):
        rc = safe_fix.main(["--root", self.root, "--fixes", "rewrite_prose"])
        self.assertEqual(rc, 2)

    def test_prose_not_touched(self):
        page(self.root, "a.html", canon=BASE + "shop/a.html")
        before = open(os.path.join(self.root, "a.html")).read()
        safe_fix.fix_sitemap_duplicates(self.root, apply=True)
        self.assertEqual(open(os.path.join(self.root, "a.html")).read(), before)

    def test_relative_canonical_absolutized(self):
        html = None
        rel = "cam-nang/kinh-nghiem/page-2.html"
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f'<!DOCTYPE html><html><head><title>T</title>'
                    f'<link rel="canonical" href="/shop/{rel}">'
                    f'</head><body><h1>T</h1></body></html>')
        changed = safe_fix.fix_canonical_relative(self.root, seo_audit.site_pages(self.root), apply=False)
        self.assertEqual(changed, [rel])
        safe_fix.fix_canonical_relative(self.root, seo_audit.site_pages(self.root), apply=True)
        with open(path) as f:
            html = f.read()
        self.assertIn(f'href="{BASE}{rel}"', html)

    def test_relative_canonical_ambiguous_not_repaired(self):
        rel = "a.html"
        path = os.path.join(self.root, rel)
        with open(path, "w") as f:
            f.write('<!DOCTYPE html><html><head><title>T</title>'
                    '<link rel="canonical" href="/shop/other.html">'
                    '</head><body><h1>T</h1></body></html>')
        changed = safe_fix.fix_canonical_relative(self.root, seo_audit.site_pages(self.root), apply=False)
        self.assertEqual(changed, [])

    def test_business_facts_untouched(self):
        # safe_fix exposes no mechanism at all that could edit prices/hours
        allowed = safe_fix.ALLOWED_FIXES
        self.assertEqual(allowed, {"canonical_shopshop", "canonical_relative", "sitemap_duplicates", "config_excludes"})


class TestSchemaGuard(FixtureBase):
    def test_invalid_jsonld_detected(self):
        page(self.root, "a.html", schema_extra='<script type="application/ld+json">{broken</script>')
        sitemap(self.root, [BASE, BASE + "a.html"])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("schema.jsonld-invalid", self.rules(r))

    def test_article_without_schema_detected(self):
        # a real article-shaped route missing Article schema
        rel = "cam-nang/kinh-nghiem/kn-0001-test.html"
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"""<!DOCTYPE html><html lang="vi"><head>
<meta charset="utf-8"><title>T</title>
<meta name="description" content="D">
<link rel="canonical" href="{BASE + rel}">
</head><body><h1>T</h1></body></html>""")
        sitemap(self.root, [BASE, BASE + rel])
        config(self.root, excludes=True)
        r = self.audit()
        self.assertIn("schema.article-missing", self.rules(r))


if __name__ == "__main__":
    unittest.main()
