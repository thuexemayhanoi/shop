# Run report - shop content factory

- run_time (Vietnam): 2026-09-26 ~16:30 - 2026-09-27 00:15 (UTC+7)
- run segment: continuation of scheduled factory run (resumed after context compaction)
- start SHA of segment: 9e48249f (prepare-next for BATCH-004)
- end SHA of segment: e3630a3 (factory-operator: consistency)
- target: 50 articles per run (target, not quota)

## Completed this segment
- published: 6 articles (all first-time PASS, no repairs needed)
  - AT-0026 loi-dung-do-xe-may-sai-quy-dinh-o-do-thi (PASS 99, source gate pass, chinhphu.vn sources verified)
  - KN-0026 kinh-nghiem-de-xe-va-giu-thang-bang-voi-yamaha-sirius (PASS 99)
  - AT-0027 xe-may-khong-dang-ky-bi-xu-ly-the-nao (PASS 99; facts verified vs Nghị định 168/2024 via chinhphu.vn reporting: 4-6 million VND for no/invalid plates, possible impound)
  - CD-0026 chuyen-mai-chau-hai-ngay (PASS 95)
  - DL-0026 sang-som-hay-chieu-muon-den-bao-tang-dan-toc-hoc-viet-nam (PASS 99)
  - XM-0026 khi-nao-can-kiem-tra-giam-xoc-tren-yamaha-sirius (PASS 96)
- repaired: 0 | source-verified: AT-0026 (2 approved chinhphu.vn URLs), AT-0027 (web verification pre-writing)
- BLOCKED/REVIEW: 0

## State at checkpoint (verified via factory-progress.json at 38ac1fc)
- totals: planned 1800 | writing 44 | published 156 | fail 0 | blocked 0
- active batch: BATCH-004 (50 rows, 6 PUBLISHED, 44 WRITING)
- completed_batches: 3
- published_commit_sha baseline: 7c20f48
- transaction state: no pending txn marker; no concurrency conflicts
- tests/validators: canonical QA passed for all 6 articles (scores 95-99); publish + consistency ops by factory-operator bot completed successfully

## Next resume point
1. Fetch fresh main, read data/content-matrix.csv, reports/batches/factory-progress.json, reports/batches/BATCH-004.md.
2. Draft next BATCH-004 rows, suggested order: HD-0026 (requires_sources=true, verify phạt nguội rules from primary sources first), AT-0028..0034, CD-0027..0033, DL-0027..0033, KN-0027..0034, XM-0027..0033.
3. Known QA rules: link only pages in eligible_internal_link_targets + commercial_link_target, each target exactly once; 1600-2000 words measured on main content; run corruption scan (CJK/Cyrillic/stray foreign words) before pushing.
4. Safe slice size: 2 articles per push + qa + publish cycle.
