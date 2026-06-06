"""Vercel serverless function: POST /api/generate

Body (JSON): the (reviewed/edited) patent data plus a "forms" list, e.g.
  { "forms": ["1","2","3","5"], "title_of_invention": "...", ... }

Returns a single .docx when one form is requested, otherwise a .zip bundle.
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _forms import fill_form, build_zip, FORMS  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _slug(data):
    base = data.get("international_application_no") or data.get("title_of_invention") or "PCT"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") or "PCT"


class handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, content, mime, filename):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")

            forms = [str(f) for f in (data.get("forms") or ["1"]) if str(f) in FORMS]
            if not forms:
                self._send_json(400, {"error": "No valid forms selected."})
                return

            slug = _slug(data)
            if len(forms) == 1:
                self._send_file(fill_form(forms[0], data), DOCX_MIME, f"{slug}_Form_{forms[0]}.docx")
            else:
                self._send_file(build_zip(forms, data), "application/zip", f"{slug}_Forms.zip")
        except Exception as e:  # noqa: BLE001
            self._send_json(500, {"error": str(e)})
