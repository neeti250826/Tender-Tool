from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headful to verify visually
        page = browser.new_page()
        page.goto("https://comprasmx.buengobierno.gob.mx/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        browser.close()

if __name__ == "__main__":
    main()