# Factory run checkpoint — BATCH-004 continuation (scheduled content factory run)

- Vietnam timestamp: 2026-09-27 01:31 (UTC+7)
- Run type: continuation of scheduled run on thuexemayhanoi/shop main
- Start SHA (this continuation): 895a4ac41552c58bc537c47fd4b5b228d0d74852
- Current HEAD before this checkpoint: 43f3275f8bfb025790c8d53eb3085b03819602e2
- Target: up to 50 published articles (target, not quota)

## Published this continuation segment
- DL-0028 (95, repaired once: price-claim wording), CD-0028 (97, repaired once)
- CD-0029 (95), DL-0029 (95)
- CD-0030 (97), DL-0030 (95)
- Earlier in run (prior segments): HD-0026, KN-0027, XM-0027, HD-0027 (FAIL->requeue->repair->PASS 99), CD-0027 (95), HD-0028 (99), AT-0028 (99), KN-0028 (99), XM-0028 (96), DL-0027 (99)
- Run total published: ~16

## Learning recorded for future runs
- QA price gate bug workaround: never place any model name within 60 characters before a digit price; regex splits numbers ("150.000" -> "50.000"/"0"). Use model-free pricing sentences: "khoảng 150.000đ đến 200.000đ mỗi ngày tùy dòng xe".
- FAIL rows are terminal: repair flow = push fixed article + op requeue, wait for operator commit, then op qa.
- Requeue budget: per-row max repair attempts (MAX_REPAIR_ATTEMPTS).

## State snapshot
- Totals: 156 PUBLISHED / 44 WRITING / 1800 PLANNED (of 2000 total)
- Active batch: BATCH-004 (completed_batches: 3)
- Sitemap URL count: 200
- Transaction state: data/batches/txn absent — no pending transaction
- Test status: publish op runs full Python + Node suites; all publishes this segment completed (operator commits 895a4ac4, 4caaa944, 4f40d387, 43f3275f)
- BLOCKED/REVIEW: none
- Unfinished: remaining BATCH-004 WRITING rows (next unclaimed slice: CD-0031, CD-0032, CD-0033, AT-0034, DL-0031 onward)

## Next resume point
1. Fetch reports/batches/BATCH-004/rows/<ID>.json manifests for the next two unwritten rows.
2. Compose per canonical rules; validate corruption/Latin-leak/word-count/price-context gates BEFORE push.
3. Push article files + operator-command.json qa op in ONE commit; poll for factory-operator: qa commit; publish PASS rows in small slices.
