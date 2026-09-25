# Legacy Pages Audit (Pass 2)

Baseline MAIN SHA: `18dbe5c619187930553b768413c0be94a7ad0a59`

All 30 root HTML pages audited by `scripts/audit_legacy_pages.py`. `lienhe.html` is now INCLUDED.

## Summary

| Metric | Before | After |
|---|---|---|
| h1 errors | 0 | 0 |
| heading hierarchy errors | 28 | 0 |
| missing title | 0 | 0 |
| missing meta | 0 | 0 |
| canonical errors | 0 | 0 |
| broken links | 0 | 0 |
| invalid jsonld | 0 | 0 |
| stale fact pages | 25 | 0 |
| pages needing review | 25 | 0 |

### Per-page status

| Page | Status | Words (before -> after) | Key changes |
|---|---|---|---|
| antoan.html | PASS | 729 -> 729 | calculator H3->H2 |
| badinh.html | FIXED | 899 -> 903 | title Xe Moi 100% removed; H1/keywords 50cc removed; 'giao xe 5-10 phut' -> giao xe theo lich hen; calculator  |
| banggia.html | FIXED | 817 -> 821 | calculator H3->H2; 'Mien phi thay dau' -> bao duong dinh ky |
| caugiay.html | FIXED | 810 -> 796 | title Giao Xe 15P removed; meta (Xe moi 2024, dam bao) rewritten; twitter cleaned; body cocc/15-20 phut fixed; |
| chinhsach.html | FIXED | 943 -> 940 | calculator H3->H2; '(chi 5 phut)' removed |
| cungduong.html | PASS | 601 -> 601 | calculator H3->H2 |
| dieukhoan.html | FIXED | 1039 -> 1039 | calculator H3->H2 |
| dongda.html | FIXED | 990 -> 989 | meta 'giao ... trong 10 phut' -> theo lich hen; og:title 10P removed; og desc 'giao xe sieu toc' softened; 'da |
| dulich.html | PASS | 601 -> 601 | calculator H3->H2 |
| faq.html | FIXED | 1168 -> 1167 | MIEN PHI/30-phut rescue claim softened; 'ke ca 2h sang' removed; calculator H3->H2 |
| gahn.html | FIXED | 775 -> 774 | og:title Giao Xe 5 Phut removed; og desc 'Vua xuong tau la co xe' softened; hero badge 5 Phut Co Xe -> theo li |
| gioithieu.html | FIXED | 882 -> 880 | title Giao Xe 15P removed; '15-20 phut' li -> theo lich hen; calculator H3->H2 |
| haibatrung.html | FIXED | 792 -> 794 | title/og Giao Xe 5 Phut removed; twitter cleaned; 'co xe ngay sau 5-10 phut' & '5-10 phut' body claims -> lich |
| hoankiem.html | FIXED | 1073 -> 1070 | twitter:title Giao Xe 5 Phut removed; 'uy tin nhat' -> uy tin; '5-10 phut' -> lich hen; calculator H3->H2 |
| hoidap.html | PASS | 647 -> 647 | calculator H3->H2 |
| index.html | FIXED | 2376 -> 2378 | Cam Ket H4->H3 x4; calculator H3->H2; AI comparison card 15 Phut/45-60p -> Theo hen/Khong cam ket |
| kinhnghiem.html | FIXED | 1203 -> 1203 | calculator H3->H2 (benign 'danh 5 phut kiem tra xe' kept) |
| lienhe.html | FIXED | 508 -> 684 | FULL CLEANUP: title/meta/og/twitter de-24/7 + 15 phut; keywords de-addressed; geo/ICBM address metas removed;  |
| longbien.html | FIXED | 881 -> 878 | title Xe Moi/Giao Tan Noi 5P -> theo lich hen; 'uy tin nhat' -> removed superlative; calculator H3->H2 |
| mangxahoi.html | FIXED | 974 -> 976 | voucher claim removed; calculator H3->H2 |
| ngay.html | FIXED | 667 -> 663 | og 10-phut claim removed; hero '5 phut' -> nhanh gon; '(chi mat khoang 5 phut)' -> nhanh gon; calculator H3->H |
| nhap.html | FIXED | 1507 -> 1507 | Cam Ket H4->H3 x4; calculator H3->H2; homepage canonical intentionally retained (entry page, not in sitemap) |
| phoco.html | FIXED | 972 -> 971 | 'giao xe 10 phut' & 'giao nhan xe 5-10 phut' -> theo lich hen; calculator H3->H2 |
| tayho.html | FIXED | 1026 -> 1029 | title Giao Tan Noi 5P -> theo lich hen; og 'uy tin so 1 / thu tuc 5 phut' cleaned; twitter 'Gia Tot Nhat' -> G |
| thang.html | FIXED | 922 -> 924 | meta 'mien phi thay dau' removed; h3 'Mien Phi Thay Dau & Bao Duong' -> Bao Duong Xe; body free-oil claim -> l |
| thanhxuan.html | FIXED | 933 -> 932 | meta (uy tin so 1, 5 phut, xe moi 2024) rewritten; og:title 10p removed; twitter cleaned; 'nhan xe sau 5 phut' |
| thutuc.html | FIXED | 1085 -> 1085 | meta/twitter '5 phut nhan xe' removed; hero badge -> nhanh gon; '5-10 phut' -> nhanh gon trong gio mo cua; cal |
| tuan.html | FIXED | 865 -> 871 | og 'combo gia cuc soc, mien phi' cleaned; 'thu tuc 5 phut' -> nhanh gon; '5-10 phut' -> nhanh gon; 'doi xe mie |
| uudai.html | FIXED | 724 -> 732 | 'So luong xe uu dai co han' fake scarcity -> uu dai tuy thoi diem, lien he xac nhan; calculator H3->H2 |
| xemay.html | PASS | 630 -> 630 | calculator H3->H2 |

### Intentional canonical exception

- `nhap.html` keeps its homepage canonical (legacy entry page, not in sitemap). No `noindex` added without evidence.

---

# Pass 3 — Fact-Safety Cleanup (config-aware)

Baseline MAIN SHA: `0445e584e918ace0ebd2c9e189c6dcc5cded99ab`

`config/business-facts.json` still keeps `opening_hours`, `support_hours`,
`delivery_or_pickup`, `late_return_policy` as `null` (unverified). They were
NOT promoted to trusted. All hard claims about them were neutralized on the
30 root pages, and `scripts/audit_legacy_pages.py` now builds its stale-fact
checks from the config (no more false negatives).

## Summary (config-aware detection)

| Metric | Before | After |
|---|---|---|
| pages with unverified-fact claims | 29 | 0 |
| unverified opening-hours claims | 21 pages | 0 |
| unverified delivery/pickup claims | 21 pages | 0 |
| unverified late-return fee claims | 4 pages | 0 |
| unverified support-hours claims | 2 pages | 0 |
| status widgets inferring open/closed from 8h-17h | 8 pages + assets/js app*.js | 0 (neutral: "Liên hệ để xác nhận thời gian hỗ trợ") |

## Removed claim categories

- Hard hours: `8h-17h`, `8h–17h`, `08:00 – 17:00`, `giờ mở cửa`, `Cửa hàng đang mở (8h-17h)`, `Ngoài giờ mở cửa – liên hệ Zalo`, footer `Cửa hàng: 08:00 – 17:00`.
- Hard delivery: `giao xe tận sảnh`, `giao (xe) tận nơi/nhà/cửa`, `giao xe theo lịch hẹn`, `Giao xe nhanh ...`, `Chi nhánh Long Biên`, `Có điểm giao xe`, `Miễn phí giao xe bán kính 3km`, `Đón khách tại Ga ...`.
- Late-return fees: `Trả xe trễ tính thêm phí theo giờ`, `Trả xe muộn sẽ tính phí phụ thu 20.000đ - 30.000đ/giờ`, `phí phạt quá giờ`.
- Support speed: `Phản hồi siêu tốc`, `Hỗ trợ Online 24/7`.

All replaced with neutral conditional wording (allowlisted), e.g.
"Vui lòng liên hệ trước để xác nhận thời gian và hình thức nhận xe.",
"Liên hệ để xác nhận khả năng giao/nhận xe ...",
"Nếu cần gia hạn hoặc thay đổi thời gian trả xe, vui lòng liên hệ trước để xác nhận điều kiện áp dụng."

## Status widget

The inline JS (8 root pages) and `assets/js/app.js`, `app-info.js`,
`app-rental.js` no longer infer open/closed from hard-coded 8–17 hours.
They now always show the neutral "Liên hệ để xác nhận thời gian hỗ trợ".

## Validation

- `python3 scripts/audit_legacy_pages.py` -> 30 pages, no blocking issues, stale fact pages (config-aware) = 0
- `python3 scripts/validate_content_matrix.py` -> 2000 production rows, 40 batches x 50, all PLANNED
- `python3 -m unittest discover tests` -> 127 tests PASS (116 before + 11 new config-aware fact-safety tests)
- Manual grep safety check on root HTML: 0 unsupported hits for 8h-17h / 8h–17h / 08:00 / 17:00 / giờ mở cửa / cửa hàng đang mở / ngoài giờ mở cửa / giao xe tận sảnh / trả xe trễ (fee claims) / phí theo giờ
