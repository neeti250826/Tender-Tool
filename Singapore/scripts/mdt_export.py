from pathlib import Path
import pandas as pd

def save_mdt_outputs(df: pd.DataFrame, output_prefix) -> dict:
    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    csv_path = output_prefix.with_suffix(".csv")
    json_path = output_prefix.with_suffix(".json")

    if df is None:
        df = pd.DataFrame()

    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records", force_ascii=False, indent=2)

    return {
        "csv_path": str(csv_path),
        "json_path": str(json_path),
    }