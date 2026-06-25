# Thailand GProcurement Scraper

This guide explains how to run the scraper step-by-step from scratch.

---

## 1. Install Requirements

### Install Python (if not installed)

Download from: [https://www.python.org/downloads/](https://www.python.org/downloads/)

Make sure to check:

* ✅ Add Python to PATH

---

### Install required packages

Open Command Prompt (CMD) and run:

```
pip install playwright
playwright install
```

---

## 2. Start Microsoft Edge with Debug Mode

This step is REQUIRED to bypass Cloudflare.

Open CMD and run:

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="C:\gproc-edge-profile"
```

If that path does not work, try:

```
"C:\Program Files\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="C:\gproc-edge-profile"
```

---

## 3. Open Website and Solve Cloudflare

In the opened Edge browser:

1. Go to:

```
https://process5.gprocurement.go.th/egp-agpc01-web/announcement
```

2. Solve the Cloudflare verification manually

3. Wait until:

* ❌ No "Verification failed"
* ✅ Search button is clickable

IMPORTANT:

* Do NOT close this Edge window

---

## 4. Run the Script

Open another CMD window and navigate to your script folder:

```
cd path\to\your\script
```

Run:

```
python your_script.py
```

Optional:

```
python your_script.py --max-pages 1
```

---

## 5. Output Files

After running, you will get:

* `gprocurement_output.csv`
* `gprocurement_output.jsonl`

These contain:

* Tender list
* Detail page data
* Contract item-level data

---

## 6. Important Notes

* Always start Edge with debug mode BEFORE running script
* Keep Edge open while script runs
* Cloudflare must be solved manually once
* Script uses the same browser session (no blocking)

---

## 7. Troubleshooting

### Error: "msedge.exe not recognized"

Use full path:

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

---

### Error: "pw not defined"

Make sure code uses:

```
async with async_playwright() as pw:
```

---

### No data found

* Ensure Cloudflare is solved
* Ensure search results are visible before running script

---

## 8. How It Works (Simple)

1. Connects to Edge browser (already open)
2. Uses existing session (Cloudflare passed)
3. Searches tenders
4. Clicks each row
5. Extracts detail data
6. Opens contract section
7. Extracts item-level data

---

## 9. Done ✅

You now have a working scraper for Thailand Government Procurement portal.
