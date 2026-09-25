#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate test fixtures under tests/fixtures/ (run from repo root)."""
import io
import os

OUT = "tests/fixtures"
os.makedirs(OUT, exist_ok=True)

BODY_OK = """
<h2>Kiểm tra ngoại quan</h2>
<p>Trước khi nhận xe, bạn nên đi một vòng quanh xe để kiểm tra vết xước cũ, gương chiếu hậu và đèn signaling. Ghi lại hiện trạng bằng ảnh chụp gửi cho Mr Tú qua Zalo để tránh tranh cãi khi trả xe.</p>
<p>Nhìn kỹ lốp trước và lốp sau: lốp mòn không đều sẽ khiến xe bị lệch tay lái, đặc biệt khi đi trong phố đông. Nếu thấy lốp quá mòn, yêu cầu đổi xe ngay lập tức.</p>
<h2>Kiểm tra động cơ và phanh</h2>
<p>Đề nổ máy, bóp phanh trước sau và thử còi xi nhan. Máy nổ êm, không có tiếng kêu lạ là dấu hiệu xe được bảo dưỡng tốt. Ví dụ Honda Vision cho thuê bên em có giá 200.000đ/ngày và luôn được bảo dưỡng định kỳ.</p>
<p>Chạy thử một vòng ngắn nếu được phép. Khi chạy thử, để ý phanh có ăn không, số có vào có nhánh không và cốp xe đóng mở có chắc không.</p>
<h2>Về đặt cọc và giấy tờ</h2>
<p>Yêu cầu giấy tờ và mức đặt cọc tùy trường hợp thuê, thường khoảng 2.000.000 – 5.000.000đ tùy xe và điều kiện. Vui lòng liên hệ để xác nhận trước khi nhận xe.</p>
<p>Nếu bạn cần hỗ trợ thêm về quy trình nhận xe, xem hướng dẫn chi tiết trên trang thủ tục thuê xe. Và nếu muốn mở rộng hành trình, có thể tham khảo gợi ý du lịch hoặc cẩm nang an toàn trước khi lên đường.</p>
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="https://thuexemayhanoi.github.io/shop/articles/{slug}.html">
<meta name="author" content="Mr Tú">
<meta property="article:published_time" content="2026-10-01">
{robots}
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":"{title}","author":{{"@type":"Person","name":"Mr Tú"}},"datePublished":"2026-10-01"}}
</script>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Trang chủ","item":"/shop/"}},{{"@type":"ListItem","position":2,"name":"Kinh nghiệm","item":"/shop/kinhnghiem.html"}}]}}
</script>
</head>
<body>
<main>
<h1>{h1}</h1>
{body}
</main>
</body>
</html>
"""

LINKS_OK = """
<p>Nội dung liên quan: <a href="kinhnghiem.html">cẩm nang kinh nghiệm</a>, <a href="dulich.html">gợi ý du lịch Hà Nội</a> và <a href="antoan.html">cẩm nang an toàn</a> của Mr Tú.</p>
<p>Bạn cũng có thể xem <a href="thutuc.html">thủ tục thuê xe chi tiết</a> trước khi đặt xe.</p>
"""


def w(name, content):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(content)


def base(title="Kinh nghiệm kiểm tra xe máy trước khi nhận",
         h1="Kinh nghiệm kiểm tra xe máy trước khi nhận xe",
         slug="sample-kn-01-check-xe",
         body=BODY_OK + LINKS_OK,
         extra_head="", robots=""):
    return TEMPLATE.format(title=title, h1=h1, slug=slug, body=body,
                           desc="Hướng dẫn kiểm tra xe máy trước khi nhận khi thuê xe ở Hà Nội: ngoại quan, động cơ, phanh và giấy tờ cần chuẩn bị.",
                           robots=robots) + extra_head


# ---- GOOD ----
w("good.html", base())
w("good2.html", base(title="Đi xe máy trong Phố Cổ cần lưu ý những đường nào?",
                     h1="Đi xe máy trong Phố Cổ cần lưu ý những đường nào?",
                     slug="sample-dl-01-pho-co",
                     body="""
<h2>Những con đường một chiều dễ nhầm</h2>
<p>Phố Cổ Hà Nội có rất nhiều phố một chiều như Hàng Bông, Hàng Gai vào giờ cao điểm. Khi đi xe máy trong khu vực này, bạn nên đi chậm và quan sát biển báo ở mỗi ngã tư. Nhiều khách du lịch thuê xe máy lần đầu dễ đi ngược chiều ở các ngõ nhỏ như ngõ Phất Lộc.</p>
<p>Lộ trình gợi ý: bắt đầu từ hồ Hoàn Kiếm, men theo Hàng Khay lên Hàng Bông, rẽ vào Hàng Điều rồi quay lại Tạ Hiện. Đây là vòng lặp đẹp và ít đường ngược chiều.</p>
<h2>Gửi xe ở đâu cho tiện</h2>
<p>Các bãi gửi xe quanh Bờ Hồ và Trần Nhật Duật là lựa chọn tiện nhất khi bạn muốn đi bộ khám phá 36 phố phường. Giá gửi xe thường từ 5.000đ đến 10.000đ mỗi lượt.</p>
<p>Để có thêm ý tưởng cho các ngày tiếp theo, xem thêm <a href="dulich.html">gợi ý du lịch Hà Nội</a> hoặc <a href="cungduong.html">các cung đường từ Hà Nội</a> nếu muốn đi xa hơn. Tham khảo thêm <a href="kinhnghiem.html">kinh nghiệm thuê xe máy ở Hà Nội</a>.</p>
"""))

# ---- FAIL fixtures ----
w("fail_no_h1.html", base(body=BODY_OK.replace("<h1>", "<h2>").replace("</h1>", "</h2>", 1).replace(
    "Kinh nghiệm kiểm tra xe máy trước khi nhận xe</h2>", "Kinh nghiệm kiểm tra xe máy trước khi nhận xe</h2>", 1) + LINKS_OK)
 ) if False else w("fail_no_h1.html", TEMPLATE.format(
    title="Kinh nghiệm kiểm tra xe máy trước khi nhận",
    h1="", slug="sample-kn-01-check-xe", body=BODY_OK + LINKS_OK,
    desc="Hướng dẫn kiểm tra xe máy.",
    robots="").replace("<h1></h1>", ""))

w("fail_two_h1.html", base() + "\n<h1>Kinh nghiệm kiểm tra xe máy trước khi nhận xe (bản sao)</h1>")

w("fail_no_canonical.html", base().replace(
    '<link rel="canonical" href="https://thuexemayhanoi.github.io/shop/articles/sample-kn-01-check-xe.html">', ''))

w("fail_wrong_canonical.html", base().replace(
    'https://thuexemayhanoi.github.io/shop/articles/sample-kn-01-check-xe.html',
    'https://thuexemayhanoi.github.io/shop/articles/some-other-article.html'))

w("fail_vision_price.html", base(body=BODY_OK.replace(
    "Honda Vision cho thuê bên em có giá 200.000đ/ngày",
    "Honda Vision cho thuê bên em có giá 150.000đ/ngày") + LINKS_OK))

w("fail_ebike_price.html", base(body=BODY_OK.replace(
    "Honda Vision cho thuê bên em có giá 200.000đ/ngày",
    "Xe điện cho thuê bên em có giá 180.000đ/ngày") + LINKS_OK))

w("fail_lead_price.html", base(body=BODY_OK.replace(
    "Honda Vision cho thuê bên em có giá 200.000đ/ngày",
    "Honda Lead cho thuê bên em có giá 200.000đ/ngày") + LINKS_OK))

w("fail_50cc_price.html", base(body=BODY_OK.replace(
    "Honda Vision cho thuê bên em có giá 200.000đ/ngày",
    "Xe 50cc cho thuê bên em có giá 200.000đ/ngày") + LINKS_OK))

w("fail_deposit.html", base(body=BODY_OK.replace(
    "Yêu cầu giấy tờ và mức đặt cọc tùy trường hợp thuê, thường khoảng 2.000.000 – 5.000.000đ tùy xe và điều kiện. Vui lòng liên hệ để xác nhận trước khi nhận xe.",
    "Miễn cọc 100% khi thuê xe online, không cần cọc.") + LINKS_OK))

w("fail_broken_link.html", base(body=BODY_OK + """
<p>Xem thêm <a href="trang-khong-ton-tai.html">trang không tồn tại</a> để biết thêm chi tiết, cùng <a href="kinhnghiem.html">cẩm nang kinh nghiệm</a> và <a href="dulich.html">gợi ý du lịch</a>.</p>
"""))

w("fail_placeholder.html", base(body=BODY_OK + """
<p>TODO: chèn thêm nội dung phần này sau. [chèn đoạn giới thiệu ở đây]</p>
""" + LINKS_OK))

# duplicate primary keyword fixture: same primary_keyword as SAMPLE-KN-01 row
w("fail_dup_keyword.html", base(
    title="Kinh nghiệm kiểm tra xe máy trước khi nhận khi thuê ở Hà Nội",
    slug="sample-kn-02-dup"))

# protected intent collision fixture: primary keyword = phoco's intent
w("fail_protected_intent.html", base(
    title="Thuê xe máy Phố Cổ Hà Nội giá rẻ nhất",
    h1="Thuê xe máy Phố Cổ Hà Nội",
    slug="sample-fail-protected"))

# ---- REVIEW fixtures ----
# near-similar title to matrix row SAMPLE-DL-01 but different keyword
w("review_similar_title.html", base(
    title="Đi xe máy trong Phố Cổ cần lưu ý những đường nào ở Hà Nội?",
    slug="sample-dl-02-similar",
    body=BODY_OK + LINKS_OK))

# weak internal linking: parent hub not linked, single link
w("review_weak_links.html", base(body=BODY_OK + """
<p>Xem thêm <a href="thutuc.html">thủ tục thuê xe</a> nếu bạn cần.</p>
"""))

# requires_sources article (legal topic) missing source section
w("review_no_sources.html", base(
    title="Những lỗi phạt nguội chủ xe máy hay gặp",
    h1="Những lỗi phạt nguội chủ xe máy hay gặp",
    slug="sample-at-01-phat-nguoi",
    body="""
<h2>Lỗi vượt đèn đỏ</h2>
<p>Vượt đèn đỏ là một trong những lỗi bị ghi hình phạt nguội phổ biến nhất hiện nay. Khi đi xe máy, bạn luôn phải dừng trước vạch dừng khi đèn đỏ bật lên. Mức phạt cho lỗi này có thể lên đến vài triệu đồng tùy tình huống.</p>
<h2>Đi không đội mũ bảo hiểm</h2>
<p>Theo quy định về an toàn giao thông, người điều khiển xe máy phải đội mũ bảo hiểm đạt chuẩn. Camera phạt nguội hiện ghi nhận cả lỗi không cài quai mũ bảo hiểm.</p>
<h2>Đi ngược chiều và lấn làn</h2>
<p>Đi ngược chiều trên đường một chiều là lỗi nghiêm trọng, dễ bị ghi hình và xử phạt. Luôn quan sát biển báo trước khi rẽ vào phố mới, nhất là trong khu Phố Cổ nhiều đường một chiều.</p>
<p>Để chuẩn bị tốt hơn, bạn nên xem <a href="antoan.html">cẩm nang an toàn</a> và <a href="faq.html">câu hỏi thường gặp</a> của Mr Tú.</p>
"""))
print("fixtures written:", sorted(os.listdir(OUT)))
