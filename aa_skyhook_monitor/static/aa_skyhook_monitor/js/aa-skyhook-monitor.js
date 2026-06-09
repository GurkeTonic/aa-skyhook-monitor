/* AA Skyhook Monitor */

(function () {
    "use strict";

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    function updateCountdowns() {
        document.querySelectorAll(".vuln-countdown").forEach(function (el) {
            var vulnStart = new Date(el.dataset.vuln);
            var vulnEnd = el.dataset.vulnEnd ? new Date(el.dataset.vulnEnd) : null;
            var now = new Date();
            var diffStart = vulnStart - now;
            var diffEnd = vulnEnd ? vulnEnd - now : null;

            var eveTime = vulnStart.toISOString().substring(11, 16);

            if (diffStart <= 0) {
                if (diffEnd !== null && diffEnd <= 0) {
                    el.innerHTML = '<small class="text-muted">abgelaufen</small>';
                    return;
                }
                el.innerHTML =
                    '<span class="badge bg-danger">Läuft</span>' +
                    '<small class="text-muted d-block">EVE ' +
                    eveTime +
                    "</small>";
                return;
            }

            var localDate = vulnStart.toLocaleDateString([], {
                day: "2-digit",
                month: "2-digit",
            });
            var localTime = vulnStart.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
            });

            var totalSec = Math.floor(diffStart / 1000);
            var h = Math.floor(totalSec / 3600);
            var m = Math.floor((totalSec % 3600) / 60);
            var s = totalSec % 60;
            var countdown = (h > 0 ? pad(h) + ":" : "") + pad(m) + ":" + pad(s);

            el.innerHTML =
                '<div class="d-flex justify-content-center gap-3">' +
                '<small class="text-muted">EVE ' +
                eveTime +
                "</small>" +
                "<small>" +
                localDate +
                " " +
                localTime +
                "</small>" +
                "</div>" +
                '<div class="text-warning" style="font-variant-numeric:tabular-nums;letter-spacing:.04em">' +
                countdown +
                "</div>";
        });
    }

    updateCountdowns();
    setInterval(updateCountdowns, 1000);
    setTimeout(function () {
        location.reload();
    }, 5 * 60 * 1000);
})();
