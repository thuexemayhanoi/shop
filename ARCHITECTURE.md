# Kiến trúc sau refactor (Architecture)

Refactor kiến trúc tháng 9/2026: tách CSS/JS/markup dùng chung khỏi các file HTML
monolithic. KHÔNG thay đổi nội dung, thiết kế, SEO hay chức năng.

## Cấu trúc

```
_includes/            (Jekyll includes — chỉ dùng nội bộ, không xuất ra site)
  header.html         — header + nav shell (14 trang dùng)
  mobile-menu.html    — overlay menu mobile (23 trang)
  footer.html         — footer (20 trang)
  ai-modals.html      — 2 modal AI Guide / Matchmaker (16 trang)
  contact-fab.html    — nút nổi liên hệ + backtop (18 trang)

assets/css/
  base.css            — design system, biến, reset, header/hero (trang khu vực)
  main.css            — layout component giữa trang (trang khu vực)
  responsive.css      — media queries cuối (trang khu vực)
  shared.css          — đoạn CSS dùng chung cho trang thông tin/index
  pricing.css         — CSS đầy đủ cho nhóm trang bảng giá (6 trang)

assets/js/
  fallback.js         — guard AI_Guide/AI_Matchmaker chống race condition
  app.js              — JS chính (theme, menu, search, calculator, chatbot)
  app-rental.js       — biến thể JS cho trang thuê ngày/tuần/tháng
  app-info.js          — biến thể JS cho trang điều khoản/liên hệ
  app-info-fallback.js — guard đi kèm app-info.js
```

## Nguyên tắc bảo toàn (preservation rules)

- Mỗi trang giữ nguyên tên file, URL, meta SEO, canonical, JSON-LD, nội dung.
- CSS được tách theo "zone" giữ nguyên thứ tự cascade: các file outside
  (`base.css` → `main.css` → `responsive.css`) và `<style>` nội tuyến trang
  được chèn đúng vị trí để kết quả render giống hệt bản gốc.
- JS chỉ được tách khi nhóm trang có code byte-identical; các trang còn lại
  (caugiay, dongda, faq, gioithieu, index, longbien, nhap, phoco) giữ JS
  inline như cũ để tránh mọi rủi ro hành vi.
- MotoAI: 24 trang dùng `motoai_v40_bm25plus_final.js` (giữ nguyên);
  `index.html` dùng motoai v39 ngoài chuỗi tại
  `https://motoopen.github.io/chothuexemayhanoi/motoai_v39_modelfirst_nomarkdown_nolink.js`
  (bất thường — xem "Rủi ro còn lại").
- Các file `motoai_v39_*`, `motoai_v41_*` không được dùng — giữ nguyên, không kích hoạt.

## Jekyll

Các trang có front matter rỗng (`---` `---`) để Jekyll xử lý thẻ include của các layout chung.
GitHub Pages chạy Jekyll mặc định (không có `.nojekyll`). Nội dung trang không chứa cú pháp Liquid nên output giữ nguyên.

## Rủi ro còn lại / TODO cho phase sau

1. Workflow `.github/workflows/recover-phoco.yml` khi được chạy sẽ khôi phục
   `phoco.html` từ blob "known-good" cũ (bản monolithic), ghi đè bản refactor.
   Nếu muốn giữ refactor, cần cập nhật GOOD_COMMIT/GOOD_BLOB trong workflow đó
   (việc này ngoài phạm vi refactor kiến trúc).
2. `index.html` phụ thuộc file motoai v39 host ngoài repo (motoopen.github.io).
3. `nhap.html` không có trong sitemap; giữ nguyên CSS inline (lệch chuẩn so với
   các trang còn lại).
4. JS của 8 trang (caugiay, dongda, faq, gioithieu, index, longbien, nhap,
   phoco) vẫn inline vì có khác biệt nội dung từng trang (câu trả lời chatbot,
   giá...). Phase sau có thể đồng nhất nếu chấp nhận rủi ro hành vi.


## robots.txt hosting limitation

The site is served at https://thuexemayhanoi.github.io/shop/. A robots.txt file is only honored at the hostname root (https://thuexemayhanoi.github.io/robots.txt), which is outside this repository. /shop/robots.txt is kept valid but is not guaranteed to be fetched by crawlers; this is a GitHub Pages hosting limitation, not a repository bug.
