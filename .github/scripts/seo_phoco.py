#!/usr/bin/env python3
"""
SEO Primary Keyword Batch — Phố Cổ
Exact string replacement script for phoco.html
"""

from pathlib import Path
import sys

ROOT = Path(".")
TARGET = ROOT / "phoco.html"

# Exact replacement pairs: (OLD, NEW)
REPLACEMENTS = [
    # 1. TITLE
    (
        '<title>Thuê Xe Máy Phố Cổ Uy Tín, Thủ Tục Nhanh - Mr Tú 081.665.9199</title>',
        '<title>Thuê Xe Máy Phố Cổ Hà Nội - Mr Tú | Xe Số, Xe Ga</title>'
    ),
    # 2. META DESCRIPTION
    (
        '<meta name="description" content="Dịch vụ thuê xe máy Phố Cổ uy tín số 1 Hà Nội. Xe mới 2024, giao tận nơi, thủ tục 5 phút không cọc. Vi vu Bờ Hồ, 36 phố phường. Gọi Mr Tú 081.665.9199!">',
        '<meta name="description" content="Thuê xe máy Phố Cổ Hà Nội tại Mr Tú với xe số, xe ga và hỗ trợ giao nhận khu vực trung tâm. Xem giá tham khảo, thủ tục thuê và liên hệ kiểm tra xe.">'
    ),
    # 3. OG TITLE
    (
        '<meta property="og:title" content="Thuê Xe Máy Phố Cổ Uy Tín, Thủ Tục Nhanh - Mr Tú">',
        '<meta property="og:title" content="Thuê Xe Máy Phố Cổ Hà Nội - Mr Tú">'
    ),
    # 4. OG DESCRIPTION
    (
        '<meta property="og:description" content="Chuyên cho thuê xe máy tại Phố Cổ & Hoàn Kiếm. Xe ngon, giá rẻ, hỗ trợ 24/7. Nhận xe ngay chỉ sau 5 phút.">',
        '<meta property="og:description" content="Dịch vụ thuê xe máy Phố Cổ Hà Nội tại Mr Tú với nhiều lựa chọn xe và hỗ trợ giao nhận tại khu vực trung tâm.">'
    ),
    # 5. TWITTER TITLE
    (
        '<meta property="twitter:title" content="Thuê Xe Máy Phố Cổ - Mr Tú">',
        '<meta property="twitter:title" content="Thuê Xe Máy Phố Cổ Hà Nội - Mr Tú">'
    ),
    # 6. TWITTER DESCRIPTION
    (
        '<meta property="twitter:description" content="Dịch vụ thuê xe máy tốt nhất Phố Cổ Hà Nội. Không cần cọc, giao xe tận nơi.">',
        '<meta property="twitter:description" content="Thuê xe máy Phố Cổ Hà Nội tại Mr Tú với xe số, xe ga và thông tin thuê xe rõ ràng cho khách tại khu vực trung tâm.">'
    ),
    # 7. HERO BADGE
    (
        'Uy tín số 1 Hoàn Kiếm',
        'Thuê xe máy tại Phố Cổ Hà Nội'
    ),
    # 8. H1
    (
        'Dịch vụ cho thuê xe máy Phố Cổ uy tín, thủ tục nhanh - Mr Tú',
        'Thuê xe máy Phố Cổ Hà Nội - Mr Tú'
    ),
    # 9. FIRST HERO PARAGRAPH
    (
        'Bạn đang tìm dịch vụ',
        'Bạn đang tìm dịch vụ <strong>thuê xe máy Phố Cổ Hà Nội</strong> để chủ động di chuyển quanh khu vực trung tâm? Mr Tú cung cấp xe số, xe ga và hỗ trợ giao nhận tại Phố Cổ. Xem lựa chọn xe, chi phí tham khảo và liên hệ để kiểm tra tình trạng xe trước khi đặt.'
    ),
    # 10. FIRST SEO H2
    (
        'Tại sao nên thuê xe máy Phố Cổ tại Mr Tú?',
        'Tại sao nên thuê xe máy Phố Cổ Hà Nội tại Mr Tú?'
    ),
    # 11. PRICE H2
    (
        'Bảng giá thuê xe máy Phố Cổ 2024',
        'Bảng giá thuê xe máy Phố Cổ Hà Nội'
    ),
]


def main():
    # Read the file
    if not TARGET.exists():
        print(f"FAIL: {TARGET} not found")
        sys.exit(1)
    
    content = TARGET.read_text(encoding="utf-8")
    
    # Validate: each OLD must occur exactly once
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        count = content.count(old)
        if count != 1:
            print(f"FAIL: target {i} OLD string occurs {count} times (expected 1)")
            print(f"  OLD: {old[:80]}...")
            sys.exit(1)
    
    # Perform replacements
    for old, new in REPLACEMENTS:
        content = content.replace(old, new, 1)
    
    # Write the file
    TARGET.write_text(content, encoding="utf-8")
    
    # Validate: check that changes were applied
    new_content = TARGET.read_text(encoding="utf-8")
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        if old in new_content:
            print(f"FAIL: target {i} OLD string still present after replacement")
            sys.exit(1)
        if new not in new_content:
            print(f"FAIL: target {i} NEW string not found after replacement")
            sys.exit(1)
    
    print(f"SUCCESS: Applied {len(REPLACEMENTS)} replacements to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())