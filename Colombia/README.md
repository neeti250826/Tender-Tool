# Colombia Tender Documentation

The SECOP II extractor is available at [colombia-secop/extract.py](../colombia-secop/extract.py). The 2026-10-13 audit recovered this source from the organization repository and added explicit date and output arguments.

## Available Evidence

Recovered local output filename: `SECOP_II_-_Contratos_Electrónicos_20260415.csv`. The file is very large and was not copied into git.

## Run Command

```powershell
python colombia-secop/extract.py --date-from 2024-01-01 --date-to 2026-10-13 --output-dir Colombia/output
```

The default end date is today. The source filters contract signature dates; these should not be represented as independently verified publication dates.

## AI Prompt

```text
Run colombia-secop/extract.py for the requested date range and review source dates, procurement status, pagination and field coverage before using its results.
```

## Documentation

- `docs/colombia_secop_documentation.html`

