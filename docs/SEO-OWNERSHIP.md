# SEO Ownership

Protected search-intent ownership. Future informational articles must NOT
steal the primary intent of existing commercial pages. Machine-readable
version: `config/seo-ownership.json` (consumed by the cannibalization
checker).

## Protected pages

| Page | Primary intents |
|---|---|
| `index.html` | thuê xe máy Hà Nội |
| `phoco.html` | thuê xe máy Phố Cổ; thuê xe máy Phố Cổ Hà Nội |
| `hoankiem.html` | thuê xe máy Hoàn Kiếm |
| `banggia.html` | bảng giá thuê xe máy (pricing intent) |
| `ngay.html` | thuê xe máy theo ngày (daily rental intent) |
| `tuan.html` | thuê xe máy theo tuần (weekly rental intent) |
| `thang.html` | thuê xe máy theo tháng (monthly rental intent) |
| `thutuc.html` | thủ tục thuê xe máy (rental procedure intent) |
| `faq.html` | hỏi đáp thuê xe máy / FAQ intent |
| `chinhsach.html`, `dieukhoan.html` | policy / terms intent |
| `gioithieu.html` | giới thiệu dịch vụ intent |
| `lienhe.html` | liên hệ / đặt xe intent |
| `mangxahoi.html` | mạng xã hội / review intent |
| `nhap.html` | landing entry intent |
| District pages (`tayho.html`, `badinh.html`, `caugiay.html`, `dongda.html`, `thanhxuan.html`, `haibatrung.html`, `longbien.html`, `gahn.html`) | "thuê xe máy + <district>" intents |

## The six Cẩm nang hubs

`kinhnghiem.html`, `antoan.html`, `xemay.html`, `dulich.html`,
`cungduong.html`, `hoidap.html` are category hubs — informational, NOT
commercial landing pages. They must not compete with the pages above.

## Examples

BAD future article (steals phoco.html ownership):

> "Thuê xe máy Phố Cổ Hà Nội giá rẻ"

GOOD future article:

> "Đi xe máy trong Phố Cổ cần lưu ý những đường nào?"

## Enforcement

- Exact primary-keyword collision with a protected intent: critical FAIL.
- Title/H1 equal to a protected intent: critical FAIL.
- Exact duplicate primary keyword across matrix rows: critical FAIL.
- Near-similar titles: REVIEW flag (never auto-FAIL on fuzzy similarity
  alone).

Do not change the titles, H1s or canonicals of protected commercial pages.
