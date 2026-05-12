import io
import os
import time
import zipfile

from flask import Flask, render_template, request, send_file

from edgar import (
    RATE_LIMIT_DELAY, HEADERS,
    load_ticker_map, resolve_ticker,
    get_filings, filter_filings,
    build_filename, filing_url, download_html,
)

app = Flask(__name__)

_ticker_map = None

def get_ticker_map():
    global _ticker_map
    if _ticker_map is None:
        _ticker_map = load_ticker_map()
    return _ticker_map

ALL_FORMS = ["10-K", "10-Q", "8-K", "DEF 14A", "S-1"]

@app.route("/")
def index():
    return render_template("index.html", forms=ALL_FORMS)

@app.route("/download", methods=["POST"])
def download():
    ticker = request.form.get("ticker", "").strip().upper()
    forms = request.form.getlist("forms")
    try:
        years = max(1, min(10, int(request.form.get("years", 3))))
    except ValueError:
        years = 3

    if not ticker:
        return render_template("index.html", forms=ALL_FORMS, error="Please enter a ticker symbol.")
    if not forms:
        return render_template("index.html", forms=ALL_FORMS, error="Please select at least one filing type.")

    try:
        ticker_map = get_ticker_map()
        cik, company = resolve_ticker(ticker, ticker_map)
    except ValueError:
        return render_template("index.html", forms=ALL_FORMS,
                               error=f"Ticker '{ticker}' not found. Make sure it's a valid US stock ticker.")

    all_filings = get_filings(cik)
    filtered = filter_filings(all_filings, forms, years)

    if not filtered:
        return render_template("index.html", forms=ALL_FORMS,
                               error=f"No filings found for {ticker} with the selected options.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filing in filtered:
            fname = build_filename(ticker, filing).replace(".pdf", ".html")
            url = filing_url(cik, filing["accession"], filing["primary_doc"])
            try:
                time.sleep(RATE_LIMIT_DELAY)
                html = download_html(url)
                zf.writestr(fname, html)
            except Exception:
                pass

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{ticker}_SEC_Filings.zip",
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
