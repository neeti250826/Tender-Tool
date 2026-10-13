"""Print '<rows> <oldest publication date dd/mm/yyyy>' for an eSupply export."""
import sys, warnings
warnings.filterwarnings("ignore")
import openpyxl
ws = openpyxl.load_workbook(sys.argv[1]).worksheets[0]
rows = list(ws.iter_rows(values_only=True))
h = next((i for i, r in enumerate(rows) if r and r[0] == "Project Code"), None)
if h is None:
    print("0 None"); sys.exit()
H = list(rows[h]); pi = H.index("Publication Date")
ds = [r[pi] for r in rows[h + 1:] if r and r[pi] and hasattr(r[pi], "year")]
print(len(ds), min(ds).strftime("%d/%m/%Y") if ds else "None")
