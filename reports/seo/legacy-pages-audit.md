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

