/* ============================================================
   CANONICAL SITE NAVIGATION DATA — single source for the menu
   used by assets/js/app.js, app-info.js, app-rental.js and the
   inline homepage renderer. All four consume window.SITE_NAV so
   the parent/child taxonomy hierarchy cannot drift between them.
   Loaded BEFORE the app renderer scripts on every page.
   ============================================================ */
(function () {
    'use strict';

    var I = {
        home: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>',
        doc: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>',
        map: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>',
        tag: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>',
        mail: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>'
    };

    window.SITE_NAV = {
        /* Cẩm nang sub MUST mirror the 6 canonical parent hubs in
           data/content-taxonomy.json plus the topic index. */
        MENU: [
            { t: "Trang chủ", l: "./", i: I.home },
            { t: "Giới thiệu", l: "gioithieu.html", i: I.doc },
            {
                t: "Dịch vụ", l: "#", i: I.tag,
                sub: [
                    { t: "Bảng giá", l: "banggia.html", i: I.tag },
                    { t: "Thuê xe theo ngày", l: "ngay.html", i: I.doc },
                    { t: "Thuê xe theo tuần", l: "tuan.html", i: I.doc },
                    { t: "Thuê xe theo tháng", l: "thang.html", i: I.doc },
                    { t: "Thủ tục thuê xe", l: "thutuc.html", i: I.doc },
                    { t: "Khuyến mãi", l: "uudai.html", i: I.tag },
                    { t: "Mạng xã hội", l: "mangxahoi.html", i: I.tag }
                ]
            },
            {
                t: "Địa điểm", l: "#", i: I.map,
                sub: [
                    { t: "Hoàn Kiếm", l: "hoankiem.html", i: I.map },
                    { t: "Phố Cổ", l: "phoco.html", i: I.map },
                    { t: "Tây Hồ", l: "tayho.html", i: I.map },
                    { t: "Ba Đình", l: "badinh.html", i: I.map },
                    { t: "Cầu Giấy", l: "caugiay.html", i: I.map },
                    { t: "Đống Đa", l: "dongda.html", i: I.map },
                    { t: "Thanh Xuân", l: "thanhxuan.html", i: I.map },
                    { t: "Hai Bà Trưng", l: "haibatrung.html", i: I.map },
                    { t: "Long Biên", l: "longbien.html", i: I.map },
                    { t: "Ga Hà Nội", l: "gahn.html", i: I.map }
                ]
            },
            {
                t: "Cẩm nang", l: "#", i: I.doc,
                sub: [
                    { t: "Kinh nghiệm", l: "kinhnghiem.html", i: I.doc },
                    { t: "An toàn", l: "antoan.html", i: I.doc },
                    { t: "Xe máy", l: "xemay.html", i: I.doc },
                    { t: "Du lịch", l: "dulich.html", i: I.doc },
                    { t: "Cung đường", l: "cungduong.html", i: I.doc },
                    { t: "Hỏi đáp", l: "hoidap.html", i: I.doc },
                    { t: "Tất cả chủ đề", l: "cam-nang/chu-de/", i: I.doc }
                ]
            },
            { t: "FAQ", l: "faq.html", i: I.doc },
            {
                t: "Chính sách", l: "#", i: I.doc,
                sub: [
                    { t: "Chính sách bảo mật", l: "chinhsach.html", i: I.doc },
                    { t: "Điều khoản sử dụng", l: "dieukhoan.html", i: I.doc }
                ]
            },
            { t: "Liên hệ", l: "lienhe.html", i: I.mail }
        ]
    };
})();
