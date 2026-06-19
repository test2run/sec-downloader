#!/usr/bin/env python3
"""
Isolated single-filing PDF renderer.
=====================================
Renders ONE filing's HTML to a PDF in its own short-lived process, with a hard
memory cap (RLIMIT_AS on POSIX). The web app invokes this via subprocess so that
a runaway Chromium render fails *inside this child* (catchable: non-zero exit)
instead of triggering the OS OOM-killer against the gunicorn worker.

Usage:
    python render_worker.py <input_html_path> <base_url> <output_pdf_path>

Exit codes:
    0  -> wrote a valid PDF to <output_pdf_path>
    !0 -> rendering failed (memory cap hit, timeout, crash, empty output, ...)
          The parent should fall back to delivering the original HTML.
"""

import sys


def _apply_memory_cap():
    """Cap this process's address space so an over-budget render fails cleanly
    here rather than OOM-killing the parent. POSIX only; a no-op elsewhere."""
    try:
        import resource  # POSIX only
        from edgar import RENDER_MEM_LIMIT_MB
        limit = RENDER_MEM_LIMIT_MB * 1024 * 1024
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        new_hard = hard if hard != resource.RLIM_INFINITY else limit
        resource.setrlimit(resource.RLIMIT_AS, (limit, new_hard))
    except Exception as e:
        # Non-POSIX (e.g. Windows dev box) or unsupported — proceed uncapped.
        print(f"[render_worker] memory cap not applied: {e}", file=sys.stderr)


def main():
    if len(sys.argv) != 4:
        print("usage: render_worker.py <input_html> <base_url> <output_pdf>", file=sys.stderr)
        return 2

    in_path, base_url, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    _apply_memory_cap()

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
