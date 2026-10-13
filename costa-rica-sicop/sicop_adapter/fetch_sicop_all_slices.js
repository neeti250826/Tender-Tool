async (page) => {
  const slices = [
    ["2019", "2018-12-31T18:30:00.000Z", "2019-12-31T18:30:00.000Z"],
    ["2020", "2019-12-31T18:30:00.000Z", "2020-12-31T18:30:00.000Z"],
    ["2021", "2020-12-31T18:30:00.000Z", "2021-12-31T18:30:00.000Z"],
    ["2022", "2021-12-31T18:30:00.000Z", "2022-12-31T18:30:00.000Z"],
    ["2023", "2022-12-31T18:30:00.000Z", "2023-12-31T18:30:00.000Z"],
    ["2024", "2023-12-31T18:30:00.000Z", "2024-12-31T18:30:00.000Z"],
    ["2025", "2024-12-31T18:30:00.000Z", "2025-12-31T18:30:00.000Z"],
    ["2026_ytd", "2025-12-31T18:30:00.000Z", "2026-09-29T18:29:59.999Z"]
  ];
  return await page.evaluate(async (slices) => {
    const results = [];
    for (const [label, start, end] of slices) {
      const body = {
        pageNumber: 0,
        pageSize: 10000,
        tableSorter: { sorter: "", order: "desc" },
        tableFilters: [],
        formFilters: [
          { field: "instRegNo", value: "4000042147" },
          { field: "startDt", value: start },
          { field: "endDt", value: end }
        ]
      };
      const response = await fetch(
        "https://prod-api.sicop.go.cr/pcont/api/v1/public/ceContractsReport/listPage",
        { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
      );
      results.push({ label, start, end, status: response.status, payload: await response.json() });
    }
    return { institution: "4000042147", slices: results };
  }, slices);
}
