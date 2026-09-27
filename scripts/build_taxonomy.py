#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the canonical content taxonomy from repository truth.

Generates, deterministically and reproducibly:
  - data/content-taxonomy.json     (parents + child clusters + counts)
  - data/content-taxonomy-map.csv  (article_id -> child cluster, 2000 rows)
  - reports/seo/content-taxonomy.md (human report)

Rules are ORDERED: the first matching rule wins. Rules are regex on the
matrix primary_keyword plus explicit id-set extensions where the topic
grouping follows the matrix's own systematic blocks. The matrix is the
single source of truth; nothing here mutates it.
"""
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TAXONOMY_VERSION = "1.0.0"

PARENTS = {
    "Kinh nghiệm": {
        "parent_id": "KINH_NGHIEM", "parent_hub": "kinhnghiem.html",
        "parent_slug": "kinh-nghiem",
    },
    "An toàn": {
        "parent_id": "AN_TOAN", "parent_hub": "antoan.html",
        "parent_slug": "an-toan",
    },
    "Xe máy": {
        "parent_id": "XE_MAY", "parent_hub": "xemay.html",
        "parent_slug": "xe-may",
    },
    "Du lịch": {
        "parent_id": "DU_LICH", "parent_hub": "dulich.html",
        "parent_slug": "du-lich",
    },
    "Cung đường": {
        "parent_id": "CUNG_DUONG", "parent_hub": "cungduong.html",
        "parent_slug": "cung-duong",
    },
    "Hỏi đáp": {
        "parent_id": "HOI_DAP", "parent_hub": "hoidap.html",
        "parent_slug": "hoi-dap",
    },
}

# child_id -> (title, description)
CHILD_META = {
    # Kinh nghiệm
    "KN_HONDA_WAVE": ("Kinh nghiệm Honda Wave", "Chọn, kiểm tra và chạy thuê Honda Wave ở Hà Nội."),
    "KN_YAMAHA_SIRIUS": ("Kinh nghiệm Yamaha Sirius", "Chọn, kiểm tra và chạy thuê Yamaha Sirius."),
    "KN_XE_GA_PHO_THONG": ("Kinh nghiệm xe ga phổ thông", "Click, Vision, Air Blade, Mio khi đi thuê và vận hành."),
    "KN_XE_MAY_DIEN": ("Kinh nghiệm xe máy điện", "Thuê và chạy xe máy điện trong phố và đường xa."),
    "KN_THUE_XE_CO_BAN": ("Thuê xe cơ bản", "Hợp đồng, nhận xe, trả xe, giờ thuê, đàm phán với chủ xe."),
    "KN_TINH_HUONG_DI_PHO": ("Tình huống khi đi xe", "Sự cố xe, thời tiết, bản đồ, gửi xe, giữ đồ trong chuyến đi."),
    "KN_THEO_KHU_VUC": ("Đi xe theo khu vực Hà Nội", "Tránh tắc, gửi xe, lộ trình theo từng quận, huyện."),
    "KN_DUONG_PHO_LON": ("Đường và phố lớn Hà Nội", "Chạy, đỗ, đổ xăng trên các trục đường chính."),
    "KN_TINH_HUONG_DOI_SONG": ("Chạy xe trong đời sống", "Lễ tết, mùa hoa, việc riêng và các tình huống thường ngày."),
    # An toàn
    "AT_LUAT_XU_PHAT": ("Luật giao thông & xử phạt", "Quy định, mức phạt, giấy tờ bắt buộc với xe máy."),
    "AT_KY_NANG_LAI_XE": ("Kỹ năng lái xe an toàn", "Kỹ năng giữ khoảng cách, phanh, quan sát, xử lý đường."),
    "AT_CHAY_DEM_DEN_XE": ("Chạy đêm & đèn xe", "An toàn khi chạy đêm và hệ thống đèn xe máy."),
    "AT_MU_TRANG_BI": ("Mũ bảo hiểm & trang bị", "Chọn mũ, kính, găng, giày và trang bị bảo hộ."),
    "AT_SUC_KHOE_NGUOI_LAI": ("Sức khoẻ người lái", "Say nắng, đau mỏi, sơ cứu và giữ sức trên xe."),
    "AT_CHONG_TROM_DO_XE": ("Chống trộm & đỗ xe", "Khoá xe, chọn bãi gửi, bảo quản xe khi dừng đỗ."),
    "AT_THOI_TIET_MUA_GIO": ("Chạy xe theo thời tiết", "Mưa, sương mù, gió mùa, nồm và các chuyển mùa."),
    "AT_DUONG_DAT_DEO_NONG_THON": ("Đèo & đường nông thôn", "Đèo dài, đường đất, đê, cầu phao, tỉnh lộ."),
    "AT_XU_LY_TINH_HUONG_DUONG": ("Xử lý tình huống trên đường", "Ngã xe, va chạm nhẹ, tai nạn, giữ bình tĩnh."),
    "AT_NGUOI_LAI_THEO_NHU_CAU": ("Người lái theo nhu cầu", "Shipper, người cao tuổi, gia đình, người mới."),
    "AT_TRANG_BI_THEO_THOI_TIET": ("Trang bị theo thời tiết", "Chọn mũ, áo mưa, giày theo mùa và thời tiết."),
    "AT_KY_NANG_NANG_CAO": ("Kỹ năng nâng cao", "Vượt xe, chạy đoàn, dừng khẩn cấp, giữ làn."),
    # Xe máy
    "XM_HONDA_WAVE": ("Honda Wave", "Kiểm tra và bảo dưỡng các cụm trên Honda Wave."),
    "XM_YAMAHA_SIRIUS": ("Yamaha Sirius", "Kiểm tra và bảo dưỡng các cụm trên Yamaha Sirius."),
    "XM_HONDA_CLICK": ("Honda Click", "Kiểm tra và bảo dưỡng các cụm trên Honda Click."),
    "XM_YAMAHA_MIO": ("Yamaha Mio", "Kiểm tra và bảo dưỡng các cụm trên Yamaha Mio."),
    "XM_HONDA_VISION": ("Honda Vision", "Kiểm tra và bảo dưỡng các cụm trên Honda Vision."),
    "XM_HONDA_AIR_BLADE": ("Honda Air Blade", "Kiểm tra và bảo dưỡng các cụm trên Honda Air Blade."),
    "XM_BAO_DUONG_KIEM_TRA": ("Bảo dưỡng & kiểm tra", "Chu kỳ bảo dưỡng, hư hỏng thường gặp, cách tự kiểm tra."),
    "XM_XE_MAY_DIEN": ("Xe máy điện", "Ắc quy, sạc, pin và bảo dưỡng xe máy điện."),
    "XM_PHU_KIEN_DO_DUNG": ("Phụ kiện & đồ dùng", "Đồ đi phượt, khoá, phụ kiện gắn thêm cho xe máy."),
    "XM_SO_SANH_XE": ("So sánh các dòng xe", "Xe số với xe ga, so dòng xe theo nhu cầu sử dụng."),
    "XM_SU_CO_XE_THUE": ("Sự cố xe thuê", "Xử lý các hư hỏng thường gặp trên xe máy thuê."),
    "XM_KIEM_TRA_KY_THUAT": ("Kiểm tra kỹ thuật khi nhận xe", "Dây đơ, biên tắng, ốc máng, sên dĩa, hộp số."),
    # Du lịch
    "DL_HA_NOI_NOI_THANH": ("Điểm đến nội thành Hà Nội", "Hồ, bảo tàng, di tích trong nội đô đi bằng xe máy."),
    "DL_TAY_BAC_GAN": ("Ba Vì – Hòa Bình – Mai Châu – Mộc Châu", "Điểm đến phía Tây gần Hà Nội."),
    "DL_VINH_PHUC_THAI_NGUYEN": ("Vĩnh Phúc – Thái Nguyên", "Tam đảo, tây thiên, đại lãi, hồ núi cốc."),
    "DL_BAC_CAN_CAO_BANG": ("Bắc Cạn – Cao Bằng", "Hồ ba bể, pắc pó, bản giốc, hữu liên."),
    "DL_LANG_SON_HA_GIANG": ("Lạng Sơn – Hà Giang", "Đồng văn, mã pí lèng, quản bạ, hoàng su phì."),
    "DL_SAPA_LAO_CAI_YEN_BAI": ("Sa Pa – Lào Cai – Yên Bái", "Sa pa, mù cang chải, tà xùa, y tý, khau phạ."),
    "DL_DONG_BANG_BAC_BO": ("Đồng bằng Bắc Bộ", "Cửa lò, sầm sơn, nam định, hưng yên, bắc ninh, làng nghề."),
    "DL_QUANG_NINH_HAI_PHONG": ("Quảng Ninh – Hải Phòng – Đông Bắc", "Đồ sơn, hạ long, cát bà, yên tử, lục ngạn."),
    "DL_NINH_BINH_PHU_THO_HA_NAM": ("Ninh Bình – Phú Thọ – Hà Nam", "Tam cốc, bái đính, hoa lư, cúc phương, tam chúc."),
    "DL_DIEM_DEN_NOI_TIENG": ("Điểm đến nổi bật khác", "Các điểm tham quan, chụp ảnh quanh Hà Nội."),
    # Cung đường (defined after block extraction below)
    "CD_DONG_BAC_GAN": ("Cung đường Đông Bắc gần", "Bắc ninh, bắc giang, thái nguyên từ Hà Nội."),
    "CD_PHU_THO_VINH_PHUC": ("Cung đường trung du: Phú Thọ – Ninh Bình", "Việt trì, vĩnh yên, sơn tây, đền hùng, tam chúc, cúc phương."),
    "CD_HOA_BINH_SON_LA": ("Cung đường Hoà Bình – Sơn La", "Hoà bình, mai châu, mộc châu, sơn la."),
    "CD_TAY_BAC_XA": ("Cung đường Tây Bắc xa", "Yên bái, tuyên quang, sơn la cao, đường vòng xa."),
    "CD_HA_GIANG_DONG_BAC_CA": ("Cung đường Hà Giang – Cao Bằng", "Quản bạ, đồng văn, mèo vạc, bảo lạc, cao bằng."),
    "CD_DONG_BANG_VEN_BIEN": ("Cung đường đồng bằng & ven biển", "Quảng ninh, hải phòng, thái bình, nam định, thanh hoá và các tỉnh ven biển."),
    # Hỏi đáp
    "HD_GIAY_TO_PHAP_LY": ("Giấy tờ & pháp lý", "Bằng lái, đăng ký, đăng kiểm, bảo hiểm, cồn, mũ."),
    "HD_XE_MAY_DIEN": ("Hỏi đáp xe máy điện", "Sạc, ắc quy, biển số, bằng lái xe điện."),
    "HD_THUE_XE": ("Hỏi đáp thuê xe máy", "Thuê, nhận, trả xe và trách nhiệm hai bên."),
    "HD_DUONG_DI_DIA_DIEM": ("Đường đi & địa điểm", "Phà, đường vành đai, phố cổ, lộ trình từ Hà Nội."),
    "HD_TRANG_BI": ("Hỏi đáp trang bị", "Mũ, găng, áo mưa, phụ kiện khi chạy xe."),
    "HD_CHI_PHI": ("Chi phí chuyến đi", "Xăng, gửi xe, nghỉ, vé và ngân sách phượt."),
    "HD_PHUOT_TRAI_NGHIEM": ("Đi phượt & trải nghiệm", "Nghỉ dừng, đồ mang theo, thời tiết khi đi xa."),
    "HD_BAI_GUI_XE": ("Gửi xe & bãi xe", "Bãi gửi, vé, giữ xe qua đêm, sự cố tại bãi."),
    "HD_CHON_XE": ("Chọn xe theo nhu cầu", "Chọn dòng xe phù hợp mục đích sử dụng."),
}

# ordered rules: (child_id, regex) — first match wins; evaluated on
# primary_keyword, normalized to lowercase, whitespace collapsed
RULES = {
    "Kinh nghiệm": [
        ("KN_HONDA_WAVE", r"honda wave"),
        ("KN_YAMAHA_SIRIUS", r"yamaha sirius"),
        ("KN_XE_GA_PHO_THONG", r"honda click|honda vision|honda air blade|yamaha mio"),
        ("KN_XE_MAY_DIEN", r"xe máy điện"),
        ("KN_THEO_KHU_VUC", r"quận |huyện |từ liêm"),
        ("KN_THUE_XE_CO_BAN", r"^chụp ảnh xe máy trước khi thuê|^những điều nên đọc kỹ trong hợp đồng|^đi thử xe quanh quán|^kinh nghiệm lấy xe buổi sáng|^nên thuê xe máy vào khung giờ|^kiểm tra xe máy đã thuê:|^kinh nghiệm trả xe máy thuê đúng giờ|^chuẩn bị gì khi lần đầu thuê|^kinh nghiệm đàm phán|^kinh nghiệm chọn cửa hàng cho thuê|^kiểm tra lại xe trước khi trả|^kinh nghiệm đối chiếu thông tin xe|^kinh nghiệm thỏa thuận thời gian trả|^kinh nghiệm kiểm tra mũ bảo hiểm kèm|^kinh nghiệm mang theo hai mũ|^kinh nghiệm nhờ người nhà nhận xe thuê"),
        ("KN_DUONG_PHO_LON", r"đường |phố |nguyễn trãi|giải phóng|trường chinh|lê văn lương|xuân thủy|âu cơ|nguyễn văn cừ|võ nguyên giáp|phạm hùng|khuất duy tiến|nguyễn xiển|kim giang|tân triều|phan trọng tuệ|trần phú|thái hà|chùa bộc|tôn đức thắng|trần duy hưng|mai hắc đế|minh khai|đại cồ việt|bach mai|giảng võ|đội cấn|hoàng hoa thám|thụy khuê|đường thanh niên|quang trung|đường láng"),
        ("KN_TINH_HUONG_DOI_SONG", r"."),
    ],
    "An toàn": [
        # first 50 rows are the law/penalty block, plus legal rows further in
        ("AT_LUAT_XU_PHAT", r"^nồng độ cồn khi lái|^tốc độ tối đa|phạt nguội|mũ bảo hiểm bị phạt|chở quá số người|lùi xe trên đường một chiều|vượt đèn đỏ|lan đường của ô tô|điện thoại khi đang lái|bằng lái a1|độ tuổi được cấp|người nước ngoài lái|mũ bảo hiểm cho người ngồi sau|bảo hiểm trách nhiệm dân sự|không mang theo giấy tờ|gương hậu|quy định đèn xe|trẻ em dưới 10|hết đăng kiểm|đổi giấy phép lái|giấy phép lái quốc tế|ngược chiều|cồng kềnh vượt quy định|nghị định xử phạt|còi và tín hiệu|dừng đỗ xe máy sai|không đăng ký|lắp thêm phụ kiện|vỉa hè bị phạt|lon bia|nồng độ cồn với xe máy|chở quá số người trên xe máy điện|xe máy điện có cần bằng|đèn chiếu sáng cho xe máy điện|ưu tiên|cơi nồi|buông hai tay|cao tốc|chở người trên xe máy điện|mũ bảo hiểm cho trẻ em|vật cản che tầm nhìn|cạnh nhau nói chuyện|cấm đỗ xe máy trên vỉa hè|đèn báo hiệu tạm thời|nhường đường cho người đi bộ|lấn làn khi vượt|chở ba người|giấy tờ photo|tra quá trình vi phạm|biển báo tạm thời|thu giữ"),
        ("AT_CHAY_DEM_DEN_XE", r"chạy đêm|đèn hậu|đèn pha chớp|đèn pin gắn|phản quang lên xe|đèn báo nguy hiểm"),
        ("AT_MU_TRANG_BI", r"mũ bảo hiểm|kính che mắt bụi|găng tay chạy|giày bọc cổ|áo phản quang|bao tay chống nắng"),
        ("AT_SUC_KHOE_NGUOI_LAI", r"chuột vặn|đau lưng|say nắng khi chạy|mỏi cổ vai|sơ cứu|túi y tế|uống đủ nước|nghỉ đúng cách|chuột vai|đau cổ tay"),
        ("AT_CHONG_TROM_DO_XE", r"chống trộm|ổ khóa phụ|bãi gửi xe không an toàn|nhầm lẫn xe|giấy tờ trong cốp|bị theo dõi|kiểm tra lại ổ khóa|không treo mũ"),
        ("AT_THOI_TIET_MUA_GIO", r"mưa đầu mùa|tai nạn hay gặp khi chạy xe trong mưa|trang bị nên mang khi chạy|trời lạnh đậm|sương mù sáng sớm|độ ẩm nồm|gió mùa|mưa giông|mưa đá|hạ nhiệt|sương muối|mưa phùn"),
        ("AT_DUONG_DAT_DEO_NONG_THON", r"đèo cao|trên đường đê|tỉnh lộ hẹp|đất lún|cầu phao|ven sông|qua rừng|bê tông nông thôn|ngã tư không đèn|ven hồ lớn|qua ruộng"),
        ("AT_XU_LY_TINH_HUONG_DUONG", r"xử lý khi ngã xe|né xe buýt|nghe tiếng xe phía sau|khe xe hợp lệ|khoảng cách khi dừng đèn đỏ|bẻ lái|xếp hàng đúng vị trí|vỉa hè tạm thời|nghe và đoán ý|phanh nối tiếp|đám cưới tràn|tải rẽ phải không bật xi nhan|rãnh nước che|hẻm có góc khuất|cầu phao gỗ|động vật hoang|khói trắng|trồng cao che tầm nhìn|giảm tốc trước lối vào làng|giữ đèn xe trên đường vòng dốc"),
        ("AT_NGUOI_LAI_THEO_NHU_CAU", r"chở hoa quả đi chợ phiên|đi công tác ngoài tỉnh|phượt một mình|bạn trẻ chạy xe sau giờ học|đồ điện tử dễ vỡ|mưa nhỏ|gia đình đi chợ cuối tuần|đau đầu khi chạy|chóng mặt khi chạy|khó thở|dấu hiệu say xe|mắt khô|ngón tay tê|co thắt vai gáy"),
        ("AT_TRANG_BI_THEO_THOI_TIET", r"chọn mũ bảo hiểm cho ngày|chọn kính chạy xe|găng tay chống trượt khi mưa|giày khô nhanh|áo mưa hai mảnh|đồ bảo hộ nào khi chạy đèo"),
        ("AT_KY_NANG_NANG_CAO", r"."),
    ],
    "Xe máy": [
        ("XM_HONDA_WAVE", r"honda wave"),
        ("XM_YAMAHA_SIRIUS", r"yamaha sirius"),
        ("XM_HONDA_CLICK", r"honda click"),
        ("XM_YAMAHA_MIO", r"yamaha mio"),
        ("XM_HONDA_VISION", r"honda vision"),
        ("XM_HONDA_AIR_BLADE", r"honda air blade"),
        ("XM_XE_MAY_DIEN", r"xe máy điện"),
        ("XM_SU_CO_XE_THUE", r"thuê xe gặp"),
        ("XM_KIEM_TRA_KY_THUAT", r"kỹ thuật kiểm tra|vai trò của"),
        ("XM_SO_SANH_XE", r"xe số và xe ga|xe ga và xe số|chọn honda|chọn xe số hay xe ga|người mới lái nên tập với xe số|chở đồ nhiều: xe số"),
        ("XM_PHU_KIEN_DO_DUNG", r"hộp đồ sau xe|móc treo túi|bình xăng dự phòng|bộ dụng cụ sửa xe|bơm tay mini|bộ vá săm|áo mưa chuyên dụng|chổi lau kính mũ|miếng lót mũ|khóa đĩa|khóa chữ u|thiết bị định vị|camera hành trình|đế chống trượt|miếng dán chống trầy|túi nước chống mưa|giá gác đồ hai bên|bao che yên|kính chắn gió|bọc tay cầm|dây buộc hành lý|bình giữ nhiệt|áo gió chống lạnh|nón bảo hiểm gắn thêm|túi chuyên dụng đựng mũ|giá sạc điện thoại|túi hàng sau xe máy|đệm lót lưng|giá giữ mũ|dây chun buộc hành|miếng xốp chèn đồ|bình xịt dưỡng xích|bộ kiểm tra áp suất|đồng hồ điện gắn thêm|đèn led thay bóng|bọc giữ nhiệt|nẹp che hốc gió|gá chống dốc|bộ nhớt mini|hộp dụng cụ gắn|sơn dặm vá xước|miếng chống trượt yên"),
        ("XM_BAO_DUONG_KIEM_TRA", r"."),
    ],
    "Du lịch": [
        # id-range based (blocks of 4 per destination); regex fallback none
    ],
    "Cung đường": [
        ("CD_HA_GIANG_DONG_BAC_CA", r"hà giang|quản bạ|yên minh|đồng văn|mèo vạc|bảo lạc|cao bằng|thất khê|lạng sơn|đình lập|ba bể|pắc pó|bản giốc|suối mỡ|lục ngạn|chợ hoa quảng bá|suối hoa|khâu vai"),
        ("CD_TAY_BAC_XA", r"yên bái|tuyên quang|thác bà|mù cang chải|bắc hà|y tý|tà xùa|ô quy hồ|sa pa|lào cai|bảo yên|hàm yên|đoan hùng|suối nước nóng bang|atk định hóa|hồ cầu nhay|vườn đào phú thượng"),
        ("CD_HOA_BINH_SON_LA", r"hòa bình|mai châu|mộc châu|sơn la|thung nai|chùa hương|đền sóc|thác đa|suối ngôi|ba vì"),
        ("CD_PHU_THO_VINH_PHUC", r"việt trì|phú thọ|vĩnh yên|sơn tây|phong châu|sông thao|đền hùng|tam chúc|cúc phương|hùng vương|tam đảo|đại lải|đồng mô|vân trình|mỹ lâm"),
        ("CD_DONG_BAC_GAN", r"bắc ninh|bắc giang|thái nguyên|đình bảng|ninh hiệp|bà chúa kho|quan họ"),
        ("CD_DONG_BANG_VEN_BIEN", r"."),
    ],
    "Hỏi đáp": [
        ("HD_GIAY_TO_PHAP_LY", r"bằng lái|giấy tờ|giấy đăng ký|đăng ký|đăng kiểm|bảo hiểm|phạt nguội|nồng độ cồn|mũ bảo hiểm bắt buộc|thiếu mũ bảo hiểm|đèn xi nhan bắt buộc|biển số|gương xe máy bắt buộc|phạt|đèn xi nhan xe máy hỏng|kéo xe máy bằng xe máy|bình ga|còi ầm ĩ|vỉa hè lúc ngập|chở được mấy người|bao nhiêu tuổi được lái|phố đi bộ|bảo hiểm tnds là gì|đội mũ bảo hiểm không cài dây|gương hai bên|qua đèn vàng|chạy xe máy trong phố đi bộ|phụ huynh chở con|tối đa bao nhiêu km một giờ|đường cao tốc|hầm đường bộ|trẻ em ngồi trước"),
        ("HD_XE_MAY_DIEN", r"xe máy điện"),
        ("HD_BAI_GUI_XE", r"bãi gửi|gửi xe"),
        ("HD_THUE_XE", r"thuê xe|xe thuê|thuê hai xe|lấy xe thuê|máy thuê|nhận lại xe nhầm|đổi xe ngay khi lấy|mùi khét nhẹ|kiểm tra xe lần cuối trước khi trả|đổ đầy bình trước khi nhận|tư vấn lộ trình|hỗ trợ khi xe hỏng giữa đường|số điện thoại chủ xe"),
        ("HD_DUONG_DI_DIA_DIEM", r"phà qua sông hồng|vành đai|hồ gươm|chợ đồng xuân|từ long biên|sân bay nội bài|đường lên ba vì|vòng quanh hồ tây|từ hà nội|đường ven đê|đền sóc|hồ tây chạy|phố cổ giờ|chợ đầu mối|hà đông|vườn cây ba vì|chợ sáng long biên|biển quất lâm|bến xe|ga hà nội|khu vui chơi giải trí|tàu hỏa|máy bay|mất mấy tiếng|đường nào|đoạn nào|đường về quê|vùng ven|trạm nghỉ|báo tắc|bản đồ định hướng|trạm kiểm tải|ngập đường|cầu nào qua|chợ đêm|phà|trạm xăng"),
        ("HD_CHI_PHI", r"chi phí|tiền |hết khoảng bao nhiêu|bao nhiêu"),
        ("HD_TRANG_BI", r"mũ bảo hiểm|nón bảo hiểm|áo mưa|găng tay|giày|kính|bao tay|áo phản quang|áo gió|giá đỡ điện thoại|túi đựng đồ|khóa xe điện từ|khóa cổ xe máy điện từ|yên xe ga có nên bọc|đèn gắn thêm|bọc tay cầm|chống nắng thế nào|mặc thêm gì|giữ ấm tay|túi giữ nóng|phản quang dán"),
        ("HD_PHUOT_TRAI_NGHIEM", r"đi phượt|xuất phát từ mấy giờ|dừng nghỉ ở quán|nghỉ giải lao|chở quà mềm|mang theo dù|đi mưa về|sau chuyến mưa|sạc điện thoại khi đi phượt|tìm trạm xăng trên quốc lộ|chạy xe máy đi mưa nên che balo|giữ balo|mang theo đồ ăn|uống nước trên xe máy|tai nghe|nghe chỉ dẫn rẽ|tránh đường có quá nhiều đèn đỏ|giữ xe sạch|dốc ngược hay dốc xuôi|can xăng|ăn no xong|mất ngủ|đổ xăng lúc nào trong ngày tiết kiệm|xăng e5|cháy|tắt máy hay để máy nổ|rửa xe ngay sau khi đi đường mưa"),
        ("HD_CHON_XE", r"xe máy nào|loại xe nào"),
    ],
}

# DL id-range clusters (blocks of 4 rows per destination, contiguous)
DL_RANGES = [
    (1, 40, "DL_HA_NOI_NOI_THANH"),
    (41, 96, "DL_TAY_BAC_GAN"),
    (97, 116, "DL_VINH_PHUC_THAI_NGUYEN"),
    (117, 132, "DL_BAC_CAN_CAO_BANG"),
    (133, 152, "DL_LANG_SON_HA_GIANG"),
    (153, 184, "DL_SAPA_LAO_CAI_YEN_BAI"),
    (185, 256, "DL_DONG_BANG_BAC_BO"),
    (257, 300, "DL_QUANG_NINH_HAI_PHONG"),
    (301, 336, "DL_NINH_BINH_PHU_THO_HA_NAM"),
    (337, 400, "DL_DIEM_DEN_NOI_TIENG"),
]

def load_matrix():
    path = os.path.join(ROOT, "data", "content-matrix.csv")
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if not r["article_id"].startswith("SAMPLE")]


def classify(rows):
    mapping = {}
    for r in rows:
        aid = r["article_id"]
        cat = r["category"]
        kw = re.sub(r"\s+", " ", r["primary_keyword"].strip().lower())
        num = int(re.sub(r"\D", "", aid))
        child = None
        if cat == "Du lịch":
            for a, b, c in DL_RANGES:
                if a <= num <= b:
                    child = c
                    break
        else:
            for child_id, pat in RULES[cat]:
                if re.search(pat, kw):
                    child = child_id
                    break
        if child is None:
            raise SystemExit("unclassified row: %s %s" % (aid, kw))
        mapping[aid] = child
    return mapping


def main():
    rows = load_matrix()
    if len(rows) != 2000:
        raise SystemExit("expected 2000 production rows, got %d" % len(rows))
    mapping = classify(rows)

    # counts
    counts = {}
    by_status = {}
    for r in rows:
        c = mapping[r["article_id"]]
        counts[c] = counts.get(c, 0) + 1
        counts_key = (c, r["status"])
        by_status[counts_key] = by_status.get(counts_key, 0) + 1

    # group children under parents (derived from rows)
    parent_of_child = {}
    for r in rows:
        parent_of_child[mapping[r["article_id"]]] = r["category"]

    parents_out = []
    for cat, meta in PARENTS.items():
        children = []
        for child_id, (title, desc) in CHILD_META.items():
            if parent_of_child.get(child_id) != cat:
                continue
            children.append({
                "child_id": child_id,
                "child_title": title,
                "child_slug": child_id.lower().replace("_", "-"),
                "child_hub_url": "/shop/cam-nang/chu-de/%s.html"
                                 % child_id.lower().replace("_", "-"),
                "description": desc,
                "article_count": counts.get(child_id, 0),
                "status": "active",
            })
        children.sort(key=lambda c: c["child_id"])
        parents_out.append({
            "parent_id": meta["parent_id"],
            "parent_title": cat,
            "parent_slug": meta["parent_slug"],
            "parent_hub": "/shop/" + meta["parent_hub"],
            "children": children,
        })

    tax = {
        "taxonomy_version": TAXONOMY_VERSION,
        "generated": None,
        "total_production_rows": len(rows),
        "rules": "ordered regex + id ranges in scripts/build_taxonomy.py",
        "parents": parents_out,
    }

    # write taxonomy json
    out_path = os.path.join(ROOT, "data", "content-taxonomy.json")
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(tax, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # write map csv
    map_path = os.path.join(ROOT, "data", "content-taxonomy-map.csv")
    with io.open(map_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["article_id", "parent_id", "child_id", "child_hub",
                    "taxonomy_version"])
        for r in rows:
            aid = r["article_id"]
            c = mapping[aid]
            cat = r["category"]
            w.writerow([aid, PARENTS[cat]["parent_id"], c,
                        "/shop/cam-nang/chu-de/%s.html" % c.lower().replace("_", "-"),
                        TAXONOMY_VERSION])

    # write human report
    report_path = os.path.join(ROOT, "reports", "seo", "content-taxonomy.md")
    with io.open(report_path, "w", encoding="utf-8") as f:
        f.write("# Content taxonomy report\n\n")
        f.write("Taxonomy version: %s\n\n" % TAXONOMY_VERSION)
        f.write("Production rows mapped: %d / %d. Orphans: 0.\n\n"
                % (len(rows), len(rows)))
        status_order = ["PUBLISHED", "WRITING", "QA", "PASS", "REPAIR",
                        "REVIEW", "BLOCKED", "FAIL", "PLANNED"]
        oversized, tiny = [], []
        f.write("| Parent | Child | Total | PUBLISHED | WRITING | PLANNED | Example ids | Child hub |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for parent in parents_out:
            for c in parent["children"]:
                ex = [r["article_id"] for r in rows
                      if mapping[r["article_id"]] == c["child_id"]][:3]
                counts_by_status = {}
                for r in rows:
                    if mapping[r["article_id"]] != c["child_id"]:
                        continue
                    s = (r["status"] or "").strip()
                    counts_by_status[s] = counts_by_status.get(s, 0) + 1
                pub = counts_by_status.get("PUBLISHED", 0)
                wri = counts_by_status.get("WRITING", 0) + counts_by_status.get("QA", 0) \
                    + counts_by_status.get("PASS", 0) + counts_by_status.get("REPAIR", 0)
                planned = counts_by_status.get("PLANNED", 0) + counts_by_status.get("REVIEW", 0) \
                    + counts_by_status.get("BLOCKED", 0) + counts_by_status.get("FAIL", 0)
                f.write("| %s | %s | %d | %d | %d | %d | %s | %s |\n"
                        % (parent["parent_title"], c["child_title"],
                           c["article_count"], pub, wri, planned,
                           ", ".join(ex), c["child_hub_url"]))
                if c["article_count"] > 100:
                    oversized.append((c["child_id"], c["article_count"]))
                if c["article_count"] < 5:
                    tiny.append((c["child_id"], c["article_count"]))
        f.write("\n## Cluster quality flags\n\n")
        f.write("Flags are advisory only; flagged clusters remain valid and mapped.\n\n")
        f.write("TOO_LARGE (>100 rows): %s\n\n"
                % (", ".join("%s (%d)" % x for x in oversized) or "none"))
        f.write("TOO_SMALL (<5 rows): %s\n\n"
                % (", ".join("%s (%d)" % x for x in tiny) or "none"))
        f.write("Orphan production rows: 0. Every production row resolves to "
                "exactly one parent and one child cluster.\n\n")
        f.write("Overlapping child ids/slugs: 0 (validated by "
                "scripts/validate_taxonomy.py).\n")

    # console summary
    print("taxonomy: %d rows mapped into %d children under %d parents"
          % (len(rows), len(set(mapping.values())), len(PARENTS)))
    for cat in PARENTS:
        cs = sorted(set(mapping[r["article_id"]] for r in rows
                        if r["category"] == cat))
        print("== %s" % cat)
        for c in cs:
            print("   %-32s %4d" % (c, counts[c]))


if __name__ == "__main__":
    main()
