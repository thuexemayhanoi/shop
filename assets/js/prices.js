/* MotoTusPrices — Single source of truth for Mr Tú Motorbike Rental pricing (owner-approved).
   Daily/weekly/monthly prices in VND. Unknown models: contact shop. */
(function () {
    'use strict';

    var PACKAGES = {
        150000: { week: 700000, monthMin: 900000, monthMax: 1200000 },
        200000: { week: 1000000, monthMin: 1500000, monthMax: 2000000 }
    };

    function fmt(n) {
        return n.toLocaleString('vi-VN') + 'đ';
    }

    /* Estimate total for `days` at `daily` base price, using weekly/monthly packages when cheaper. */
    function calcEstimate(days, daily) {
        days = Math.max(1, parseInt(days, 10) || 1);
        daily = parseInt(daily, 10) || 0;
        if (daily === 0) return 'Liên hệ để xác nhận giá hiện tại';

        var pkg = PACKAGES[daily];
        if (!pkg) return fmt(daily * days);

        if (days < 7) return fmt(daily * days);

        if (days < 28) {
            var weeks = Math.floor(days / 7);
            var extra = days - weeks * 7;
            var byDay = daily * days;
            var byPkg = weeks * pkg.week + extra * daily;
            return fmt(byPkg < byDay ? byPkg : byDay) + ' (ước tính)';
        }

        var months = Math.floor(days / 30);
        var remDays = days - months * 30;
        var min = months * pkg.monthMin + remDays * daily;
        var max = months * pkg.monthMax + remDays * daily;
        if (min === max) return fmt(min);
        return fmt(min).replace('đ', '') + ' - ' + fmt(max) + ' (ước tính, tùy dòng xe)';
    }

    window.MotoTusPrices = {
        CONTACT_PRICE: 'Liên hệ để xác nhận giá hiện tại',
        PACKAGES: PACKAGES,
        calcEstimate: calcEstimate
    };
})();
