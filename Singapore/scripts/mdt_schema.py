import pandas as pd

def to_mdt_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Minimal passthrough converter.
    Replace with real MDT column mapping later if needed.
    """
    if df is None:
        return pd.DataFrame()
    return df.copy()