async (page) => {
  const start = process.env.SICOP_START;
  const end = process.env.SICOP_END;
  if (!start || !end) throw new Error("SICOP_START and SICOP_END are required");
  return await page.evaluate(async ({ start, end }) => {
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
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      }
    );
    return await response.json();
  }, { start, end });
}
