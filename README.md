README — Thuê Xe Máy Phố Cổ (Mr Tú)

Mô tả ngắn:
Repository chứa một landing page cho dịch vụ cho thuê xe máy (HTML/CSS/JS) kèm một widget chatbot/assistant nội bộ (motoai_v40_bm25plus_final.js) — một bản “MotoAI v4.0 (BM25+ final)” tối ưu cho thị trường VN, hỗ trợ NLU nhẹ, tra cứu tài liệu cục bộ, crawler + sitemap reader, trích xuất bảng giá tự động, và một chatbot offline giả lập (fallback AI) để tư vấn/đặt xe qua Zalo/Hotline.

⸻

Mục lục
	1.	Tổng quan chức năng￼
	2.	Kiến trúc & Thành phần chính￼
	3.	Cách chạy / kiểm thử nhanh￼
	4.	Cấu hình & tuỳ chỉnh nhanh￼
	5.	Chi tiết kỹ thuật (quan trọng)￼
	6.	Local storage / keys quan trọng￼
	7.	Hành vi tìm kiếm (BM25+) — tóm tắt thuật toán￼
	8.	Crawl / Auto-price extraction￼
	9.	AI offline (fallback) và UX chatbot￼
	10.	Tiềm năng nâng cấp / TODOs￼
	11.	Bảo mật & Quyền riêng tư￼
	12.	Góp phần & License￼
	13.	Liên hệ tác giả￼

⸻

Tổng quan chức năng
	•	Landing page responsive, dark/light theme, nhiều section marketing (HERO, fleet, pricing, FAQ, contact).
	•	Floating “ultra-fab” contact + AI modal + matchmaker modal.
	•	Mini “MotoAI” widget (motoai_v40_bm25plus_final.js) tích hợp:
	•	NLU rule-based (phân loại loại xe, lượng thời gian, khu vực, tên).
	•	Intent scoring (giá, thủ tục, giao xe, liên hệ…).
	•	Giá mẫu (PRICE_TABLE) + composePrice() để trả lời giá nhanh.
	•	Local search index (BM25+ với boosts: phrase, synonym, freshness).
	•	Crawler nhẹ: sitemap reader, fallback crawl, trích xuất Last-Modified.
	•	Auto-price extraction từ nội dung web.
	•	Context lưu localStorage (turn-based, session).
	•	API giao diện: window.MotoAI_v40.open(), .send(), .learnNow(), .clear().

⸻

Kiến trúc & Thành phần chính
	•	index.html — giao diện chính, CSS + markup, modal AI, form.
	•	motoai_v40_bm25plus_final.js — engine chatbot / search / crawler / autolearn (được link defer cuối index.html).
	•	Assets: ảnh được host trực tiếp trên GitHub raw.
	•	Storage keys trong localStorage quản lý session, context, cache crawl, autoprices.

⸻

Cách chạy / kiểm thử nhanh
	1.	Clone repo hoặc mở file index.html từ thư mục local hoặc deploy trên GitHub Pages.
	2.	Mở trình duyệt (Chrome, Edge, Safari). Không cần backend.
	3.	Các action nhanh:
	•	Mở chatbot widget: window.MotoAI_v40.open()
	•	Gửi tin demo: window.MotoAI_v40.send("thuê vision 3 ngày")
	•	Forçar crawl/learn (dev): await window.MotoAI_v40.learnNow([location.origin], true)

Lưu ý: crawler sẽ dùng fetch() để truy xuất sitemap / trang — nếu host tắt CORS hoặc đang chạy từ file://, chức năng crawl có thể lỗi. Chạy trên HTTP(s) server (ví dụ npx http-server hoặc GitHub Pages).

⸻

Cấu hình & tuỳ chỉnh nhanh

Các cấu hình nằm trong file JS (biến DEF / CFG):
	•	brand, phone, zalo, map, avatar, themeColor — hiển thị UI.
	•	autolearn (boolean) — bật/tắt học tự động.
	•	viOnly — lọc nội dung VN.
	•	maxContextTurns, fetchTimeoutMs, crawlDepth, refreshHours, maxPagesPerDomain, maxTotalPages.
	•	smart.searchThreshold — ngưỡng lọc kết quả tìm kiếm.

Thay đổi trực tiếp trong motoai_v40_bm25plus_final.js hoặc truyền window.MotoAI_CONFIG trước khi script load để override.

Ví dụ cấu hình trước khi tải script:

<script>
  window.MotoAI_CONFIG = { brand: "Mr Tú", phone: "0816659199", autolearn: true, themeColor: "#007AFF" };
</script>
<script src="motoai_v40_bm25plus_final.js" defer></script>


⸻

Chi tiết kỹ thuật (quan trọng)

NLU & entity extraction
	•	TYPE_MAP + regex để phát hiện model (vision, air blade, xe ga/số, xe điện, 50cc, xe côn tay,…).
	•	detectQty() bắt số + unit (ngày/tuần/tháng).
	•	detectArea() heuristics đơn giản cho vài khu vực.
	•	detectIntent() trả về bảng score cho intent (needPrice, needDocs, needContact, needDelivery, needReturn, needPolicy).

Price model
	•	PRICE_TABLE: bảng giá mẫu theo model + đơn vị (day/week/month). composePrice() tạo câu trả lời tự nhiên.
	•	mergeAutoPrices() cập nhật PRICE_TABLE bằng median (p50) dữ liệu trích xuất từ crawl.

Context / dialog
	•	Lưu turns trong localStorage[K.ctx], maxContextTurns mặc định 8.
	•	Multi-step stateful flows: ASK_MODEL, ASK_DURATION, ASK_DELIVERY, etc.

⸻

Local storage / keys quan trọng
	•	MotoAI_v39_session — session chat (user/bot messages).
	•	MotoAI_v39_ctx — dialog context/turns.
	•	MotoAI_v39_learn — cache crawl / index.
	•	MotoAI_v39_auto_prices — bảng giá trích xuất (raw).
	•	MotoAI_v39_learnStamp — thời gian learn gần nhất.
	•	MotoAI_v39_lastClean — timestamp clean lần cuối.

Xoá toàn bộ cache dev:

window.MotoAI_v40.clear();
localStorage.removeItem('MotoAI_v39_autoprices');


⸻

Hành vi tìm kiếm (BM25+) — tóm tắt thuật toán
	•	Tokenize Unicode, loại stopwords VN.
	•	Tính df/tf trên tập trang đã crawl (cache learn).
	•	BM25+ variant: chuẩn BM25 cộng delta thích ứng (adaptiveDelta) để adjust theo độ dài tài liệu.
	•	Boosts bổ sung:
	•	phraseBoost() nếu câu query xuất hiện nguyên văn.
	•	synonymBoost() dùng map synonym (xe ga ⇄ vision, lead, air blade…).
	•	freshnessBoost() nếu meta.ts (Last-Modified) mới.
	•	scoreDocMeta() bonus nếu URL/title khớp dạng banggia, thutuc.
	•	Kết quả lọc theo CFG.smart.searchThreshold (mặc định 1.0).

⸻

Crawl / Auto-price extraction
	•	learnSites(origins, force):
	•	Gọi readSitemap() để đọc sitemap.xml; nếu không có sitemap, fallback fallbackCrawl() lấy các link từ homepage.
	•	pullPages() tải trang bằng fetchTextWithMeta() (có đọc Last-Modified) và trích xuất title/meta description.
	•	extractPricesFromText() quét dòng, regex detect model + giá, parse số với đơn vị (k, tr, triệu).
	•	Kết quả lưu K.autoprices, mergeAutoPrices() cập nhật PRICE_TABLE.

Lưu ý: Crawl client-side phụ thuộc CORS. Để crawl toàn diện, cần chạy crawler server-side (đề xuất nâng cấp).

⸻

AI offline (fallback) và UX chatbot
	•	Nếu không có API, có Render.callGeminiWithRetry()—thực chất là một fallback rule-based + template reply generator (không gọi API bên ngoài).
	•	Chat widget UI premium: glassmorphism, typing indicator, tags quick-queries.
	•	API dùng trong trang:
	•	window.MotoAI_v40.open() — mở widget
	•	window.MotoAI_v40.close()
	•	window.MotoAI_v40.send("...")
	•	window.MotoAI_v40.learnNow([urls], force) — trigger crawl/learn
	•	window.MotoAI_v40.clear() — xoá caches

⸻

Tiềm năng nâng cấp / TODOs (ưu tiên)
	1.	Crawl server-side (cron) để bypass CORS, tăng độ tin cậy, index sâu hơn.
	2.	Chỉ số an toàn: kiểm tra robots.txt, rate-limit, user-agent rõ ràng.
	3.	Indexstore: chuyển BM25 từ localStorage sang indexedDB hoặc server search service (Elastic / Typesense / Meilisearch).
	4.	Unit tests cho NLU regex / price parsing.
	5.	Nâng cấp NLU: dùng small transformer (on-prem) hoặc OpenAI/Anthropic để intent/entity extraction cho độ chính xác cao hơn.
	6.	Tối ưu bảo mật: validate input trước khi dùng trong mailto/href để tránh injection.
	7.	I18n & locale: hiện code giả định VN; tách strings để dễ translate.
	8.	Accessibility: kiểm tra contrast, keyboard trap, aria attributes cho modal (đã thêm nhiều fix accessibility nhưng cần audit).

⸻

Bảo mật & Quyền riêng tư
	•	Hiện lưu ctx, session, autoprices trong localStorage. Không upload/đẩy thông tin người dùng lên server.
	•	Contact form dùng mailto: — không có backend storage. Nếu cần lưu lead, phải thêm backend an toàn (HTTPS) và xác thực.
	•	Không giữ giấy tờ: UI khuyến cáo không giữ giấy tờ gốc; đây là nội dung marketing — chính sách thực tế cần tuân thủ pháp luật địa phương.

⸻

Góp phần & License
	•	Đề xuất license: MIT (nếu bạn muốn chia public). Thêm file LICENSE nếu đồng ý.
	•	Cách đóng góp: fork → feature branch → PR → mô tả rõ sửa lỗi / thay đổi.
	•	Khi gửi PR, kèm checklist: cross-browser test, desktop/mobile, accessibility quick test.

⸻

Ví dụ cấu hình / snippet dev

Ghi đè cấu hình (trước script):

<script>
  window.MotoAI_CONFIG = {
    brand: "Mr Tú",
    phone: "0816659199",
    autolearn: true,
    refreshHours: 12,
    smart: { searchThreshold: 0.8 }
  };
</script>
<script src="/path/to/motoai_v40_bm25plus_final.js" defer></script>

Xoá cache dev nhanh:

localStorage.removeItem('MotoAI_v39_learn');
localStorage.removeItem('MotoAI_v39_autoprices');
localStorage.removeItem('MotoAI_v39_ctx');

