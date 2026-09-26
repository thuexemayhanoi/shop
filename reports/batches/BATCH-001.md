# Batch report BATCH-001

- started_at: 2026-09-26T02:10:31 | finished_at: 2026-09-26T02:10:32
- writer: external-agent | batch resolved once: BATCH-001
- processed: 3 | written: 3 | pass: 3 | published: 3
- review: 0 | repair: 0 | fail: 0 | blocked: 0
- scores: avg 97.3 | min 96 | max 100 | repair_count: 0
- source_gate: pass 0 | blocked 0
- published_commit_sha: null

| article_id | output_path | status | score | repairs | notes |
|---|---|---|---|---|---|
| DL-0001 | cam-nang/du-lich/dl-0001-kinh-nghiem-di-xe-may-den-ho-tay-tu-ha-noi.html | PUBLISHED | 96 | 0 |  |
| KN-0002 | cam-nang/kinh-nghiem/kn-0002-thue-honda-wave-di-duong-dai-nen-chuan-bi-nhung-gi.html | PUBLISHED | 100 | 0 |  |
| XM-0002 | cam-nang/xe-may/xm-0002-khi-nao-can-kiem-tra-nhot-may-tren-honda-wave.html | PUBLISHED | 96 | 0 |  |

## Publish transaction — 2026-09-26 (scheduled recovery run)

- Canonical QA (scripts/run_article_batch.py --batch BATCH-001 --qa):
  KN-0002 = 100, XM-0002 = 96, DL-0001 = 96 — all PASS (avg 97.3).
- Publish executed via the new Node fallback (scripts/js/factory.mjs
  --publish "KN-0002,XM-0002,DL-0001" --date 2026-09-26): matrix rows
  flipped PASS -> PUBLISHED with published_date=2026-09-26; hub
  ARTICLE-LIST blocks regenerated (kinhnghiem 2 cards, xemay 2 cards,
  dulich 1 card, antoan unchanged); sitemap.xml rebuilt to 35 URLs
  (29 legacy + 6 published articles); factory-progress.json refreshed.
- Cross-validated: canonical generate_category_pages.py and
  generate_sitemap.py are byte-level no-ops after the Node transaction.
- Previous corruption fixes and manual QA for these 3 articles are
  recorded in commit e4df684 (the Python --qa rewrite of this file
  replaced the earlier Resume QA section; see git history).
- Disposition of the 44 file-less WRITING rows: legitimate BATCH-001
  reservations per the documented crash-recovery rule (file-less rows
  stay claimable/resumable); unchanged, to be written by the external
  writer in later runs.
