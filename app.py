import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile

from flask import Flask, after_this_request, jsonify, render_template, request, send_file


def ensure_chromium_installed():
    """Make sure Playwright's Chromium binary is present. If not, install it.
    This is idempotent — Playwright skips the download if the binary is already cached.
    Runs at app startup so the build step is no longer load-bearing."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Probe whether the executable exists by asking Playwright for its path.
            exe_path = p.chromium.executable_path
            if exe_path and os.path.exists(exe_path):
                print(f"[startup] Chromium present at {exe_path}", flush=True)
                return
        print("[startup] Chromium missing — running 'playwright install chromium'...", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            print("[startup] Chromium install succeeded.", flush=True)
        else:
            print(f"[startup] Chromium install FAILED (rc={result.returncode})", flush=True)
            print(f"[startup] stdout: {result.stdout}", flush=True)
            print(f"[startup] stderr: {result.stderr}", flush=True)
    except Exception as e:
        print(f"[startup] ensure_chromium_installed errored: {e}", flush=True)


ensure_chromium_installed()

from edgar import (
    RATE_LIMIT_DELAY,
    load_ticker_map, resolve_ticker,
    get_filings, filter_filings,
    build_filename, filing_url, download_html,
    html_to_pdf_bytes,
)

app = Flask(__name__)

_ticker_map = None
jobs = {}

def get_ticker_map():
    global _ticker_map
    if _ticker_map is None:
        _ticker_map = load_ticker_map()
    return _ticker_map

ALL_FORMS = ["10-K", "10-Q", "8-K", "DEF 14A", "S-1"]

@app.route("/")
def index():
    return render_template("index.html", forms=ALL_FORMS)

def run_download(job_id, ticker, cik, forms, years, convert_pdf=False):
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp_path = tmp.name
        tmp.close()

        all_filings = get_filings(cik)
        filtered = filter_filings(all_filings, forms, years)

        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filing in filtered:
                try:
                    if not filing.get("primary_doc"):
                        continue
                    url = filing_url(cik, filing["accession"], filing["primary_doc"])
                    base_url = url.rsplit("/", 1)[0] + "/"
                    time.sleep(RATE_LIMIT_DELAY)
                    html = download_html(url)

                    if convert_pdf:
                        fname = build_filename(ticker, filing)  # .pdf extension
                        try:
                            pdf = html_to_pdf_bytes(html, base_url)
                            zf.writestr(fname, pdf)
                            del pdf
                        except Exception as pdf_err:
                            print(f"PDF conversion failed for {fname}: {pdf_err}")
                            zf.writestr(fname.replace(".pdf", "_PDF_FAILED.html"), html)
                    else:
                        fname = build_filename(ticker, filing).replace(".pdf", ".html")
                        zf.writestr(fname, html)

                    del html
                except Exception:
                    pass

        jobs[job_id] = {"status": "done", "path": tmp_path, "filename": f"{ticker}_SEC_Filings.zip"}
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        jobs[job_id] = {"status": "error"}

@app.route("/download", methods=["POST"])
def download():
    ticker = request.form.get("ticker", "").strip().upper()
    forms = request.form.getlist("forms")
    try:
        years = max(1, min(20, int(request.form.get("years", 10))))
    except ValueError:
        years = 10

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
    except Exception:
        return render_template("index.html", forms=ALL_FORMS,
                               error="Could not reach SEC EDGAR. Please try again in a moment.")

    convert_pdf = request.form.get("convert_pdf") == "1"

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}

    thread = threading.Thread(target=run_download, args=(job_id, ticker, cik, forms, years, convert_pdf))
    thread.daemon = True
    thread.start()

    return render_template("processing.html", job_id=job_id, ticker=ticker, convert_pdf=convert_pdf)

@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id, {"status": "not_found"})
    return jsonify({"status": job["status"]})

@app.route("/result/<job_id>")
def result(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return "File not ready or not found.", 404

    path = job["path"]
    filename = job["filename"]

    @after_this_request
    def cleanup(response):
        try:
            os.unlink(path)
        except Exception:
            pass
        jobs.pop(job_id, None)
        return response

    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
