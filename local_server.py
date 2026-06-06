"""
Local development server (no Vercel needed).

    set GEMINI_API_KEY=...        (Windows)   /   export GEMINI_API_KEY=...
    python local_server.py
    -> open http://localhost:8000

Serves the static front-end and the same /api/extract and /api/generate logic
that the Vercel functions use.
"""

import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
# Static front-end lives in public/ (Vercel serves that directory at the root).
PUBLIC = os.path.join(ROOT, "public")
sys.path.insert(0, os.path.join(ROOT, "api"))

from _forms import fill_form, build_zip, FORMS  # noqa: E402
from _extract import extract_patent_data         # noqa: E402

PORT = int(os.environ.get("PORT", "8000"))
STATIC = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter logs
        sys.stderr.write("  " + (a[0] % a[1:]) + "\n")

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        # PatentScope browser scrape (biblio text + RO/101 PDF). No API key needed.
        if path == "/api/scrape":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            doc_id = (qs.get("docId", [""])[0]).strip()
            want_pdf = qs.get("pdf", ["1"])[0] != "0"
            if not doc_id:
                self._json(400, {"ok": False, "error": "docId query parameter is required."})
                return
            try:
                from _browser import scrape_patentscope
                self._json(200, scrape_patentscope(doc_id, want_pdf=want_pdf))
            except Exception as e:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/":
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(PUBLIC, path.lstrip("/")))
        if not fpath.startswith(PUBLIC) or not os.path.isfile(fpath):
            self.send_error(404)
            return
        ext = os.path.splitext(fpath)[1]
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", STATIC.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except Exception:
            self._json(400, {"error": "invalid JSON"})
            return

        try:
            if self.path.startswith("/api/extract"):
                pdfs = []
                for f in req.get("pdfs", []) or []:
                    d = f.get("data", "")
                    if d:
                        pdfs.append((f.get("mime", "application/pdf"), base64.b64decode(d)))
                result = extract_patent_data(
                    pct_number=(req.get("pct_number") or "").strip(),
                    pdfs=pdfs,
                    biblio_text=(req.get("biblio_text") or ""),
                )
                self._json(200, result)
            elif self.path.startswith("/api/generate"):
                forms = [str(f) for f in (req.get("forms") or ["1"]) if str(f) in FORMS]
                if len(forms) <= 1:
                    content = fill_form(forms[0] if forms else "1", req)
                    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    fname = f"Form_{forms[0] if forms else '1'}.docx"
                else:
                    content = build_zip(forms, req)
                    mime = "application/zip"
                    fname = "PCT_Forms.zip"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})


if __name__ == "__main__":
    print(f"Serving http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
