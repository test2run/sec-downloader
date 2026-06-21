# EDGAR Filing Downloader — Setup & Usage

## What this does
Downloads SEC filings (10-K, 10-Q, 8-K, DEF 14A, S-1) for any US-listed ticker and saves them as HTML files (default) or PDFs (opt-in) with clean, consistent filenames.

**Default output** (HTML, fast):
```
~/SEC_Filings/AAPL/
├── AAPL_10K_AnnualReport_FY2024.html
├── AAPL_10Q_FirstQuarter_1Q2025.html
├── AAPL_10Q_FourthQuarter_4Q2024.html
├── AAPL_8K_CurrentReport_2025-03-15.html
├── AAPL_DEF14A_ProxyStatement_2025.html
└── ...
```

**With `--pdf`** (slower, see note below):
```
~/SEC_Filings/AAPL/
├── AAPL_10K_AnnualReport_FY2024.pdf
└── ...
```

---

## Setup (one-time, ~5 minutes)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```
PDF conversion renders filings with **headless Chromium via Playwright**
(`playwright install chromium` downloads the browser). On Linux servers, install
Chromium's OS libraries too with `playwright install --with-deps chromium`.

A pure-Python **WeasyPrint** fallback is used automatically if Chromium fails. It
needs a couple of system libs if you want the fallback to work:
- **macOS:** `brew install pango`
- **Linux/WSL:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`
- **Windows:** see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows

### 2. Update the User-Agent
Open `edgar.py` and edit line ~34:
```python
USER_AGENT = "EDGAR Downloader yourname@youremail.com"
```
SEC requires this — they will throttle/block requests without a real contact.

### 3. Test
```bash
python edgar.py AAPL --years 1 --forms 10-K
```
Should download Apple's most recent 10-K as an HTML file to `~/SEC_Filings/AAPL/`.

---

## Usage

### Basic
```bash
python edgar.py AAPL                  # all defaults: 10 years, all 5 form types, HTML output
python edgar.py AAPL MSFT NVDA        # batch multiple tickers
```

### Customize
```bash
python edgar.py AAPL --years 5                  # only last 5 years
python edgar.py AAPL --forms 10-K 10-Q          # only annuals + quarterlies
python edgar.py AAPL --output ~/Documents/SEC   # custom output dir
python edgar.py AAPL --save-html                # also keep original HTML when using --pdf
python edgar.py AAPL --pdf                      # convert to PDF (slower — see note below)
```

### All options
```bash
python edgar.py --help
```

---

## PDF conversion note

By default, filings are saved as **HTML files** that open in any browser. This is fast and reliable.

Checking **Convert to PDF** in the web UI produces real PDFs. Rendering is done in this order, per filing, so it stays reliable on a 512 MB host:
1. **Cloudflare Browser Rendering** (off-box, recommended) — if `CF_ACCOUNT_ID` and `CF_API_TOKEN` are set, the filing is rendered by Cloudflare's hosted browser. This is the robust path: real browser fidelity even for large filings, and it never stresses the web host's memory. See **Cloudflare setup** below.
2. **On-box Chromium fallback** — used when Cloudflare isn't configured or its daily budget is spent. Runs in an isolated subprocess; filings whose HTML exceeds `PDF_MAX_HTML_MB` (default **6 MB**) are delivered as HTML instead, since the largest docs risk an out-of-memory crash on 512 MB.
3. **HTML fallback** — if neither renderer succeeds, the filing is saved as `.html` (or `_PDF_FAILED.html`) so you can still read it. The job always completes.

Notes:
- Typically **5–15 seconds per filing**; a 10-year multi-form request may take **several minutes**.
- Tunable env vars: `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_PDF_TIMEOUT` (Cloudflare); `PDF_MAX_HTML_MB` (on-box size guard), `RENDER_SUBPROCESS_TIMEOUT` (on-box per-render seconds).

### Cloudflare setup (free tier)
Cloudflare's **Workers Free** plan includes **10 minutes of browser time/day and 3 concurrent browsers** at no charge — enough for typical use; heavier days fall back to the on-box path automatically.
1. In the Cloudflare dashboard: **My Profile ▸ API Tokens ▸ Create Custom Token**, grant **Account ▸ Browser Rendering ▸ Edit**, and copy the token.
2. Find your **Account ID** (dashboard account home / URL).
3. In **Render ▸ your service ▸ Environment**, add `CF_ACCOUNT_ID` and `CF_API_TOKEN`.

Until those are set, PDF uses the on-box fallback (fine for typical-size filings).

---

## Web UI

The app is hosted at [sec-downloader.onrender.com](https://sec-downloader.onrender.com). Enter a ticker, choose filing types, enter the number of years of history (1–20, defaults to 10), optionally check **Convert to PDF**, and click Download ZIP.

---

## Render deployment

The app is configured in `render.yaml`. PDF conversion uses Chromium, whose browser binary and OS libraries are installed during the build phase.

**Build command:**
```
pip install -r requirements.txt && playwright install --with-deps chromium
```

**Start command:**
```
gunicorn app:app --workers 1 --threads 4 --timeout 120
```

> **Note on the free tier:** the 512 MB free plan is enough for HTML downloads and on-box PDF conversion of typical filings. For reliable PDF conversion of *large* filings without upgrading RAM, configure **Cloudflare Browser Rendering** (see the PDF conversion note) — it renders off-box on Cloudflare's free tier. Optionally set `CF_ACCOUNT_ID` and `CF_API_TOKEN` here in the environment.

---

## Integrate with Claude Code (one-click experience)

### Option A: Shell alias (simplest)
Add to your `~/.zshrc` or `~/.bashrc`:
```bash
alias edgar='python ~/scripts/edgar.py'
```
Then anywhere: `edgar AAPL` works.

### Option B: Claude Code slash command
Create `~/.claude/commands/edgar.md`:
```markdown
Run the EDGAR downloader for the ticker(s) the user provides.

Usage: /edgar AAPL [MSFT NVDA ...] [--years N] [--forms FORM1 FORM2 ...]

Execute: python ~/scripts/edgar.py {arguments}
Then show the user the resulting folder contents.
```
Now in any Claude Code session, `/edgar AAPL` triggers it.

---

## Notes & limitations

- **Filing types covered:** 10-K, 10-Q, 8-K, DEF 14A, S-1 by default. Add/remove via `--forms`. Any EDGAR form code works (e.g. `S-4`, `20-F`, `13F-HR`).
- **HTML output:** Files open directly in any browser. All text and tables render correctly.
- **PDF quality:** Filings render on A4 via headless Chromium, so layout closely matches the browser. Most filings look good; very large filings are memory-intensive (see PDF conversion note).
- **Foreign filers:** US-listed foreign companies file 20-F (annual) and 6-K instead of 10-K/10-Q. Use `--forms 20-F 6-K` for those (e.g. `python edgar.py BABA --forms 20-F 6-K`).
- **Rate limits:** Script sleeps 0.11s between requests (~6 req/sec), well under SEC's 10 req/sec cap.
- **Resume support:** If a file already exists, it's skipped — safe to re-run.
- **Older filings:** SEC's "recent" feed covers ~1000 most-recent filings. For very high-volume filers (e.g. large funds), the script auto-loads older batches.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `403 Forbidden` | Update `USER_AGENT` with a real email |
| PDF conversion errors / worker crashes | Large filing exceeded available RAM (Chromium OOM). Use HTML mode or a host with ≥1 GB RAM. Run `playwright install --with-deps chromium` if Chromium itself won't launch. |
| Ticker not found | Use the exact SEC ticker (e.g. `BRK-B` not `BRKB`); check `https://www.sec.gov/cgi-bin/browse-edgar` |
| PDF looks broken | The `_PDF_FAILED.html` fallback file will be in the ZIP — open it in a browser |
| Internal server error on Render | Ensure the build command runs `playwright install --with-deps chromium` (see Render deployment section). For large filings, see the memory note. |
