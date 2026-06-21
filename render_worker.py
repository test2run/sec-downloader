#!/usr/bin/env python3
"""
Isolated single-filing PDF renderer (on-box fallback).
======================================================
Renders ONE filing's HTML to a PDF in its own short-lived process. The web app
invokes this via subprocess so that a Chromium crash/hang fails *inside this child*
(catchable: non-zero exit / timeout) instead of taking down the gunicorn worker.
This is the on-box fallback used when Cloudflare Browser Rendering is unavailable.

NOTE: we deliberately do NOT cap virtual memory here. Chromium reserves multi-GB
of virtual address space that is never physically used, so an RLIMIT_AS cap would
abort every launch.

Usage:
    python render_worker.py <input_html_path> <base_url> <output_pdf_path>

Exit codes:
    0  -> wrote a valid PDF to <output_pdf_path>
    !0 -> rendering failed (timeout, crash, empty output, ...)
          The parent should fall back to delivering the original HTML.
"""

import sys


def main():
    if len(sys.argv) != 4:
        print("usage: render_worker.py <input_html> <base_url> <output_pdf>", file=sys.stderr)
        return 2

    in_path, base_url, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    try:
        from edgar import html_to_pdf_bytes
        with open(in_path, "rb") as f:
            html_bytes = f.read()
        pdf_bytes = html_to_pdf_bytes(html_bytes, base_url)
        if not pdf_bytes:
            print("[render_worker] empty PDF output", file=sys.stderr)
            return 1
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
        return 0
    except Exception as e:
        print(f"[render_worker] render failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
