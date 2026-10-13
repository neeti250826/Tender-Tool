import argparse
from pathlib import Path

import requests
import pandas as pd
import re
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta


BASE_URL = "https://www.datos.gov.co/resource/jbjy-vk9h.json"
APP_TOKEN = None  # optional, recommended for stability

START_DATE = "2024-01-01"
END_DATE = datetime.now().date().isoformat()

SELECT_COLUMNS = [
    "id_contrato",
    "proceso_de_compra",
    "referencia_del_contrato",
    "nombre_entidad",
    "nit_entidad",
    "departamento",
    "ciudad",
    "descripcion_del_proceso",
    "objeto_del_contrato",
    "proveedor_adjudicado",
    "documento_proveedor",
    "valor_del_contrato",
    "estado_contrato",
    "modalidad_de_contratacion",
    "codigo_de_categoria_principal",
    "fecha_de_firma",
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
    "urlproceso"
]

KEYWORDS = [
    "reactivo", "reactivos", "reactivo laboratorio", "reactivos laboratorio",
    "química clínica", "quimica clinica", "bioquímica clínica", "bioquimica clinica",
    "hematología", "hematologia", "hemograma", "analizador hematológico", "analizador hematologico",
    "inmunología", "inmunologia", "reactivo inmunológico", "reactivo inmunologico",
    "serología", "serologia", "elisa", "inmunoensayo",
    "pcr", "diagnóstico molecular", "diagnostico molecular", "biología molecular", "biologia molecular",
    "kit pcr", "reactivo pcr", "extracción adn", "extraccion adn", "extracción arn", "extraccion arn",
    "microbiología", "microbiologia", "medios de cultivo", "cultivo microbiológico", "cultivo microbiologico",
    "bacteriología", "bacteriologia", "antibiograma",
    "banco de sangre", "pruebas transfusionales", "tipificación sanguínea", "tipificacion sanguinea",
    "compatibilidad sanguínea", "compatibilidad sanguinea",
    "diagnóstico in vitro", "diagnostico in vitro", "ivd",
    "equipo laboratorio", "equipos laboratorio", "equipo biomédico", "equipo biomedico",
    "equipos biomédicos", "equipos biomedicos", "analizador clínico", "analizador clinico",
    "reactivo químico", "reactivo quimico", "reactivos químicos", "reactivos quimicos",
]

KEYWORDS_LOWER = [k.lower() for k in KEYWORDS]


def month_ranges(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    current = start.replace(day=1)
    while current <= end:
        next_month = current + relativedelta(months=1)
        chunk_start = max(start, current)
        chunk_end = min(end, next_month - relativedelta(days=1))
        yield (
            chunk_start.strftime("%Y-%m-%dT00:00:00"),
            chunk_end.strftime("%Y-%m-%dT23:59:59"),
        )
        current = next_month


def flatten_url(value):
    if isinstance(value, dict):
        return value.get("url")
    return None


def text_matches_keywords(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.lower()
    return any(k in t for k in KEYWORDS_LOWER)


def extract_brand_or_manufacturer(text: str):
    if not isinstance(text, str):
        return None

    patterns = [
        r"marca\s*[:\-]?\s*([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./ ]{2,100})",
        r"fabricante\s*[:\-]?\s*([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./ ]{2,100})",
        r"manufacturer\s*[:\-]?\s*([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./ ]{2,100})",
        r"marca\/fabricante\s*[:\-]?\s*([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./ ]{2,100})",
    ]

    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .,:;-")
    return None


def extract_quantity(text: str):
    if not isinstance(text, str):
        return None

    patterns = [
        r'(\d+(?:[\.,]\d+)?)\s*(kit|kits|prueba|pruebas|test|tests|caja|cajas|unidad|unidades|frasco|frascos|bolsa|bolsas|tubo|tubos|ampolla|ampollas)',
        r'cantidad\s*[:\-]?\s*(\d+(?:[\.,]\d+)?)',
        r'cant\.\s*[:\-]?\s*(\d+(?:[\.,]\d+)?)',
    ]

    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def extract_unit(text: str):
    if not isinstance(text, str):
        return None

    units = [
        "kit", "kits", "prueba", "pruebas", "test", "tests",
        "caja", "cajas", "unidad", "unidades", "frasco", "frascos",
        "bolsa", "bolsas", "tubo", "tubos", "ampolla", "ampollas"
    ]

    lower = text.lower()
    for u in units:
        if re.search(rf"\b{re.escape(u)}\b", lower):
            return u
    return None


def normalize_status(status: str):
    if not isinstance(status, str):
        return status

    s = status.strip().lower()
    mapping = {
        "abierto": "Aberto",
        "adjudicado": "Adjudicado",
        "homologado": "Homologado",
        "cancelado": "Cancelado",
        "cerrado": "Cerrado",
        "firmado": "Firmado",
        "terminado": "Terminado",
        "modificado": "Modificado",
        "en ejecución": "En ejecución",
        "en ejecucion": "En ejecución",
        "suspendido": "Suspendido"
    }
    return mapping.get(s, status)


def fetch_window(window_start: str, window_end: str, limit: int = 5000, max_pages: int = 200):
    headers = {}
    if APP_TOKEN:
        headers["X-App-Token"] = APP_TOKEN

    select_sql = ", ".join([f"`{c}`" for c in SELECT_COLUMNS[:-1]]) + ", `urlproceso`"

    all_rows = []
    offset = 0

    for _ in range(max_pages):
        query = f"""
        SELECT {select_sql}
        WHERE `fecha_de_firma` BETWEEN '{window_start}'::floating_timestamp
          AND '{window_end}'::floating_timestamp
        ORDER BY `fecha_de_firma` DESC
        LIMIT {limit}
        OFFSET {offset}
        """
        params = {"$query": " ".join(query.split())}

        try:
            r = requests.get(BASE_URL, params=params, headers=headers, timeout=(20, 60))
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"Failed window {window_start} -> {window_end}, offset={offset}: {e}")
            break

        if not batch:
            break

        all_rows.extend(batch)
        print(f"  {window_start[:10]} to {window_end[:10]} | offset={offset} | got {len(batch)} rows")

        if len(batch) < limit:
            break

        offset += limit
        time.sleep(0.4)

    return all_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract SECOP IVD contracts from the official open dataset")
    parser.add_argument("--date-from", default=START_DATE)
    parser.add_argument("--date-to", default=END_DATE)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args(argv)
    try:
        start = datetime.strptime(args.date_from, "%Y-%m-%d")
        end = datetime.strptime(args.date_to, "%Y-%m-%d")
    except ValueError:
        parser.error("Dates must use YYYY-MM-DD")
    if start > end:
        parser.error("--date-from must not be after --date-to")
    rows = []

    for ws, we in month_ranges(args.date_from, args.date_to):
        print(f"\nFetching {ws[:10]} -> {we[:10]}")
        batch_rows = fetch_window(ws, we, limit=5000)
        rows.extend(batch_rows)
        time.sleep(0.5)

    print(f"\nTotal raw rows: {len(rows)}")

    df = pd.DataFrame(rows)

    if df.empty:
        print("No rows downloaded.")
        return

    df["Link Individual"] = df["urlproceso"].apply(flatten_url) if "urlproceso" in df.columns else None

    df["texto_busqueda"] = (
        df.get("descripcion_del_proceso", "").fillna("").astype(str) + " " +
        df.get("objeto_del_contrato", "").fillna("").astype(str)
    ).str.strip()

    df = df[df["texto_busqueda"].apply(text_matches_keywords)].copy()

    df["valor_del_contrato"] = pd.to_numeric(df.get("valor_del_contrato"), errors="coerce")

    df["Quantidade"] = df["texto_busqueda"].apply(extract_quantity)
    df["Unidade de Fornecimento"] = df["texto_busqueda"].apply(extract_unit)

    # Only derive unit price when both total value and quantity are available and quantity > 0
    df["Valor Unitário"] = df.apply(
        lambda row: row["valor_del_contrato"] / row["Quantidade"]
        if pd.notnull(row["valor_del_contrato"]) and pd.notnull(row["Quantidade"]) and row["Quantidade"] not in (0, 0.0)
        else None,
        axis=1
    )

    out = pd.DataFrame({
        "Unique tender/contract ID": df.get("id_contrato"),
        "Buying entity (hospital, health secretary, lab)": df.get("nombre_entidad"),
        "State": df.get("departamento"),
        "City/municipality": df.get("ciudad"),
        "Product description": df.get("objeto_del_contrato").fillna(df.get("descripcion_del_proceso")),
        "Brand and manufacturer name": df["texto_busqueda"].apply(extract_brand_or_manufacturer),
        "Quantity ordered": df["Quantidade"],
        "Unit": df["Unidade de Fornecimento"],
        "Unit price": df["Valor Unitário"],
        "Total contract value": df.get("valor_del_contrato"),
        "Winning supplier company name": df.get("proveedor_adjudicado"),
        "Supplier tax ID": df.get("documento_proveedor"),
        "Publication date": df.get("fecha_de_firma"),
        "Opening / closing date": (
            df.get("fecha_de_inicio_del_contrato", "").fillna("").astype(str)
            + " / " +
            df.get("fecha_de_fin_del_contrato", "").fillna("").astype(str)
        ),
        "Status": df.get("estado_contrato").apply(normalize_status),
        "Standard product catalog code": df.get("codigo_de_categoria_principal"),
        "Tender type": df.get("modalidad_de_contratacion"),
        "URL of individual tender detail page": df.get("Link Individual"),
    })

    out = out.drop_duplicates()
    out = out[out["Product description"].notna()]

    print(f"\nFiltered rows: {len(out)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_excel = args.output_dir / "secop_ivd_full_output.xlsx"
    output_csv = args.output_dir / "secop_ivd_full_output.csv"

    out.to_excel(output_excel, index=False)
    out.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("\nSaved:")
    print(f"- {output_excel}")
    print(f"- {output_csv}")


if __name__ == "__main__":
    main()
