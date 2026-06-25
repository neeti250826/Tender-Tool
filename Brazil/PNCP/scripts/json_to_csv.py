import json
import re
import pandas as pd

input_file = "pncp_notice_items_checkpoint_backup_reagente_hematologia.json"
output_file = "pncp_notice_items_checkpoint_backup_reagente_hematologia.xlsx"

# Remove illegal Excel characters
ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]")

def clean_for_excel(value):
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value

# Load JSON
with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# Extract rows
rows = data.get("rows", [])

# Create DataFrame
df = pd.DataFrame(rows)

# Clean all cells
df = df.apply(lambda col: col.map(clean_for_excel))

# Save to Excel
df.to_excel(output_file, index=False)

print(f"Done! Excel file saved as: {output_file}")
print(f"Rows exported: {len(df)}")