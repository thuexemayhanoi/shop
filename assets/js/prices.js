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

    /* Cost of one combination: months monthly blocks + weeks weekly blocks + leftover days.
       Uses min/max monthly price when the model has a monthly range. Returns {min, max}. */
    function combo(m, days, months, weeks) {
        var rest = days - months * 30 - weeks * 7;
        var min = months * m.monthMin + weeks * m.week + rest * m.daily;
        var max = months * m.monthMax + weeks * m.week + rest * m.daily;
        return { min: min, max: max };
    }

    /* Estimate total for `days` rental of model `key` (see MODELS).
       Chooses the cheapest valid combination of monthly (30d blocks), weekly (7d blocks)
       and daily rates for leftover days. Unknown keys -> contact-shop message. */
    function calcEstimate(days, key) {
        days = Math.max(1, parseInt(days, 10) || 1);
        var m = MODELS[String(key || '').toLowerCase()];
        if (!m) return CONTACT;

        var maxMonths = Math.floor(days / 30);
        var best = null;

        for (var mo = 0; mo <= maxMonths; mo++) {
            var restAfterMonths = days - mo * 30;
            var maxWeeks = Math.floor(restAfterMonths / 7);
            for (var wk = 0; wk <= maxWeeks; wk++) {
                var c = combo(m, days, mo, wk);
                if (!best || c.min < best.min) best = c;
            }
        }

        if (best.min === best.max) return fmt(best.min) + ' (ước tính)';
        return fmt(best.min).replace('đ', '') + ' - ' + fmt(best.max) + ' (ước tính, tùy dòng xe)';
    }

    window.MotoTusPrices = {
        CONTACT_PRICE: CONTACT,
        MODELS: MODELS,
        calcEstimate: calcEstimate
    };
})();
