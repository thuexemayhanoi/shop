# Batch report BATCH-001

- started_at: 2026-09-25T20:34:24 | finished_at: 2026-09-25T20:34:25
- writer: external-agent | batch resolved once: BATCH-001
- processed: 3 | written: 3 | pass: 3 | published: 0
- review: 0 | repair: 0 | fail: 0 | blocked: 0
- scores: avg 98.7 | min 96 | max 100 | repair_count: 0
- source_gate: pass 1 | blocked 0
- published_commit_sha: None

| article_id | output_path | status | score | repairs | notes |
|---|---|---|---|---|---|
| KN-0001 | cam-nang/kinh-nghiem/kn-0001-kinh-nghiem-thue-honda-wave-o-ha-noi-cho-nguoi-moi.html | PASS | 100 | 0 |  |
| AT-0001 | cam-nang/an-toan/at-0001-nong-do-con-khi-lai-xe-may-muc-xu-phat-hien-hanh.html | PASS | 100 | 0 |  |
| XM-0001 | cam-nang/xe-may/xm-0001-cach-kiem-tra-bugi-tren-honda-wave.html | PASS | 96 | 0 |  |

## Resume QA — 2026-09-26 (scheduled recovery run)

Manual QA (external operator, byte-exact file verification via git blob SHAs)
of the 3 WRITING articles with committed files (KN-0002, XM-0002, DL-0001):

- word counts (main editorial content, tag-stripped): KN-0002 = 1952,
  XM-0002 = 1740, DL-0001 = 1868 — all within the 1,600–2,000 standard
- 1 H1, self canonical, unique title + meta description, lang=vi, author
  Mr Tú, datePublished 2026-09-26, Article + BreadcrumbList JSON-LD — OK
- contextual internal links: KN-0002 = 3 (parent hub kinhnghiem.html ✓),
  XM-0002 = 4 (parent hub xemay.html ✓), DL-0001 = 4 (parent hub
  dulich.html ✓); exactly the ledger internal_link_targets + the single
  approved commercial_link_target; descriptive diverse anchors; all
  targets resolve to existing /shop/ pages — OK
- duplicate sentences: 0 in all three; no placeholder/template text;
  no unapproved prices (KN-0002 deposit range 2.000.000–5.000.000đ is
  approved business fact); requires_sources=false for all three rows
- DEFECTS FOUND AND FIXED in this run (foreign-script corruption):
  - at-0001 (PUBLISHED): "một người完全不 uống" → "một người hoàn toàn
    không uống"; "xe nhưng轮流 di chuyển" → "xe nhưng luân phiên di
    chuyển" (2 fixes)
  - dl-0001 (WRITING draft): "gần như phẳng абсолютно," → "gần như
    phẳng tuyệt đối," (1 fix)
- Matrix rows intentionally remain WRITING: the 990KB ledger cannot be
  rewritten byte-exactly in this runtime (no Python tooling; fetch size
  caps). Before any publish of these 3 rows, the scripted pipeline must
  still run: run_article_batch.py --qa → --publish → --mark-published,
  then regenerate root hubs + sitemap. Do not add them to sitemap.xml
  or hub ARTICLE-LIST blocks before the rows are PUBLISHED.
