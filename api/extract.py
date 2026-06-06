"""Vercel serverless function: POST /api/extract

Body (JSON):
  {
    "pct_number": "PCT/IB2023/062067",          # optional
    "pdfs": [ {"mime": "application/pdf", "data": "<base64>"} ]   # optional
  }

Returns the structured patent data JSON for the review form.
"""

import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _extract import extract_patent_data  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            req = json.loads(raw or b"{}")

            pct_number = (req.get("pct_number") or "").strip()
            pdfs = []
            for f in req.get("pdfs", []) or []:
                data = f.get("data", "")
                if not data:
                    continue
                if "," in data and data.strip().startswith("data:"):
                    data = data.split(",", 1)[1]
                pdfs.append((f.get("mime", "application/pdf"), base64.b64decode(data)))

            biblio_text = req.get("biblio_text") or ""

            if not pct_number and not pdfs and not biblio_text:
                self._send(400, {"error": "Provide a pct_number and/or at least one PDF."})
                return

            result = extract_patent_data(pct_number=pct_number, pdfs=pdfs, biblio_text=biblio_text)
            self._send(200, result)
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})
