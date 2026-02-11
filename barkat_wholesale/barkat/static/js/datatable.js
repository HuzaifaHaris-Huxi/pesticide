document.addEventListener("DOMContentLoaded", function () {
  // Sanity: make sure DT is loaded
  if (typeof DataTable === "undefined") {
    console.error("DataTables JS not loaded");
    return;
  }

  feather.replace();

  const dt = new DataTable("#customers-table", {
    searching: true,
    paging: true,
    info: true,
    responsive: true,
    lengthChange: true,
    pageLength: 10,
    lengthMenu: [5, 10, 25, 50],
    order: [[0, "asc"]],
    // Classic DOM layout: length + filter on top, table, then info + pager
    dom: '<"dt-head flex items-center justify-between mb-3"lf>rt<"dt-foot flex items-center justify-between mt-3"ip>',
    language: {
      lengthMenu: "_MENU_ per page",
      info: "Showing _START_–_END_ of _TOTAL_",
      infoEmpty: "No customers",
      search: "", // hide default label
    },
  });

  // Add placeholder to the generated filter input
  const wrapper = document.querySelector("#customers-table_wrapper");
  const searchInput = wrapper?.querySelector(".dataTables_filter input");
  if (searchInput) searchInput.placeholder = "Search customers…";

  // Re-apply feather icons after redraws (pagination, search, etc.)
  dt.on("draw", () => feather.replace());
});
