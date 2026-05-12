# EDGAR Filing Downloader — Setup & Usage

## What this does
Downloads SEC filings (10-K, 10-Q, 8-K, DEF 14A, S-1) for any US-listed ticker, converts them to PDF, and saves them with clean, consistent filenames into `~/SEC_Filings/{TICKER}/`.

Example output for `python edgar.py AAPL`:
```
~/SEC_Filings/AAPL/
├── AAPL_10K_AnnualReport_FY2024.pdf
├── AAPL_10Q_FirstQuarter_1Q2025.pdf
├── AAPL_10Q_FourthQuarter_4Q2024.pdf
├── AAPL_8K_CurrentReport_2025-03-15.pdf
├── AAPL_DEF14A_ProxyStatement_2025.pdf
└── ...
```

---

## Setup (one-time, ~5 minutes)

### 1. Install Python dependencies
```bash
pip install requests weasyprint
```
WeasyPrint needs a couple of system libs:
- **macOS:** `brew install pango`
- **Linux/WSL:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`
- **Windows:** see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows

### 2. Update the User-Agent
Open `edgar.py` and edit line ~24:
```python
USER_AGENT = "EDGAR Downloader yourname@youremail.com"
```
SEC requires this — they will throttle/block requests without a real contact.

### 3. Test
```bash
python edgar.py AAPL --years 1 --forms 10-K
```
Should download Apple's most recent 10-K to `~/SEC_Filings/AAPL/`.

---

## Usage

### Basic
```bash
python edgar.py AAPL                  # all defaults: 10 years, all 5 form types
python edgar.py AAPL MSFT NVDA        # batch multiple tickers
```

### Customize
```bash
python edgar.py AAPL --years 5                  # only last 5 years
python edgar.py AAPL --forms 10-K 10-Q          # only annuals + quarterlies
python edgar.py AAPL --output ~/Documents/SEC   # custom output dir
python edgar.py AAPL --save-html                # also keep the original HTML
```

### All options
```bash
python edgar.py --help
```

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

### Option C: Cowork
Cowork can run the script through a task. Set up a saved task: "Run edgar.py with ticker {input}" and trigger it from Cowork's UI.

---

## Notes & limitations

- **Filing types covered:** 10-K, 10-Q, 8-K, DEF 14A, S-1 by default. Add/remove via `--forms`. Any EDGAR form code works (e.g. `S-4`, `20-F`, `13F-HR`).
- **PDF quality:** WeasyPrint renders the primary HTML document. For filings with heavy XBRL or external image references, you may see formatting differences vs. the SEC's rendered view. The text and tables come through cleanly.
- **Foreign filers:** US-listed foreign companies file 20-F (annual) and 6-K instead of 10-K/10-Q. Use `--forms 20-F 6-K` for those (e.g. `python edgar.py BABA --forms 20-F 6-K`).
- **Rate limits:** Script sleeps 0.15s between requests (~6 req/sec), well under SEC's 10 req/sec cap.
- **Resume support:** If a file already exists, it's skipped — safe to re-run.
- **Older filings:** SEC's "recent" feed covers ~1000 most-recent filings. For very high-volume filers (e.g. large funds), the script auto-loads older batches.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `403 Forbidden` | Update `USER_AGENT` with a real email |
| `weasyprint` import error | Install system libs (see Setup step 1) |
| Ticker not found | Use the exact SEC ticker (e.g. `BRK-B` not `BRKB`); check `https://www.sec.gov/cgi-bin/browse-edgar` |
| PDF looks broken | Re-run with `--save-html`; open the HTML in a browser to confirm source is fine |
