import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def debug_one(url: str, outdir: Path, headless: bool = False, timeout_ms: int = 180_000):
    outdir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            channel="chrome",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
            locale="es-MX",
        )

        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        logs = {
            "url": url,
            "base_bootstrap_url": None,
            "nav_status": None,
            "final_url": None,
            "title": None,
            "page_errors": [],
            "console": [],
            "request_failed": [],
            "http_errors": [],  # <— non-2xx responses
            "paint_check": {},
        }

        page.on("console", lambda msg: logs["console"].append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda err: logs["page_errors"].append(str(err)))

        def on_req_failed(req):
            failure = req.failure()
            # failure can be None, str, or an object/dict depending on version
            if failure is None:
                failure_text = None
            elif isinstance(failure, str):
                failure_text = failure
            elif isinstance(failure, dict):
                failure_text = failure.get("errorText") or failure.get("error_text")
            else:
                failure_text = getattr(failure, "error_text", str(failure))

            logs["request_failed"].append({
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "failure": failure_text,
            })

        page.on("requestfailed", on_req_failed)

        def on_response(resp):
            # capture 4xx/5xx (these can break JS bundles and still not appear as request_failed)
            if resp.status >= 400:
                logs["http_errors"].append({
                    "url": resp.url,
                    "status": resp.status,
                    "resource_type": resp.request.resource_type,
                })

        page.on("response", on_response)

        try:
            # ---- SPA Bootstrap Trick ----
            # Load the app entry first (no hash route), let JS bundles initialize, then go to target route.
            base = "https://comprasmx.buengobierno.gob.mx/sitiopublico/"
            logs["base_bootstrap_url"] = base

            page.goto(base, wait_until="load", timeout=timeout_ms)
            page.wait_for_timeout(3000)

            # Now navigate to the target hash route
            resp = page.goto(url, wait_until="commit", timeout=timeout_ms)

            logs["nav_status"] = resp.status if resp else None

            # Wait for SPA to paint something meaningful
            # (Try a few likely selectors used by Angular/PrimeNG)
            candidates = [
                "app-root",
                "router-outlet",
                "p-table",
                "table[role='table']",
            ]

            painted = False
            for sel in candidates:
                try:
                    page.wait_for_selector(sel, timeout=20_000, state="attached")
                    painted = True
                    break
                except Exception:
                    pass

            # extra buffer for rendering
            page.wait_for_timeout(5000)

            logs["final_url"] = page.url
            logs["title"] = page.title()

            # ---- Paint check ----
            body_html = page.eval_on_selector("body", "el => el.innerHTML") or ""
            body_text = page.eval_on_selector("body", "el => el.innerText") or ""
            logs["paint_check"] = {
                "painted_selector_found": painted,
                "body_html_len": len(body_html),
                "body_text_len": len(body_text.strip()),
                "has_table": page.locator("table").count(),
                "has_role_table": page.locator("table[role='table']").count(),
            }

            safe = "procedimiento_debug"
            ss_path = outdir / f"{safe}.png"
            html_path = outdir / f"{safe}.html"
            json_path = outdir / f"{safe}.json"
            print("has app-root:", page.locator("app-root").count())
            print("has router-outlet:", page.locator("router-outlet").count())
            print("body length:", len(page.content()))

            page.screenshot(path=str(ss_path), full_page=True)
            html_path.write_text(page.content(), encoding="utf-8", errors="ignore")
            json_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")

            print("\n=== RESULT ===")
            print("Nav status:", logs["nav_status"])
            print("Title:", logs["title"])
            print("HTTP errors:", len(logs["http_errors"]))
            print("Request failed:", len(logs["request_failed"]))
            print("Paint check:", logs["paint_check"])
            print("Saved:", ss_path, html_path, json_path)

        except PWTimeout as e:
            logs["page_errors"].append(f"Timeout: {e}")
            print("TIMEOUT:", url)

        finally:
            context.close()
            browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--outdir", default="output/debug")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    debug_one(args.url, Path(args.outdir), headless=args.headless)


if __name__ == "__main__":
    main()
