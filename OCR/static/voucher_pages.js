/*
 * Print layout for vouchers that carry On Duty rows. Shared by voucher_draft,
 * cash_voucher_entry and ia_authentication.
 *
 * The previews copy the whole voucher per three On Duty rows. Three long rows
 * can be taller than an A4 sheet, which pushes the signature strip onto a page
 * of its own. packVoucherPages() re-splits the rows by measured height so every
 * page (full voucher, signatures included) fits one sheet, and gives the On Duty
 * table the full width of its cell.
 *
 * packVoucherPages(root, widthCss, boxCss)
 *   root      element holding the voucher copy/copies to print (replaced in place)
 *   widthCss  width available to the voucher box when printed, default 190mm
 *   boxCss    only for a page that prints in place (ia_authentication), whose print-only
 *             box rules do not apply on screen: the box style to measure with
 */
(function () {
    const SCOPE = "voucher-print-scope";
    const MAX_ROWS = 3;                         // On Duty rows per page, at most
    const PAGE_PX = 277 / 25.4 * 96 - 40;       // A4 less 2 x 10mm @page margin, 40px slack

    const CSS = `
        .${SCOPE} .voucher-page { break-after: page; page-break-after: always; break-inside: avoid; page-break-inside: avoid; }
        .${SCOPE} .voucher-page:last-child { break-after: auto; page-break-after: auto; }
        /* On Duty: label above, table across the whole row instead of the narrow value column */
        .${SCOPE} .preview-on-duty-row { display: block !important; }
        .${SCOPE} .preview-on-duty-row > .print-label { border: 0 !important; padding-bottom: 2px !important; }
        .${SCOPE} .preview-on-duty-row > .print-value { display: block !important; border: 0 !important; padding: 4px var(--onduty-pad, 4mm) 8px !important; }
        .${SCOPE} .preview-on-duty-table { width: 100% !important; table-layout: auto !important; }
        .${SCOPE} .preview-on-duty-table th { width: auto !important; }
        .${SCOPE} .preview-on-duty-table td { white-space: pre-wrap !important; }
        .${SCOPE} .preview-on-duty-table td:nth-child(n+2):nth-child(-n+4) { white-space: nowrap !important; }
        /* pre-wrap cells print the template whitespace around a table as blank lines */
        .${SCOPE} .preview-details-row .print-value,
        .${SCOPE} .preview-on-duty-row .print-value { white-space: normal !important; }
    `;

    window.packVoucherPages = function (root, widthCss, boxCss) {
        let host = null;

        try {
            const doc = root.ownerDocument;
            const onDutyRows = Array.from(root.querySelectorAll(".preview-on-duty-row"));
            const rows = onDutyRows.flatMap(function (box) {
                return Array.from(box.querySelectorAll("tbody tr"));
            });

            if (!rows.length) return;

            if (!doc.getElementById("voucherPrintCss")) {
                const style = doc.createElement("style");
                style.id = "voucherPrintCss";
                style.textContent = CSS;
                doc.head.appendChild(style);
            }

            // Measure one copy holding every row, off-screen, at print width.
            const template = onDutyRows[0].closest(".print-box, .preview-box");
            const probe = template.cloneNode(true);
            probe.style.cssText += ";" + (boxCss || "");
            probe.querySelector(".preview-on-duty-row tbody").replaceChildren(
                ...rows.map(function (row) { return row.cloneNode(true); })
            );

            host = doc.createElement("div");
            host.className = SCOPE;
            host.style.cssText = "position:absolute;left:-99999px;top:0;width:" + (widthCss || "190mm");
            host.appendChild(probe);
            doc.body.appendChild(host);

            // Inset the table like the "ON DUTY" label so both line up in every template.
            const inset = doc.defaultView.getComputedStyle(
                probe.querySelector(".preview-on-duty-row > .print-label")
            ).paddingLeft;
            host.style.setProperty("--onduty-pad", inset);

            const heights = Array.from(
                probe.querySelectorAll(".preview-on-duty-row tbody tr"),
                function (row) { return row.getBoundingClientRect().height; }
            );
            const fixed = probe.getBoundingClientRect().height - heights.reduce(function (a, b) { return a + b; }, 0);

            // Fill each page until it holds MAX_ROWS rows or the next row would not fit.
            const groups = [];
            let current = [];
            let used = fixed;

            rows.forEach(function (row, i) {
                if (current.length && (current.length === MAX_ROWS || used + heights[i] > PAGE_PX)) {
                    groups.push({ rows: current, height: used });
                    current = [];
                    used = fixed;
                }
                current.push(row);
                used += heights[i];
            });
            groups.push({ rows: current, height: used });

            const pages = doc.createElement("div");
            pages.className = "voucher-pages";

            groups.forEach(function (group) {
                const page = template.cloneNode(true);
                page.classList.add("voucher-page");
                page.querySelector(".preview-on-duty-row tbody").replaceChildren(
                    ...group.rows.map(function (row) { return row.cloneNode(true); })
                );
                // One row taller than a page can't be split further: shrink that page a little
                // rather than let its signature strip fall onto a sheet of its own.
                if (group.height > PAGE_PX) page.style.zoom = (PAGE_PX / group.height).toFixed(3);
                pages.appendChild(page);
            });

            // Only now touch the print content, so a failure above leaves it as it was.
            root.classList.add(SCOPE);
            root.style.setProperty("--onduty-pad", inset);
            root.replaceChildren(pages);
        } catch (error) {
            console.error("packVoucherPages failed, printing the voucher as is:", error);
        } finally {
            if (host) host.remove();
        }
    };
})();
