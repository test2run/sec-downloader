#!/usr/bin/env python3
"""
EDGAR Filing Downloader
=======================
Downloads SEC filings for given tickers, names them per convention, and saves as
HTML (default) or PDF (opt-in via --pdf flag).

Usage:
    python edgar.py AAPL
    python edgar.py AAPL MSFT NVDA
    python edgar.py AAPL --years 5 --forms 10-K 10-Q
    python edgar.py AAPL --output ~/Documents/SEC
    python edgar.py AAPL --pdf            # convert to real PDF (slower)

Filename convention:
    {TICKER}_{FORM}_{DescriptiveName}_{Period}.html  (default)
    {TICKER}_{FORM}_{DescriptiveName}_{Period}.pdf   (with --pdf)
    e.g. AAPL_10K_AnnualReport_FY2024.html
         AAPL_10Q_FirstQuarter_1Q2025.html
         AAPL_8K_CurrentReport_2025-03-15.html
"""

import argparse
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
    # Suppress xhtml2pdf's noisy per-property warnings on SEC HTML
    logging.getLogger("xhtml2pdf").setLevel(logging.ERROR)
    logging.getLogger("pisa").setLevel(logging.ERROR)
except ImportError:
    XHTML2PDF_AVAILABLE = False

# ---- CONFIG -----------------------------------------------------------------

# REQUIRED by SEC: User-Agent with name + email. Update this to your info.
USER_AGENT = "EDGAR Downloader Kiran kiranmika24@gmail.com"

DEFAULT_FORMS = ["10-K", "10-Q", "8-K", "DEF 14A", "S-1"]
DEFAULT_YEARS = 10
DEFAULT_OUTPUT = "~/SEC_Filings"

# SEC rate limit: 10 req/sec. We use 0.11s = ~6 req/sec to be safe.
RATE_LIMIT_DELAY = 0.11

HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# CSS injected into SEC filings before PDF conversion.
SEC_PDF_STYLESHEET = """
@page { size: A4 landscape; margin: 1.5cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; }
table { font-size: 8pt; width: 100%; table-layout: auto; }
td, th { padding: 2px !important; word-wrap: break-word; overflow-wrap: break-word; }
img { max-width: 100%; }
"""

# ---- TICKER → CIK LOOKUP ----------------------------------------------------

def load_ticker_map():
    """Fetch SEC's ticker → CIK mapping."""
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    # data is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    return {entry["ticker"].upper(): (str(entry["cik_str"]).zfill(10), entry["title"])
            for entry in data.values()}

def resolve_ticker(ticker, ticker_map):
    ticker = ticker.upper()
    if ticker not in ticker_map:
        raise ValueError(f"Ticker '{ticker}' not found in SEC EDGAR.")
    return ticker_map[ticker]  # (cik_padded, company_name)

# ---- FILING METADATA --------------------------------------------------------

def get_filings(cik):
    """Get all filings metadata for a CIK."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    recent = data["filings"]["recent"]
    filings = []
    for i in range(len(recent["accessionNumber"])):
        filings.append({
            "accession": recent["accessionNumber"][i],
            "form": recent["form"][i],
            "filing_date": recent["filingDate"][i],
            "report_date": recent["reportDate"][i],
            "primary_doc": recent["primaryDocument"][i],
            "primary_desc": recent["primaryDocDescription"][i],
        })

    # Also load older filings from any referenced files
    for older_file in data["filings"].get("files", []):
        time.sleep(RATE_LIMIT_DELAY)
        older_url = f"https://data.sec.gov/submissions/{older_file['name']}"
        try:
            r = requests.get(older_url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            older = r.json()
            for i in range(len(older["accessionNumber"])):
                filings.append({
                    "accession": older["accessionNumber"][i],
                    "form": older["form"][i],
                    "filing_date": older["filingDate"][i],
                    "report_date": older["reportDate"][i],
                    "primary_doc": older["primaryDocument"][i],
                    "primary_desc": older["primaryDocDescription"][i],
                })
        except Exception as e:
            print(f"  ! Could not load older filings batch {older_file['name']}: {e}")

    return filings

# ---- FILENAME GENERATION ----------------------------------------------------

def quarter_from_date(date_str):
    """Given YYYY-MM-DD, return ('1Q', '2025') style tuple."""
    if not date_str:
        return None, None
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    q = (dt.month - 1) // 3 + 1
    return f"{q}Q", str(dt.year)

QUARTER_WORDS = {1: "FirstQuarter", 2: "SecondQuarter", 3: "ThirdQuarter", 4: "FourthQuarter"}

def build_filename(ticker, filing):
    """Build the canonical filename for a filing (always .pdf extension; caller changes to .html if needed)."""
    form = filing["form"]
    form_clean = form.replace("-", "").replace(" ", "").replace("/", "")
    report_date = filing.get("report_date") or filing.get("filing_date")
    filing_date = filing.get("filing_date")

    if form == "10-K":
        year = report_date.split("-")[0] if report_date else filing_date.split("-")[0]
        return f"{ticker}_10K_AnnualReport_FY{year}.pdf"

    if form == "10-Q":
        if report_date:
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            q = (dt.month - 1) // 3 + 1
            qword = QUARTER_WORDS[q]
            return f"{ticker}_10Q_{qword}_{q}Q{dt.year}.pdf"
        return f"{ticker}_10Q_Quarterly_{filing_date}.pdf"

    if form == "8-K":
        return f"{ticker}_8K_CurrentReport_{filing_date}.pdf"

    if form == "DEF 14A":
        year = filing_date.split("-")[0]
        return f"{ticker}_DEF14A_ProxyStatement_{year}.pdf"

    if form == "S-1":
        return f"{ticker}_S1_Registration_{filing_date}.pdf"

    # Fallback
    return f"{ticker}_{form_clean}_{filing_date}.pdf"

# ---- DOWNLOAD & CONVERT ------------------------------------------------------

def filing_url(cik, accession, primary_doc):
    """Build the URL to the primary document."""
    acc_clean = accession.replace("-", "")
    cik_int = int(cik)
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{primary_doc}"

def download_html(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.content

def _strip_table_widths(html_str):
    """Remove inline width attributes from table elements — wide SEC tables cause
    xhtml2pdf to compute sub-1pt cell widths which crash ReportLab layout."""
    return re.sub(
        r'(<(?:table|tbody|thead|tfoot|tr|td|th|col|colgroup)\b[^>]*?)\s+width\s*=\s*(?:"[^"]*"|\'[^\']*\'|\S+)',
        r'\1',
        html_str,
        flags=re.IGNORECASE,
    )

def html_to_pdf_bytes(html_bytes, base_url):
    """Convert HTML bytes to PDF bytes using xhtml2pdf. Returns PDF bytes or raises."""
    if not XHTML2PDF_AVAILABLE:
        raise RuntimeError("xhtml2pdf is not installed. Run: pip install xhtml2pdf")
    html_str = html_bytes.decode("utf-8", errors="replace")
    html_str = _strip_table_widths(html_str)
    style_tag = f"<style>{SEC_PDF_STYLESHEET}</style>"
    html_str = re.sub(r"(<head[^>]*>)", r"\1" + style_tag, html_str, count=1, flags=re.IGNORECASE)
    output = io.BytesIO()
    pisa.CreatePDF(html_str, dest=output, encoding="utf-8", path=base_url)
    pdf_bytes = output.getvalue()
    if not pdf_bytes:
        raise RuntimeError("xhtml2pdf produced empty output")
    return pdf_bytes

def html_to_pdf(html_bytes, _base_url, output_path):
    """Save filing as HTML (open in any browser). Used by CLI without --pdf."""
    html_path = Path(str(output_path).replace(".pdf", ".html"))
    html_path.write_bytes(html_bytes)
    return True

# ---- MAIN --------------------------------------------------------------------

def filter_filings(filings, forms, years):
    """Keep only filings of desired forms within lookback window."""
    cutoff = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    return [f for f in filings if f["form"] in forms and f["filing_date"] >= cutoff]

def process_ticker(ticker, ticker_map, forms, years, output_root, save_html_too=False, use_pdf=False):
    print(f"\n=== {ticker} ===")
    try:
        cik, company = resolve_ticker(ticker, ticker_map)
    except ValueError as e:
        print(f"  ! {e}")
        return

    print(f"  Company: {company}")
    print(f"  CIK: {cik}")

    time.sleep(RATE_LIMIT_DELAY)
    all_filings = get_filings(cik)
    filtered = filter_filings(all_filings, forms, years)
    print(f"  Found {len(filtered)} filings matching criteria (forms={forms}, years={years})")

    out_dir = Path(output_root).expanduser() / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    success, failed = 0, 0
    for filing in filtered:
        base_fname = build_filename(ticker, filing)
        if use_pdf:
            fname = base_fname  # .pdf
        else:
            fname = base_fname.replace(".pdf", ".html")

        out_path = out_dir / fname

        if out_path.exists():
            print(f"  ✓ [skip, exists] {fname}")
            success += 1
            continue

        url = filing_url(cik, filing["accession"], filing["primary_doc"])
        try:
            time.sleep(RATE_LIMIT_DELAY)
            html = download_html(url)
            base = url.rsplit("/", 1)[0] + "/"

            if save_html_too:
                html_fname = base_fname.replace(".pdf", ".html")
                (out_dir / html_fname).write_bytes(html)

            if use_pdf:
                try:
                    pdf = html_to_pdf_bytes(html, base)
                    out_path.write_bytes(pdf)
                    del pdf
                    print(f"  ✓ {fname}")
                    success += 1
                except Exception as e:
                    fail_fname = base_fname.replace(".pdf", "_PDF_FAILED.html")
                    (out_dir / fail_fname).write_bytes(html)
                    print(f"  ! PDF failed, saved HTML fallback: {fail_fname}: {e}")
                    failed += 1
            else:
                out_path.write_bytes(html)
                print(f"  ✓ {fname}")
                success += 1

            del html
        except Exception as e:
            print(f"  ✗ {fname}: {e}")
            failed += 1

    print(f"  Done: {success} succeeded, {failed} failed -> {out_dir}")

def main():
    parser = argparse.ArgumentParser(description="Download SEC EDGAR filings.")
    parser.add_argument("tickers", nargs="+", help="Ticker symbols (e.g. AAPL MSFT)")
    parser.add_argument("--forms", nargs="+", default=DEFAULT_FORMS,
                        help=f"Filing forms (default: {DEFAULT_FORMS})")
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS,
                        help=f"Lookback years (default: {DEFAULT_YEARS})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output root dir (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--save-html", action="store_true",
                        help="Also save the original HTML alongside the output file")
    parser.add_argument("--pdf", action="store_true",
                        help="Convert filings to PDF using WeasyPrint (slower; default is HTML)")
    args = parser.parse_args()

    print("Loading SEC ticker map...")
    ticker_map = load_ticker_map()
    print(f"Loaded {len(ticker_map)} tickers.")

    for ticker in args.tickers:
        process_ticker(ticker, ticker_map, args.forms, args.years,
                       args.output, save_html_too=args.save_html, use_pdf=args.pdf)

    print("\nAll done.")

if __name__ == "__main__":
    main()
