from __future__ import annotations

import csv
import glob
import io
import os
import re
import time
import zipfile
from io import BytesIO
from typing import Dict, List, Tuple
from urllib.parse import urlencode

import cv2
import easyocr
import numpy as np
from PIL import Image
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


print("[INIT] Loading EasyOCR model ...")
easy_reader = easyocr.Reader(["en"], gpu=False)
print("[INIT] EasyOCR ready.")


KEYWORDS = "reagentes"
START_DATE = "01/01/2024"
END_DATE = "08/04/2026"
TEST_PAGE = 1

OUTFILE_SUCCESS = "comprasnet_results.csv"
OUTFILE_FAILURE = "comprasnet_failures.csv"

CAPTCHA_MAX_RETRIES = 6
CAPTCHA_LENGTH = 6
WAIT_SECONDS = 20

BASE_URL = "https://comprasnet.gov.br/ConsultaLicitacoes/ConsLicitacao_RelacaoTexto.asp"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
DELETE_ZIP_AFTER_MEMORY_READ = True

os.makedirs("captcha_debug", exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


SUCCESS_COLUMNS = [
    "process_number",
    "buying_entity",
    "state_uf",
    "city",
    "product_description",
    "brand_manufacturer",
    "quantity",
    "unit",
    "unit_price_brl",
    "total_value_brl",
    "winning_supplier_cnpj",
    "publication_date",
    "status",
    "tender_type",
    "total_notice_amount_brl",
    "entry_url",
]

FAILURE_COLUMNS = [
    "process_number",
    "buying_entity",
    "publication_date",
    "status",
    "tender_type",
    "entry_url",
    "failure_reason",
    "captcha_attempts_exhausted",
    "zip_downloaded",
    "relacaoitens_pdf_found",
]


def build_driver(headless: bool = False) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": DOWNLOAD_DIR,
            },
        )
    except Exception as e:
        print(f"[WARN] Could not set CDP download behavior: {e}")

    return driver


def wait(driver: webdriver.Chrome, seconds: int = WAIT_SECONDS) -> WebDriverWait:
    return WebDriverWait(driver, seconds)


def build_results_url(keywords: str, page: int) -> str:
    params = {
        "txtTermo": keywords,
        "chkTipoBusca": "1,2,3",
        "dt_publ_ini": START_DATE,
        "dt_publ_fim": END_DATE,
        "chkModalidade": "3,5",
        "optTpPesqMat": "M",
        "optTpPesqServ": "S",
        "numpag": str(page),
    }
    return f"{BASE_URL}?{urlencode(params)}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_after_label(text: str, labels: List[str]) -> str:
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(.+)", text, re.IGNORECASE)
        if m:
            return clean_text(m.group(1).splitlines()[0])
    return ""


def first_nonempty(*values: str) -> str:
    for v in values:
        if clean_text(v):
            return clean_text(v)
    return ""


def br_number_to_float_string(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    value = value.replace(".", "").replace(",", ".")
    try:
        return f"{float(value):.2f}"
    except Exception:
        return ""


def safe_mul_str(a: str, b: str) -> str:
    try:
        if not a or not b:
            return ""
        return f"{float(a) * float(b):.2f}"
    except Exception:
        return ""


def extract_cnpj(text: str) -> str:
    m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", text)
    return m.group(0) if m else ""


def parse_summary_metadata(text: str) -> Dict[str, str]:
    txt = clean_text(text)

    process_number = ""
    buying_entity = ""
    publication_date = ""
    tender_type = ""
    status = ""

    m = re.search(r"Preg[aã]o[:\s]*([0-9/]+)", txt, re.IGNORECASE)
    if m:
        process_number = clean_text(m.group(1))

    m = re.search(r"UASG[:\s]*([0-9]+)", txt, re.IGNORECASE)
    if m:
        buying_entity = clean_text(m.group(1))

    m = re.search(r"(\d{2}/\d{2}/\d{4})", txt)
    if m:
        publication_date = m.group(1)

    m = re.search(r"(Preg[aã]o\s+Eletr[oô]nico|Preg[aã]o|Concorr[eê]ncia|Dispensa|Inexigibilidade|Tomada de Pre[cç]os)", txt, re.IGNORECASE)
    if m:
        tender_type = clean_text(m.group(1))

    m = re.search(r"(Homologado|Encerrado|Aberto|Cancelado|Suspenso|Revogado|Adjudicado|Em andamento)", txt, re.IGNORECASE)
    if m:
        status = clean_text(m.group(1))

    return {
        "process_number": process_number,
        "buying_entity": buying_entity,
        "publication_date": publication_date,
        "tender_type": tender_type,
        "status": status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA OCR - grayscale only
# ─────────────────────────────────────────────────────────────────────────────
def _to_bgr(pil_img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _upscale(bgr: np.ndarray, scale: int = 3) -> np.ndarray:
    h, w = bgr.shape[:2]
    return cv2.resize(bgr, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)


def _grayscale_only_variant(bgr: np.ndarray) -> np.ndarray:
    up = _upscale(bgr, scale=3)
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    return gray


def _run_easyocr_on_gray(gray: np.ndarray) -> str:
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    try:
        detections = easy_reader.readtext(
            rgb,
            detail=1,
            paragraph=False,
            rotation_info=[0],
        )
    except Exception as e:
        print(f"[OCR] EasyOCR error: {e}")
        return ""

    best_text = ""
    best_score = -1e9
    raw_hits = []

    for _, text, conf in detections:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", text or "").strip()
        if cleaned:
            raw_hits.append(cleaned)
            candidate = cleaned[:CAPTCHA_LENGTH] if len(cleaned) > CAPTCHA_LENGTH else cleaned
            if len(candidate) == CAPTCHA_LENGTH and candidate.isalnum():
                score = conf
                if len(candidate) == CAPTCHA_LENGTH:
                    score += 1.0
                if candidate.isalnum():
                    score += 0.3
                if score > best_score:
                    best_score = score
                    best_text = candidate

    print(f"[OCR] grayscale -> {raw_hits}")
    return best_text


def solve_captcha_from_element(captcha_img_element) -> str:
    ts = str(int(time.time() * 1000))
    png = captcha_img_element.screenshot_as_png
    raw = Image.open(io.BytesIO(png)).convert("RGB")

    print(f"[OCR] Raw captcha size: {raw.size}")
    raw.save(os.path.join("captcha_debug", f"raw_{ts}.png"))

    bgr = _to_bgr(raw)
    gray = _grayscale_only_variant(bgr)
    Image.fromarray(gray).save(os.path.join("captcha_debug", f"{ts}_gray.png"))

    best = _run_easyocr_on_gray(gray)
    print(f"[OCR] Final: '{best}'")
    return best


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA ELEMENTS
# ─────────────────────────────────────────────────────────────────────────────
def find_captcha_image(driver: webdriver.Chrome):
    candidates = []
    css_selectors = [
        "img[src*='captcha']",
        "img[src*='Captcha']",
        "img[src*='validacao']",
        "img[id*='captcha']",
        "img[name*='captcha']",
        "img[alt*='captcha' i]",
    ]
    for sel in css_selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if not el.is_displayed():
                    continue
                s = el.size
                w, h = s.get("width", 0), s.get("height", 0)
                if w >= 60 and h >= 20:
                    candidates.append((w * h, el))
            except Exception:
                pass

    if candidates:
        return max(candidates, key=lambda x: x[0])[1]

    fallback = []
    for el in driver.find_elements(By.TAG_NAME, "img"):
        try:
            if not el.is_displayed():
                continue
            s = el.size
            w, h = s.get("width", 0), s.get("height", 0)
            if w >= 80 and h >= 25:
                fallback.append((w * h, el))
        except Exception:
            pass

    return max(fallback, key=lambda x: x[0])[1] if fallback else None


def find_captcha_input(driver: webdriver.Chrome):
    xpaths = [
        "//input[@name='txtToken_captcha']",
        "//input[contains(@name,'captcha')]",
        "//input[contains(@id,'captcha')]",
        "//input[contains(@name,'token')]",
        "//input[contains(@id,'token')]",
        "//input[@type='text' and not(@readonly)]",
    ]
    for xp in xpaths:
        for el in driver.find_elements(By.XPATH, xp):
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                pass
    return None


def find_confirm_button(driver: webdriver.Chrome):
    xpaths = [
        "//input[@value='Confirmar']",
        "//input[@value='Download']",
        "//input[contains(@value,'Confirm')]",
        "//button[contains(., 'Confirmar')]",
        "//button[contains(., 'Download')]",
        "//input[@type='submit']",
        "//button[@type='submit']",
    ]
    for xp in xpaths:
        for el in driver.find_elements(By.XPATH, xp):
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                pass
    return None


def refresh_captcha_if_possible(driver: webdriver.Chrome) -> bool:
    xpaths = [
        "//a[contains(., 'gerar outra imagem')]",
        "//a[contains(., 'Nova Imagem')]",
        "//a[contains(., 'Atualizar')]",
        "//button[contains(., 'Atualizar')]",
    ]
    for xp in xpaths:
        for el in driver.find_elements(By.XPATH, xp):
            try:
                if el.is_displayed():
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    time.sleep(1.5)
                    return True
            except Exception:
                pass
    return False


def wait_for_captcha_to_be_visible(driver: webdriver.Chrome, timeout: int = 25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        img = find_captcha_image(driver)
        inp = find_captcha_input(driver)
        btn = find_confirm_button(driver)

        if (
            img and img.is_displayed()
            and inp and inp.is_displayed() and inp.is_enabled()
            and btn and btn.is_displayed() and btn.is_enabled()
        ):
            return True
        time.sleep(0.3)
    return False


def _fill_input_robustly(driver: webdriver.Chrome, inp, text: str) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
        time.sleep(0.2)
        inp.click()
        time.sleep(0.15)
        inp.clear()
        inp.send_keys(text)
        time.sleep(0.3)
        actual = driver.execute_script("return arguments[0].value;", inp)
        if actual == text:
            print(f"[INPUT] Filled via send_keys -> '{actual}'")
            return True
    except Exception as e:
        print(f"[INPUT] send_keys failed: {e}")

    try:
        driver.execute_script("""
            var el = arguments[0];
            var val = arguments[1];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, inp, text)
        time.sleep(0.3)
        actual = driver.execute_script("return arguments[0].value;", inp)
        if actual == text:
            print(f"[INPUT] Filled via JS setter -> '{actual}'")
            return True
    except Exception as e:
        print(f"[INPUT] JS setter failed: {e}")

    return False


def _click_confirm_robustly(driver: webdriver.Chrome, btn) -> None:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.2)
    except Exception:
        pass

    try:
        btn.click()
        print("[CONFIRM] Clicked via Selenium")
        return
    except Exception as e:
        print(f"[CONFIRM] Selenium click failed: {e}")

    try:
        driver.execute_script("arguments[0].click();", btn)
        print("[CONFIRM] Clicked via JS")
        return
    except Exception as e:
        print(f"[CONFIRM] JS click failed: {e}")


def body_has_rejection_message(driver: webdriver.Chrome) -> bool:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        rejection_words = [
            "inválido",
            "invalido",
            "incorreto",
            "erro",
            "invalid",
            "caracteres incorretos",
            "código inválido",
            "codigo invalido",
        ]
        return any(word in body for word in rejection_words)
    except Exception:
        return False


def handle_captcha_and_download(driver: webdriver.Chrome, proc_num: str) -> Tuple[bool, bool]:
    print(f"[INFO] Waiting for CAPTCHA - {proc_num}")
    print(f"[INFO] Current URL : {driver.current_url}")
    print(f"[INFO] Open windows: {driver.window_handles}")

    if not wait_for_captcha_to_be_visible(driver, timeout=25):
        print("[WARN] CAPTCHA UI did not become ready in time")
        return False, True

    for attempt in range(1, CAPTCHA_MAX_RETRIES + 1):
        print(f"[CAPTCHA] Attempt {attempt}/{CAPTCHA_MAX_RETRIES} - {proc_num}")

        img = find_captcha_image(driver)
        inp = find_captcha_input(driver)
        btn = find_confirm_button(driver)

        if not img or not inp or not btn:
            print("[WARN] CAPTCHA elements disappeared before attempt")
            return False, True

        captcha_text = solve_captcha_from_element(img)
        print(f"[INFO] OCR guess: '{captcha_text}'")

        if not captcha_text or not captcha_text.isalnum() or len(captcha_text) != CAPTCHA_LENGTH:
            print(f"[WARN] Bad OCR result ('{captcha_text}') - refreshing")
            refresh_captcha_if_possible(driver)
            time.sleep(1)
            continue

        filled = _fill_input_robustly(driver, inp, captcha_text)
        if not filled:
            print("[WARN] Could not verify input was filled")

        try:
            actual_val = driver.execute_script("return arguments[0].value;", inp)
            print(f"[INPUT] Field value before submit: '{actual_val}'")
        except Exception:
            pass

        _click_confirm_robustly(driver, btn)
        time.sleep(2.5)

        if body_has_rejection_message(driver):
            print(f"[CAPTCHA] Server rejected on attempt {attempt}")
            refresh_captcha_if_possible(driver)
            time.sleep(1)
            continue

        print(f"[CAPTCHA] No rejection message found after attempt {attempt}; treating as accepted")
        return True, False

    print(f"[CAPTCHA] Failed after {CAPTCHA_MAX_RETRIES} attempts")
    return False, True


# ─────────────────────────────────────────────────────────────────────────────
# ZIP / PDF MEMORY PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def wait_for_new_zip_download(download_dir: str, before_files: set[str], timeout: int = 180) -> str | None:
    deadline = time.time() + timeout
    seen_crdownload = False
    last_crdownload_path = ""

    while time.time() < deadline:
        current_files = set(glob.glob(os.path.join(download_dir, "*")))
        new_files = current_files - before_files

        if new_files:
            print(f"[ZIP] New files detected: {sorted(new_files)}")

        ready_zips = [
            f for f in new_files
            if f.lower().endswith(".zip")
            and os.path.isfile(f)
            and not f.lower().endswith(".crdownload")
        ]
        if ready_zips:
            zip_path = max(ready_zips, key=os.path.getmtime)
            size1 = os.path.getsize(zip_path)
            time.sleep(1.5)
            if os.path.exists(zip_path):
                size2 = os.path.getsize(zip_path)
                if size1 == size2 and size1 > 0:
                    print(f"[ZIP] Ready: {zip_path}")
                    return zip_path

        crs = [
            f for f in current_files
            if f.lower().endswith(".crdownload") and os.path.isfile(f)
        ]
        if crs:
            seen_crdownload = True
            last_crdownload_path = max(crs, key=os.path.getmtime)
            print(f"[ZIP] Active download: {last_crdownload_path}")
            time.sleep(1.0)
            continue

        if seen_crdownload and last_crdownload_path:
            expected_zip = re.sub(r"\.crdownload$", "", last_crdownload_path, flags=re.IGNORECASE)
            if os.path.exists(expected_zip) and os.path.isfile(expected_zip):
                size1 = os.path.getsize(expected_zip)
                time.sleep(1.5)
                if os.path.exists(expected_zip):
                    size2 = os.path.getsize(expected_zip)
                    if size1 == size2 and size1 > 0:
                        print(f"[ZIP] Completed from crdownload -> {expected_zip}")
                        return expected_zip

        time.sleep(0.75)

    return None


def read_file_as_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    print(f"[ZIP] Read {len(data)} bytes from {path}")
    return data


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        print("[PDF] pypdf not installed; skipping text extraction")
        return ""

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        text = "\n".join(chunks).strip()
        print(f"[PDF] Extracted {len(text)} chars from PDF bytes")
        return text
    except Exception as e:
        print(f"[PDF] Failed reading PDF bytes: {e}")
        return ""


def extract_pdf_metadata_from_text(text: str) -> Dict[str, str]:
    meta = {
        "pdf_uasg_orgao_code": "",
        "pdf_uasg_orgao_nome": "",
        "pdf_uasg_code": "",
        "pdf_uasg_nome": "",
        "pdf_pregao_numero": "",
        "pdf_datahora": "",
    }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2:
        m0 = re.match(r"^(\d+)\s*-\s*(.+)$", lines[0])
        if m0:
            meta["pdf_uasg_orgao_code"] = m0.group(1).strip()
            meta["pdf_uasg_orgao_nome"] = m0.group(2).strip()

        m1 = re.match(r"^(\d+)\s*-\s*(.+)$", lines[1])
        if m1:
            meta["pdf_uasg_code"] = m1.group(1).strip()
            meta["pdf_uasg_nome"] = m1.group(2).strip()

    m = re.search(
        r"RELAÇÃO DE ITENS\s*-\s*PREGÃO ELETRÔNICO Nº\s*([0-9/\-]+(?:\s*SRP)?)",
        text,
        re.IGNORECASE,
    )
    if m:
        meta["pdf_pregao_numero"] = clean_text(m.group(1))

    m = re.search(
        r"UASG\s+\d+\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        meta["pdf_datahora"] = m.group(1).strip()

    return meta


def normalize_relacaoitens_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(
        r"PREGÃO ELETRÔNICO Nº.*?UASG\s+\d+\s+\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+\(\d+/\d+\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n1\s*-\s*Itens da Licitação\s*\n", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\n)\n(?!\d+\s*-\s)", " ", text)

    labels = [
        "Descrição Detalhada:",
        "Tratamento Diferenciado:",
        "Aplicabilidade Decreto 7174/2010:",
        "Quantidade Total:",
        "Critério de Julgamento:",
        "Valor Unitário \\(R\\$\\):",
        "Unidade de Fornecimento:",
        "Intervalo Mínimo entre Lances \\(R\\$\\):",
        "Local de Entrega \\(Quantidade\\):",
        "Marca:",
        "Fabricante:",
    ]
    for label in labels:
        text = re.sub(rf"\s*({label})", r"\n\1", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+(\d+\s*-\s)", r"\n\1", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_brand_manufacturer(text: str) -> str:
    brand = ""
    manufacturer = ""

    m = re.search(r"Marca:\s*(.*?)\s*(?=\n|$)", text, re.IGNORECASE)
    if m:
        brand = clean_text(m.group(1))

    m = re.search(r"Fabricante:\s*(.*?)\s*(?=\n|$)", text, re.IGNORECASE)
    if m:
        manufacturer = clean_text(m.group(1))

    return " / ".join([x for x in [brand, manufacturer] if x])


def parse_local_city_uf(local_entrega: str) -> Tuple[str, str]:
    local_entrega = clean_text(local_entrega)
    if not local_entrega:
        return "", ""

    m = re.match(r"(.+?)/([A-Z]{2})$", local_entrega)
    if m:
        return clean_text(m.group(1)), clean_text(m.group(2))

    m = re.search(r"([A-Z]{2})\s*$", local_entrega)
    if m:
        uf = clean_text(m.group(1))
        city = clean_text(local_entrega[:m.start()].strip(" -/,"))
        return city, uf

    return "", ""


def parse_relacaoitens_pdf_text(text: str) -> List[Dict[str, str]]:
    meta = extract_pdf_metadata_from_text(text)
    clean = normalize_relacaoitens_text(text)

    item_pattern = re.compile(
        r"(?ms)^\s*(\d+)\s*-\s*(.+?)\n"
        r"(.*?)(?=^\s*\d+\s*-\s.+?$|\Z)"
    )

    rows: List[Dict[str, str]] = []

    for m in item_pattern.finditer(clean):
        item_name = clean_text(m.group(2).strip(" ,"))

        def grab(pattern: str) -> str:
            mm = re.search(pattern, m.group(3), re.IGNORECASE | re.DOTALL)
            if not mm:
                return ""
            return re.sub(r"\s+", " ", mm.group(1)).strip()

        descricao = grab(r"Descrição Detalhada:\s*(.*?)\s*(?=\nTratamento Diferenciado:|\Z)")
        qtd_total = ""
        m_qty = re.search(
            r"Quantidade Total:\s*([0-9\.,]+)\s+Quantidade Mínima Cotada:\s*([0-9\.,]+)",
            m.group(3),
            re.IGNORECASE,
        )
        if m_qty:
            qtd_total = clean_text(m_qty.group(1))

        valor_unitario = grab(r"Valor Unitário \(R\$\):\s*([0-9\.\,]+)")

        unidade_fornecimento = ""
        m_un = re.search(
            r"Unidade de Fornecimento:\s*(.*?)\s+Quantidade Máxima para Adesões:\s*([0-9\.,]+)",
            m.group(3),
            re.IGNORECASE | re.DOTALL,
        )
        if m_un:
            unidade_fornecimento = clean_text(m_un.group(1))
        if not unidade_fornecimento:
            unidade_fornecimento = grab(r"Unidade de Fornecimento:\s*(.*?)\s*(?=\n|$)")

        local_entrega = ""
        m_loc = re.search(
            r"Local de Entrega \(Quantidade\):\s*(.*?)\s*\(([\d\.,]+)\)",
            m.group(3),
            re.IGNORECASE | re.DOTALL,
        )
        if m_loc:
            local_entrega = clean_text(m_loc.group(1))

        city, uf = parse_local_city_uf(local_entrega)
        brand_manufacturer = extract_brand_manufacturer(m.group(3))
        product_description = first_nonempty(descricao, item_name)
        quantity_num = br_number_to_float_string(qtd_total)
        unit_price_num = br_number_to_float_string(valor_unitario)
        total_value_num = safe_mul_str(quantity_num, unit_price_num)

        row = {
            **meta,
            "product_description": product_description,
            "brand_manufacturer": brand_manufacturer,
            "quantity": quantity_num,
            "unit": unidade_fornecimento,
            "unit_price_brl": unit_price_num,
            "total_value_brl": total_value_num,
            "city": city,
            "state_uf": uf,
        }
        rows.append(row)

    return rows


def capture_zip_and_extract_relacaoitens(
    before_files: set,
    download_dir: str = DOWNLOAD_DIR,
    timeout: int = 180,
    delete_zip_after_read: bool = DELETE_ZIP_AFTER_MEMORY_READ,
) -> dict:
    zip_path = wait_for_new_zip_download(download_dir, before_files, timeout=timeout)
    if not zip_path:
        print("[ZIP] No ZIP found after download")
        return {
            "zip_path": "",
            "zip_bytes": b"",
            "relacaoitens_pdf_names": [],
            "pdf_texts": {},
            "parsed_item_rows": [],
        }

    zip_bytes = read_file_as_bytes(zip_path)

    if delete_zip_after_read:
        try:
            os.remove(zip_path)
            print(f"[ZIP] Deleted local ZIP after memory read: {zip_path}")
        except Exception as e:
            print(f"[WARN] Could not delete ZIP after memory read: {e}")

    relacaoitens_pdf_names = []
    pdf_texts = {}
    parsed_item_rows = []

    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            members = zf.namelist()
            print(f"[ZIP] Archive entries: {members}")

            for member in members:
                base = os.path.basename(member)
                low = base.lower()
                if not base:
                    continue

                if "relacaoitens" in low and low.endswith(".pdf"):
                    print(f"[ZIP] Found target PDF in memory: {base}")
                    relacaoitens_pdf_names.append(base)

                    with zf.open(member) as src:
                        pdf_bytes = src.read()

                    text = extract_text_from_pdf_bytes(pdf_bytes)
                    pdf_texts[base] = text

                    if text.strip():
                        rows = parse_relacaoitens_pdf_text(text)
                        for r in rows:
                            r["source_pdf_name"] = base
                        parsed_item_rows.extend(rows)

    except Exception as e:
        print(f"[ZIP] Failed to process ZIP in memory: {e}")

    print(f"[ZIP] Parsed rows from PDF(s): {len(parsed_item_rows)}")
    return {
        "zip_path": zip_path,
        "zip_bytes": zip_bytes,
        "relacaoitens_pdf_names": relacaoitens_pdf_names,
        "pdf_texts": pdf_texts,
        "parsed_item_rows": parsed_item_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS PAGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_notice_blocks(driver: webdriver.Chrome) -> list:
    locator = (
        "//table[@class='td' or @name='relacao'] "
        "| //form[@name='Form']/table"
    )
    try:
        wait(driver, 10).until(EC.presence_of_element_located((By.XPATH, locator)))
        candidates = driver.find_elements(By.XPATH, locator)
    except Exception:
        return []

    unique = []
    seen = set()
    for element in candidates:
        try:
            html = element.get_attribute("outerHTML")
            if "Itens e Download" in html and html not in seen:
                seen.add(html)
                unique.append(element)
        except Exception:
            continue
    return unique


def get_notice_summaries(driver: webdriver.Chrome) -> List[Dict[str, str]]:
    summaries = []
    blocks = get_notice_blocks(driver)

    for idx, block in enumerate(blocks, start=1):
        try:
            text = clean_text(block.text)
            parsed = parse_summary_metadata(text)

            summaries.append({
                "block_index": idx,
                "summary_text": text,
                "process_number": parsed["process_number"],
                "buying_entity": parsed["buying_entity"],
                "publication_date": parsed["publication_date"],
                "status": parsed["status"],
                "tender_type": parsed["tender_type"],
                "entry_url": driver.current_url,
            })
        except StaleElementReferenceException:
            continue

    return summaries


def get_edital_buttons(driver: webdriver.Chrome) -> list:
    return driver.find_elements(By.XPATH, "//input[@value='Edital']")


def return_to_results_page(driver: webdriver.Chrome, results_url: str, main_handle: str) -> None:
    for h in list(driver.window_handles):
        if h != main_handle:
            try:
                driver.switch_to.window(h)
                driver.close()
            except Exception:
                pass

    driver.switch_to.window(main_handle)
    time.sleep(0.8)

    if "ConsLicitacao_RelacaoTexto" not in driver.current_url:
        try:
            driver.get(results_url)
            time.sleep(2)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# NOTICE PAGE EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
def click_itens_download_for_block(driver: webdriver.Chrome, block_index: int) -> str:
    blocks = get_notice_blocks(driver)
    if not blocks:
        raise RuntimeError("No notice blocks found on results page.")
    if block_index < 1 or block_index > len(blocks):
        raise RuntimeError(f"Block {block_index} unavailable - only {len(blocks)} blocks found.")

    block = blocks[block_index - 1]
    button = block.find_element(
        By.XPATH,
        ".//a[contains(., 'Itens e Download')] | .//input[contains(@value, 'Download')]",
    )

    old_handles = driver.window_handles[:]
    old_url = driver.current_url

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
    time.sleep(0.5)

    onclick = button.get_attribute("onclick")
    if onclick:
        try:
            driver.execute_script(onclick)
        except Exception:
            driver.execute_script("arguments[0].click();", button)
    else:
        try:
            button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", button)

    time.sleep(2)

    if len(driver.window_handles) > len(old_handles):
        return "new_window"
    if driver.current_url != old_url:
        return "same_tab"

    deadline = time.time() + 8
    while time.time() < deadline:
        if len(driver.window_handles) > len(old_handles):
            return "new_window"
        if driver.current_url != old_url:
            return "same_tab"
        time.sleep(0.25)

    raise RuntimeError(f"Notice {block_index} did not open in new window or same tab.")


def extract_notice_level_fields(driver: webdriver.Chrome) -> Dict[str, str]:
    text = driver.find_element(By.TAG_NAME, "body").text
    text_clean = clean_text(text)

    process_number = extract_after_label(text_clean, ["Processo", "Nº do Processo"])
    buying_entity = extract_after_label(text_clean, ["Órgão", "UASG"])
    publication_date = extract_after_label(text_clean, ["Data de Publicação", "Publicação", "Data"])
    status = extract_after_label(text_clean, ["Situação", "Status"])
    tender_type = extract_after_label(text_clean, ["Modalidade", "Tipo"])

    if not publication_date:
        m = re.search(r"(\d{2}/\d{2}/\d{4})", text_clean)
        if m:
            publication_date = m.group(1)

    winning_supplier = extract_after_label(text_clean, ["Fornecedor Vencedor", "Vencedor", "Fornecedor"])
    cnpj = extract_cnpj(text_clean)
    winning_supplier_cnpj = clean_text(" - ".join([x for x in [winning_supplier, cnpj] if x]))

    total_notice_amount_brl = ""
    patterns = [
        r"Valor Total(?: Estimado)?[:\s]*R?\$?\s*([0-9\.\,]+)",
        r"Valor Global[:\s]*R?\$?\s*([0-9\.\,]+)",
        r"Total da Licitação[:\s]*R?\$?\s*([0-9\.\,]+)",
        r"Valor Homologado[:\s]*R?\$?\s*([0-9\.\,]+)",
    ]
    for p in patterns:
        m = re.search(p, text_clean, re.IGNORECASE)
        if m:
            total_notice_amount_brl = br_number_to_float_string(m.group(1))
            if total_notice_amount_brl:
                break

    city = extract_after_label(text_clean, ["Município", "Cidade"])
    state_uf = extract_after_label(text_clean, ["UF", "Estado"])

    return {
        "process_number": process_number,
        "buying_entity": buying_entity,
        "publication_date": publication_date,
        "status": status,
        "tender_type": tender_type,
        "winning_supplier_cnpj": winning_supplier_cnpj,
        "total_notice_amount_brl": total_notice_amount_brl,
        "city_notice": city,
        "state_uf_notice": state_uf,
        "entry_url": driver.current_url,
    }


def extract_notice_fields_from_itens_page(
    driver: webdriver.Chrome,
    summary: Dict[str, str],
    results_url: str,
) -> Dict[str, str]:
    main_handle = driver.window_handles[0]
    result = {
        "process_number": summary.get("process_number", ""),
        "buying_entity": summary.get("buying_entity", ""),
        "publication_date": summary.get("publication_date", ""),
        "status": summary.get("status", ""),
        "tender_type": summary.get("tender_type", ""),
        "winning_supplier_cnpj": "",
        "total_notice_amount_brl": "",
        "city_notice": "",
        "state_uf_notice": "",
        "entry_url": summary.get("entry_url", results_url),
    }

    try:
        open_mode = click_itens_download_for_block(driver, summary["block_index"])
        if open_mode == "new_window":
            wait(driver, 10).until(lambda d: len(d.window_handles) > 1)
            driver.switch_to.window(driver.window_handles[-1])
        else:
            time.sleep(2)

        extracted = extract_notice_level_fields(driver)
        for k, v in extracted.items():
            if clean_text(v):
                result[k] = v

    except Exception as e:
        print(f"[WARN] Notice-level extraction failed for block {summary['block_index']}: {e}")

    finally:
        return_to_results_page(driver, results_url, main_handle)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# EDITAL ZIP FLOW
# ─────────────────────────────────────────────────────────────────────────────
def click_edital_for_card_and_capture_zip(
    driver: webdriver.Chrome,
    summary: Dict[str, str],
    results_url: str,
) -> Dict[str, object]:
    buttons = get_edital_buttons(driver)
    idx = summary["block_index"]

    result: Dict[str, object] = dict(summary)
    result["edital_download_success"] = False
    result["download_zip_path"] = ""
    result["download_zip_size_bytes"] = ""
    result["download_zip_in_memory"] = False
    result["relacaoitens_pdf_count"] = 0
    result["relacaoitens_pdf_names"] = ""
    result["captcha_attempts_exhausted"] = False
    result["failure_reason"] = ""

    if idx > len(buttons):
        result["failure_reason"] = f"Only {len(buttons)} Edital buttons found"
        return result

    btn = buttons[idx - 1]

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.4)
    except Exception:
        pass

    before_handles = set(driver.window_handles)
    before_files = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*")))
    main_handle = driver.window_handles[0]

    try:
        btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", btn)

    time.sleep(1.5)

    new_handles = set(driver.window_handles) - before_handles
    accepted = False
    attempts_exhausted = False

    if new_handles:
        popup_handle = list(new_handles)[-1]
        driver.switch_to.window(popup_handle)
        print(f"[INFO] Switched to Edital popup for card {idx}")
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            pass
        time.sleep(1)

        result["entry_url"] = driver.current_url
        accepted, attempts_exhausted = handle_captcha_and_download(driver, f"card {idx}")
        result["captcha_attempts_exhausted"] = attempts_exhausted

        if accepted:
            print("[INFO] CAPTCHA accepted, waiting for ZIP download...")
            zip_result = capture_zip_and_extract_relacaoitens(
                before_files=before_files,
                download_dir=DOWNLOAD_DIR,
                timeout=180,
                delete_zip_after_read=True,
            )

            zip_found = bool(zip_result["zip_bytes"])
            pdf_found = bool(zip_result["relacaoitens_pdf_names"])
            result["edital_download_success"] = zip_found
            result["download_zip_path"] = zip_result["zip_path"]
            result["download_zip_size_bytes"] = str(len(zip_result["zip_bytes"]))
            result["download_zip_in_memory"] = zip_found
            result["relacaoitens_pdf_count"] = len(zip_result["relacaoitens_pdf_names"])
            result["relacaoitens_pdf_names"] = " | ".join(zip_result["relacaoitens_pdf_names"])
            result["_parsed_item_rows"] = zip_result["parsed_item_rows"]

            if not zip_found:
                result["failure_reason"] = "No ZIP found after CAPTCHA submission"
            elif not pdf_found:
                result["failure_reason"] = "ZIP downloaded but no relacaoitens PDF found"
        else:
            result["edital_download_success"] = False
            result["failure_reason"] = "CAPTCHA attempts exhausted" if attempts_exhausted else "CAPTCHA/Download flow failed"

        try:
            driver.close()
        except Exception:
            pass
        driver.switch_to.window(main_handle)

    else:
        print(f"[INFO] Edital opened in same tab for card {idx}")
        result["entry_url"] = driver.current_url
        accepted, attempts_exhausted = handle_captcha_and_download(driver, f"card {idx}")
        result["captcha_attempts_exhausted"] = attempts_exhausted

        if accepted:
            print("[INFO] CAPTCHA accepted, waiting for ZIP download...")
            zip_result = capture_zip_and_extract_relacaoitens(
                before_files=before_files,
                download_dir=DOWNLOAD_DIR,
                timeout=180,
                delete_zip_after_read=True,
            )

            zip_found = bool(zip_result["zip_bytes"])
            pdf_found = bool(zip_result["relacaoitens_pdf_names"])
            result["edital_download_success"] = zip_found
            result["download_zip_path"] = zip_result["zip_path"]
            result["download_zip_size_bytes"] = str(len(zip_result["zip_bytes"]))
            result["download_zip_in_memory"] = zip_found
            result["relacaoitens_pdf_count"] = len(zip_result["relacaoitens_pdf_names"])
            result["relacaoitens_pdf_names"] = " | ".join(zip_result["relacaoitens_pdf_names"])
            result["_parsed_item_rows"] = zip_result["parsed_item_rows"]

            if not zip_found:
                result["failure_reason"] = "No ZIP found after CAPTCHA submission"
            elif not pdf_found:
                result["failure_reason"] = "ZIP downloaded but no relacaoitens PDF found"
        else:
            result["edital_download_success"] = False
            result["failure_reason"] = "CAPTCHA attempts exhausted" if attempts_exhausted else "CAPTCHA/Download flow failed"

        try:
            driver.get(results_url)
            time.sleep(2)
        except Exception:
            pass

    return result


# ─────────────────────────────────────────────────────────────────────────────
# ROW SHAPING
# ─────────────────────────────────────────────────────────────────────────────
def make_success_row(notice_fields: Dict[str, str], item: Dict[str, str]) -> Dict[str, str]:
    process_number = first_nonempty(
        notice_fields.get("process_number", ""),
        item.get("pdf_pregao_numero", ""),
    )

    buying_entity = first_nonempty(
        notice_fields.get("buying_entity", ""),
        item.get("pdf_uasg_nome", ""),
    )

    publication_date = first_nonempty(
        notice_fields.get("publication_date", ""),
        item.get("pdf_datahora", "")[:10] if item.get("pdf_datahora", "") else "",
    )

    tender_type = first_nonempty(
        notice_fields.get("tender_type", ""),
        "Pregão Eletrônico" if item.get("pdf_pregao_numero") else "",
    )

    return {
        "process_number": process_number,
        "buying_entity": buying_entity,
        "state_uf": first_nonempty(item.get("state_uf", ""), notice_fields.get("state_uf_notice", "")),
        "city": first_nonempty(item.get("city", ""), notice_fields.get("city_notice", "")),
        "product_description": clean_text(item.get("product_description", "")),
        "brand_manufacturer": clean_text(item.get("brand_manufacturer", "")),
        "quantity": clean_text(item.get("quantity", "")),
        "unit": clean_text(item.get("unit", "")),
        "unit_price_brl": clean_text(item.get("unit_price_brl", "")),
        "total_value_brl": clean_text(item.get("total_value_brl", "")),
        "winning_supplier_cnpj": clean_text(notice_fields.get("winning_supplier_cnpj", "")),
        "publication_date": publication_date,
        "status": clean_text(notice_fields.get("status", "")),
        "tender_type": tender_type,
        "total_notice_amount_brl": clean_text(notice_fields.get("total_notice_amount_brl", "")),
        "entry_url": clean_text(notice_fields.get("entry_url", "")),
    }


def make_failure_row(result: Dict[str, object]) -> Dict[str, str]:
    return {
        "process_number": clean_text(str(result.get("process_number", ""))),
        "buying_entity": clean_text(str(result.get("buying_entity", ""))),
        "publication_date": clean_text(str(result.get("publication_date", ""))),
        "status": clean_text(str(result.get("status", ""))),
        "tender_type": clean_text(str(result.get("tender_type", ""))),
        "entry_url": clean_text(str(result.get("entry_url", ""))),
        "failure_reason": clean_text(str(result.get("failure_reason", ""))),
        "captcha_attempts_exhausted": str(bool(result.get("captcha_attempts_exhausted", False))),
        "zip_downloaded": str(bool(result.get("download_zip_in_memory", False))),
        "relacaoitens_pdf_found": str(int(result.get("relacaoitens_pdf_count", 0)) > 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CORE LOOP
# ─────────────────────────────────────────────────────────────────────────────
def process_notice(
    driver: webdriver.Chrome,
    summary: Dict[str, str],
    results_url: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    main_handle = driver.window_handles[0]
    success_rows: List[Dict[str, str]] = []
    failure_rows: List[Dict[str, str]] = []

    try:
        edital_result = click_edital_for_card_and_capture_zip(driver, summary, results_url)
        parsed_rows = edital_result.pop("_parsed_item_rows", [])

        if parsed_rows:
            return_to_results_page(driver, results_url, main_handle)
            current = get_notice_summaries(driver)
            notice_summary = current[summary["block_index"] - 1] if summary["block_index"] <= len(current) else summary
            notice_fields = extract_notice_fields_from_itens_page(driver, notice_summary, results_url)

            for item in parsed_rows:
                success_rows.append(make_success_row(notice_fields, item))

            print(f"[OK] Card {summary['block_index']} | parsed_pdf_rows={len(parsed_rows)}")
        else:
            failure_rows.append(make_failure_row(edital_result))
            print(f"[WARN] Card {summary['block_index']} | no parsed PDF rows")

    except Exception as e:
        print(f"[WARN] Error on notice {summary['block_index']}: {e}")
        out = dict(summary)
        out["failure_reason"] = str(e)
        out["captcha_attempts_exhausted"] = False
        out["download_zip_in_memory"] = False
        out["relacaoitens_pdf_count"] = 0
        failure_rows.append(make_failure_row(out))

    finally:
        return_to_results_page(driver, results_url, main_handle)

    return success_rows, failure_rows


def test_one_page(driver: webdriver.Chrome, results_url: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    print(f"[INFO] Opening: {results_url}")
    driver.get(results_url)
    time.sleep(2)

    summaries = get_notice_summaries(driver)
    print(f"[INFO] Found {len(summaries)} notices.")

    all_success: List[Dict[str, str]] = []
    all_failures: List[Dict[str, str]] = []

    for i in range(1, len(summaries) + 1):
        print(f"\n{'-'*60}\n  Notice {i}/{len(summaries)}\n{'-'*60}")
        return_to_results_page(driver, results_url, driver.window_handles[0])
        current = get_notice_summaries(driver)

        if i <= len(current):
            success_rows, failure_rows = process_notice(driver, current[i - 1], results_url)
            all_success.extend(success_rows)
            all_failures.extend(failure_rows)
        else:
            print(f"[WARN] Notice {i} no longer available after reload")

    return all_success, all_failures


def save_csv(rows: List[Dict[str, str]], filename: str, fieldnames: List[str]) -> None:
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        if rows:
            w.writerows(rows)
    print(f"[DONE] Saved {len(rows)} rows -> {filename}")


def main():
    driver = build_driver(headless=False)
    try:
        url = build_results_url(KEYWORDS, TEST_PAGE)
        success_rows, failure_rows = test_one_page(driver, url)
        save_csv(success_rows, OUTFILE_SUCCESS, SUCCESS_COLUMNS)
        save_csv(failure_rows, OUTFILE_FAILURE, FAILURE_COLUMNS)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()