"""
captcha_solver.py - grayscale EasyOCR captcha solver with segmentation fallback
==============================================================================
"""

import argparse
import io
import logging
import os
import re
from typing import Optional

import cv2
import numpy as np
import requests
from PIL import Image

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr

        logging.info("Loading EasyOCR model (downloads ~100 MB on first run)...")
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


def _decode_image(img_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(img_bytes)).convert("RGB")


def _gray_upscaled(img_bytes: bytes, scale: int = 4) -> np.ndarray:
    img = np.array(_decode_image(img_bytes))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _prepare_variants(img_bytes: bytes) -> list[tuple[str, np.ndarray]]:
    gray = _gray_upscaled(img_bytes, scale=4)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_blur = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    return [
        ("gray", gray),
        ("gray_inv", cv2.bitwise_not(gray)),
        ("otsu", otsu),
        ("otsu_inv", cv2.bitwise_not(otsu)),
        ("otsu_blur", otsu_blur),
        ("adaptive", adaptive),
    ]


def _save_debug(img_bytes: bytes, variants: list[tuple[str, np.ndarray]], out_dir: str = "captcha_debug") -> None:
    os.makedirs(out_dir, exist_ok=True)
    _decode_image(img_bytes).save(os.path.join(out_dir, "00_original.png"))
    for idx, (label, arr) in enumerate(variants, start=1):
        Image.fromarray(arr).save(os.path.join(out_dir, f"attempt_{idx:02d}_{label}.png"))


def _remove_small_components(mask: np.ndarray, min_area: int = 30, min_height: int = 18) -> np.ndarray:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    for idx in range(1, num_labels):
        _, _, _, h, area = stats[idx]
        if area >= min_area and h >= min_height:
            cleaned[labels == idx] = 255
    return cleaned


def _build_segmentation_mask(img_bytes: bytes) -> np.ndarray:
    gray = _gray_upscaled(img_bytes, scale=4)
    mask = np.zeros_like(gray)
    mask[gray < 185] = 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    return _remove_small_components(mask)


def _spans_from_projection(mask: np.ndarray, min_col_pixels: int = 6) -> list[tuple[int, int]]:
    projection = (mask > 0).sum(axis=0)
    active = projection >= min_col_pixels
    spans: list[tuple[int, int]] = []
    start = None
    for idx, on in enumerate(active):
        if on and start is None:
            start = idx
        elif not on and start is not None:
            spans.append((start, idx))
            start = None
    if start is not None:
        spans.append((start, len(active)))
    return spans


def _merge_close_spans(spans: list[tuple[int, int]], max_gap: int = 8) -> list[tuple[int, int]]:
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _split_wide_spans(mask: np.ndarray, spans: list[tuple[int, int]], target_count: int) -> list[tuple[int, int]]:
    spans = spans[:]
    while len(spans) < target_count:
        widths = [end - start for start, end in spans]
        if not widths:
            break
        idx = int(np.argmax(widths))
        start, end = spans[idx]
        if end - start < 24:
            break
        region = (mask[:, start:end] > 0).sum(axis=0)
        if len(region) < 6:
            break
        mid_start = len(region) // 4
        mid_end = (3 * len(region)) // 4
        split_at = int(np.argmin(region[mid_start:mid_end])) + mid_start
        left = (start, start + split_at)
        right = (start + split_at, end)
        if left[1] - left[0] < 6 or right[1] - right[0] < 6:
            break
        spans[idx : idx + 1] = [left, right]
        spans.sort()
    return spans


def _extract_char_regions(mask: np.ndarray, source_gray: np.ndarray, exact_length: int) -> list[np.ndarray]:
    spans = _merge_close_spans(_spans_from_projection(mask))
    spans = _split_wide_spans(mask, spans, exact_length)
    if len(spans) != exact_length:
        return []

    chars: list[np.ndarray] = []
    for start, end in spans:
        region = mask[:, max(0, start - 4) : min(mask.shape[1], end + 4)]
        ys, xs = np.where(region > 0)
        if len(xs) == 0 or len(ys) == 0:
            return []
        x0, x1 = xs.min(), xs.max() + 1
        y0, y1 = ys.min(), ys.max() + 1
        base_x = max(0, start - 4)
        crop_x0 = base_x + max(0, x0 - 2)
        crop_x1 = base_x + min(region.shape[1], x1 + 2)
        crop_y0 = max(0, y0 - 4)
        crop_y1 = min(region.shape[0], y1 + 4)
        chars.append(source_gray[crop_y0:crop_y1, crop_x0:crop_x1])
    return chars


def _ocr_array(reader, arr: np.ndarray) -> list[tuple[str, float]]:
    rgb = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
    detections = reader.readtext(
        rgb,
        detail=1,
        paragraph=False,
        rotation_info=[0],
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    )
    out = []
    for _, text, conf in detections:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", text or "").strip()
        if cleaned:
            out.append((cleaned, float(conf)))
    return out


def _ocr_single_char(reader, crop: np.ndarray) -> tuple[str, float]:
    best_char = ""
    best_conf = 0.0
    variants: list[np.ndarray] = [crop, cv2.bitwise_not(crop)]
    _, otsu = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.extend([otsu, cv2.bitwise_not(otsu)])

    for variant in variants:
        canvas = np.full((96, 96), 255, dtype=np.uint8)
        scale = min(72 / max(variant.shape[0], 1), 72 / max(variant.shape[1], 1))
        resized = cv2.resize(
            variant,
            (max(1, int(variant.shape[1] * scale)), max(1, int(variant.shape[0] * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
        y = (canvas.shape[0] - resized.shape[0]) // 2
        x = (canvas.shape[1] - resized.shape[1]) // 2
        canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
        for cleaned, conf in _ocr_array(reader, canvas):
            candidate = cleaned[0]
            if conf > best_conf:
                best_char = candidate
                best_conf = conf
    return best_char, best_conf


def _solve_by_segmentation(reader, img_bytes: bytes, exact_length: int) -> tuple[Optional[str], float]:
    source_gray = _gray_upscaled(img_bytes, scale=4)
    mask = _build_segmentation_mask(img_bytes)
    chars = _extract_char_regions(mask, source_gray=source_gray, exact_length=exact_length)
    if not chars:
        logging.info(f"  Segmentation -> no {exact_length}-char split")
        return None, -1e9

    text_parts: list[str] = []
    score = 0.0
    for idx, crop in enumerate(chars, start=1):
        char, conf = _ocr_single_char(reader, crop)
        if not char:
            logging.info(f"    [segmentation] char {idx}: no detection")
            return None, -1e9
        text_parts.append(char)
        score += conf
        logging.info(f"    [segmentation] char {idx}: '{char}' ({conf:.3f})")

    candidate = "".join(text_parts)
    score += 1.2
    logging.info(f"  Segmentation -> '{candidate}' ({score:.3f})")
    return candidate, score


def solve_captcha(
    img_bytes: bytes,
    max_attempts: int = 10,
    debug: bool = False,
    confidence_threshold: float = 0.85,
    min_length: int = 4,
    exact_length: int = 6,
) -> Optional[str]:
    reader = _get_reader()
    variants = _prepare_variants(img_bytes)[:max_attempts]

    if debug:
        _save_debug(img_bytes, variants)

    best_text = None
    best_score = -1e9

    for attempt_idx, (label, processed) in enumerate(variants, start=1):
        logging.info(f"  Captcha attempt {attempt_idx}/{len(variants)} [{label}]...")
        try:
            hits = _ocr_array(reader, processed)
        except Exception as e:
            logging.warning(f"    OCR error: {e}")
            continue

        if not hits:
            logging.info("    -> no text detected")
            continue

        raw_hits = [text for text, _ in hits]
        logging.info(f"    -> {raw_hits}")
        for cleaned, conf in hits:
            candidate = cleaned[:exact_length] if len(cleaned) > exact_length else cleaned
            score = conf
            if len(candidate) == exact_length:
                score += 1.0
            if candidate.isalnum():
                score += 0.3
            if len(candidate) >= min_length:
                score += 0.1

            if score > best_score:
                best_score = score
                best_text = candidate

            if len(candidate) == exact_length and candidate.isalnum() and conf >= confidence_threshold:
                logging.info(f"  Accepted on attempt {attempt_idx}: '{candidate}' ({conf:.3f})")
                return candidate

    segmented_text, segmented_score = _solve_by_segmentation(reader, img_bytes, exact_length=exact_length)
    if segmented_text and segmented_score > best_score:
        logging.info(f"  Best segmented result: '{segmented_text}' ({segmented_score:.3f})")
        return segmented_text

    if best_text and len(best_text) >= min_length:
        logging.info(f"  Best result after {len(variants)} attempts: '{best_text}' ({best_score:.3f})")
        return best_text

    logging.error("  All captcha attempts failed - returning None.")
    return None


def main():
    from common import BASE_URL, CAPTCHA_URL

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Test the EasyOCR captcha solver.")
    parser.add_argument("--image", default=None, help="Path to a local captcha PNG/JPEG")
    parser.add_argument("--attempts", type=int, default=10, help="Max preprocessing attempts")
    parser.add_argument("--debug", action="store_true", help="Save each preprocessed image to captcha_debug/")
    args = parser.parse_args()

    if args.image:
        print(f"Loading captcha from: {args.image}")
        with open(args.image, "rb") as f:
            img_bytes = f.read()
    else:
        print("Fetching live captcha from eProcure...")
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0"
        session.get(f"{BASE_URL}?page=FrontEndLogin&service=page", timeout=15)
        resp = session.get(CAPTCHA_URL, timeout=15)
        img_bytes = resp.content
        with open("captcha_latest.png", "wb") as f:
            f.write(img_bytes)
        print("  Saved raw captcha -> captcha_latest.png")

    result = solve_captcha(img_bytes, max_attempts=args.attempts, debug=args.debug)
    print(f"\nFinal answer: '{result}'")
    if args.debug:
        print("Debug images saved to captcha_debug/")


if __name__ == "__main__":
    main()
