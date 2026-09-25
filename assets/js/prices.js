/* MotoTusPrices — Model-based source of truth for Mr Tú Motorbike Rental pricing (owner-approved).
   Prices in VND. Models without an approved price (50cc, Lead, Janus, Attila, NVX, SH, côn/PKL...):
   contact shop to confirm current price. */
(function () {
    'use strict';

    var CONTACT = 'Liên hệ để xác nhận giá hiện tại';

    var MODELS = {
        wave:     { name: 'Honda Wave',       daily: 150000, week: 700000,  monthMin: 900000,  monthMax: 1200000 },
        sirius:   { name: 'Yamaha Sirius',    daily: 150000, week: 700000,  monthMin: 900000,  monthMax: 1200000 },
        click:    { name: 'Honda Click',      daily: 150000, week: 700000,  monthMin: 900000,  monthMax: 1200000 },
        mio:      { name: 'Yamaha Mio',       daily: 150000, week: 700000,  monthMin: 900000,  monthMax: 1200000 },
        vision:   { name: 'Honda Vision',     daily: 200000, week: 1000000, monthMin: 1800000, monthMax: 2000000 },
        airblade: { name: 'Honda Air Blade',  daily: 200000, week: 1000000, monthMin: 1500000, monthMax: 1500000 },
        ebike:    { name: 'Xe điện',          daily: 200000, week: 1000000, monthMin: 1500000, monthMax: 1500000 }
    };

    function fmt(n) {
        return n.toLocaleString('vi-VN') + 'đ';
    }

    /* Estimate total for `days` rental of model `key` (see MODELS).
       Unknown keys -> contact-shop message. */
    function calcEstimate(days, key) {
        days = Math.max(1, parseInt(days, 10) || 1);
        var m = MODELS[String(key || '').toLowerCase()];
        if (!m) return CONTACT;

        if (days < 7) return fmt(m.daily * days);

        if (days < 28) {
            var weeks = Math.floor(days / 7);
            var extra = days - weeks * 7;
            var byDay = m.daily * days;
            var byPkg = weeks * m.week + extra * m.daily;
            return fmt(byPkg < byDay ? byPkg : byDay) + ' (ước tính)';
        }

        var months = Math.floor(days / 30);
        var remDays = days - months * 30;
        var min = months * m.monthMin + remDays * m.daily;
        var max = months * m.monthMax + remDays * m.daily;
        if (min === max) return fmt(min) + ' (ước tính)';
        return fmt(min).replace('đ', '') + ' - ' + fmt(max) + ' (ước tính, tùy dòng xe)';
    }

    window.MotoTusPrices = {
        CONTACT_PRICE: CONTACT,
        MODELS: MODELS,
        calcEstimate: calcEstimate
    };
})();
