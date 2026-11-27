(function (global) {
    "use strict";

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatTime(value, options) {
        var opts = typeof options === "boolean"
            ? { includeWeekday: options }
            : (options && typeof options === "object" ? options : {});
        var fallback = Object.prototype.hasOwnProperty.call(opts, "fallback") ? opts.fallback : "-";
        if (value === undefined || value === null || value === "") {
            return fallback;
        }
        var dateValue = value;
        if (typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value))) {
            var numeric = Number(value);
            if (!Number.isFinite(numeric) || numeric === 0) {
                return fallback;
            }
            dateValue = numeric > 100000000000 ? numeric : numeric * 1000;
        }
        var date = new Date(dateValue);
        if (Number.isNaN(date.getTime())) {
            return fallback === "-" ? String(value) : fallback;
        }
        if (opts.includeWeekday || opts.localeOptions) {
            var localeOptions = opts.localeOptions || {
                hour12: false,
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit"
            };
            if (opts.includeWeekday) {
                localeOptions = Object.assign({}, localeOptions, { weekday: "short" });
            }
            return date.toLocaleString(opts.locale || "zh-CN", localeOptions);
        }
        return date.toLocaleString();
    }

    async function fetchJson(url, options) {
        var fetchOptions = Object.assign({ cache: "no-store" }, options || {});
        var response = await fetch(url, fetchOptions);
        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }
        return response.json();
    }

    var api = {
        escapeHtml: escapeHtml,
        formatTime: formatTime,
        fetchJson: fetchJson
    };

    if (global) {
        global.JjcCommon = api;
    }
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
})(typeof window !== "undefined" ? window : globalThis);
