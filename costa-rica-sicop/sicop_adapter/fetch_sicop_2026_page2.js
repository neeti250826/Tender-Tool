async (page) => {
  return await page.evaluate(async () => {
    const url = 'https://prod-api.sicop.go.cr/pcont/api/v1/public/ceContractsReport/listPage';
    const body = {
      pageNumber: 1,
      pageSize: 10000,
      tableSorter: { sorter: '', order: 'desc' },
      tableFilters: [],
      formFilters: [
        { field: 'instRegNo', value: '4000042147' },
        { field: 'startDt', value: '2025-12-31T18:30:00.000Z' },
        { field: 'endDt', value: '2026-09-29T18:29:59.999Z' },
      ],
    };
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: response.status, request: body, payload: await response.json() };
  });
}
