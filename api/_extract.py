"""
Data extraction for the PCT Form 1 filler.

Two complementary sources are supported (you can combine them):

  * A PCT / WO number  -> Gemini is asked to read the PatentScope bibliographic
    HTML page (and, for the priority title, the WIPO priority document) using
    the url_context + google_search tools.
  * One or more uploaded PDFs (RO/101, IB-306, ISR, priority document) which are
    passed to Gemini inline.

The result is the structured JSON the front-end review form edits before it is
sent to /api/generate.

Requirements baked into the prompt:
  1. Latest applicant / inventor / title from the HTML page (not RO/101).
  2. Addresses keep a comma before the country name (ISR / IB-306 style).
  3. Priority country / number / filing date from the HTML page; priority TITLE
     only for English-language priority applications.
  4. PCT number + international filing date from the HTML page.
"""

import json
import os
import re

try:
    from _scrape import scrape_patent
except ImportError:  # when imported as a package
    from ._scrape import scrape_patent

MODEL = "gemini-2.5-flash"


def _load_dotenv():
    """Load KEY=VALUE pairs from a local .env (filler/.env) into os.environ.

    Vercel injects real environment variables, so this is a no-op there; it only
    matters for local runs where the key lives in .env rather than the shell.
    Existing environment variables always win.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
    except OSError:
        pass


_load_dotenv()

RESPONSE_SHAPE = """
{
  "title_of_invention": "string",
  "international_application_no": "string",        // PCT number, e.g. PCT/IB2023/062067
  "international_filing_date": "string",           // DD/MM/YYYY
  "international_publication_no": "string",         // WO number if published
  "priority_details": {
    "country": "string",                            // 2-letter or full country
    "application_number": "string",
    "filing_date": "string",                        // DD/MM/YYYY
    "applicant_name": "string",
    "title": "string",                              // ONLY for English priority apps, else ""
    "ipc": "string"
  },
  "applicants": [
    { "name": "string", "nationality": "string", "country_of_residence": "string", "address": "string" }
  ],
  "category_of_applicant": "string",               // "Natural Person" or "Other than Natural Person"
  "inventors": [
    { "name": "string", "nationality": "string", "country_of_residence": "string", "address": "string" }
  ],
  "description_pages": 0,
  "claims_pages_listed": 0,
  "abstract_pages_listed": 0,
  "drawings_pages_listed": 0
}
"""

PROMPT = """You are a meticulous patent paralegal extracting bibliographic data to
fill an Indian Patent Office FORM 1 for the PCT national-phase entry of an
international (PCT) application.

Extract the data and return ONLY a single JSON object matching this exact shape
(no markdown, no commentary):
""" + RESPONSE_SHAPE + """

Rules — follow precisely:
1. Use the LATEST recorded applicant(s), inventor(s) and title of invention as
   shown on the WIPO PatentScope bibliographic (HTML) page. If a published
   pamphlet / IB-306 differs from RO/101, prefer the published bibliographic
   data. Names of applicants and inventors must reflect the most recent record.
2. ADDRESSES: always keep a comma immediately before the country name, e.g.
   "12 Main Street, Tokyo 100-0001, Japan". Use the address exactly as it
   appears on the ISR or, if the application is published, the IB-306 / front
   page. Combine "First LAST" name order for inventors.
3. PRIORITY: provide the priority country, application number and filing date
   from the bibliographic page. Provide the priority application TITLE ONLY when
   the priority application was filed in English (e.g. US, GB, AU, CA, IN, NZ,
   SG). For non-English priority applications leave "title" as "".
4. PCT number and international filing date come from the bibliographic page.
5. category_of_applicant: "Other than Natural Person" if any applicant name
   contains company indicators (LTD, LIMITED, INC, CORP, GMBH, LLC, CO, KK,
   UNIVERSITY, INSTITUTE, AB, BV, SA, PLC); otherwise "Natural Person".
6. For page counts, use the number of sheets/pages of description, claims,
   abstract and drawings if present in the documents; use 0 if unknown.
7. If a value is unknown, use "" (or 0 for integers). Never invent data.
"""


def _api_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _client():
    api_key = _api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Add it in your Vercel project settings (or a local .env)."
        )
    from google import genai
    return genai.Client(api_key=api_key)


def _strip_json(text: str) -> dict:
    text = text.strip()
    # Remove ```json ... ``` fences if present.
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # Grab the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def extract_patent_data(pct_number: str = "", pdfs: list = None, biblio_text: str = "") -> dict:
    """Extract bibliographic data for the review form.

    Sources, in order of preference:
      1. PatentScope rendered text (`biblio_text`, scraped by the browser) — the
         authoritative "latest data". When present it is the Gemini source and
         the Google Patents fallback is skipped.
      2. Google Patents structured scrape — only as a key-free fallback when no
         PatentScope text was supplied (it resolves WO/publication numbers).
      3. Gemini fills the gaps (addresses, nationality, priority, page counts)
         from the PatentScope text and/or any attached PDFs.

    Never fatal on a missing key. Returns the structured dict (always) with a
    "_meta.notes" list describing what happened.
    """
    pdfs = pdfs or []
    notes = []

    scraped = {}
    if biblio_text:
        notes.append("Using PatentScope-rendered bibliographic text as the source.")
    elif pct_number:
        # Fallback only — Google Patents may lag the live PatentScope record.
        scraped, snote = scrape_patent(pct_number)
        notes.append("PatentScope text unavailable; " + snote)

    gemini = {}
    if _api_key():
        if pct_number or pdfs or biblio_text:
            try:
                gemini = _gemini_extract(pct_number, pdfs, biblio_text)
                notes.append("Gemini extraction succeeded.")
            except Exception as e:  # noqa: BLE001
                notes.append(f"Gemini extraction failed ({e.__class__.__name__}: {e}).")
    else:
        notes.append(
            "GEMINI_API_KEY not set - used scraping only. "
            "Add it (Vercel env var or local .env) to auto-fill the remaining "
            "fields; otherwise complete them manually below."
        )

    data = _post_process(_merge(scraped, gemini))

    # If nothing meaningful came back, say so clearly (an empty form otherwise
    # looks like a silent failure). The usual cause: a PCT/application number was
    # entered (Google Patents only resolves WO/publication numbers) and Gemini's
    # url_context cannot read the JavaScript-rendered PatentScope page.
    if not data.get("title_of_invention") and not data.get("applicants"):
        notes.append(
            "No bibliographic data found. Tip: enter the WO PUBLICATION number "
            "(e.g. WO2024116111) — those resolve reliably — or attach the RO/101 / "
            "ISR PDF, then review/fill the form manually."
        )

    data["_meta"] = {
        "notes": notes,
        "scraped": bool(scraped),
        "gemini": bool(gemini),
    }
    return data


def _gemini_extract(pct_number: str = "", pdfs: list = None, biblio_text: str = "") -> dict:
    """pdfs: list of (mime_type, bytes). Returns the structured dict from Gemini."""
    from google.genai import types

    client = _client()
    pdfs = pdfs or []

    contents = []
    for mime, raw in pdfs:
        contents.append(types.Part.from_bytes(data=raw, mime_type=mime or "application/pdf"))

    prompt = PROMPT
    config_kwargs = {}

    if biblio_text:
        # We already have the rendered PatentScope page — feed it directly and
        # skip the browsing tools (url_context can't read the JS-rendered page).
        prompt += (
            "\n\nRendered text of the WIPO PatentScope bibliographic page for "
            "this application (use this as the authoritative latest data):\n\n"
            + biblio_text[:200000]
        )
        if pct_number:
            prompt += f"\n\nThe international / publication number is: {pct_number}"
    elif pct_number:
        prompt += (
            f"\n\nThe international application / publication number is: {pct_number}\n"
            "Find its WIPO PatentScope bibliographic page "
            "(https://patentscope.wipo.int/search/en/) and read it. "
            "If a priority title is required (English priority application), also "
            "read the priority document published on WIPO to obtain that title."
        )
        # Let the model browse to read the live bibliographic page.
        config_kwargs["tools"] = [
            types.Tool(url_context=types.UrlContext()),
            types.Tool(google_search=types.GoogleSearch()),
        ]

    contents.append(prompt)

    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=config,
    )

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise RuntimeError("Gemini returned no text (tool-only or blocked response).")
    data = _strip_json(text)
    return _post_process(data)


def _name_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _merge_people(base: list, extra: list) -> list:
    """Scraped people are the base; enrich each from the matching Gemini person
    (by name) for any empty sub-field, then append Gemini-only people."""
    base = [dict(p) for p in (base or [])]
    extra = list(extra or [])
    if not base:
        return extra
    by_key = {_name_key(p.get("name", "")): p for p in base if p.get("name")}
    used = set()
    for ep in extra:
        k = _name_key(ep.get("name", ""))
        target = by_key.get(k)
        if target:
            used.add(k)
            for field in ("nationality", "country_of_residence", "address"):
                if not target.get(field) and ep.get(field):
                    target[field] = ep[field]
    for ep in extra:
        if _name_key(ep.get("name", "")) not in by_key:
            base.append(ep)
    return base


def _merge(scraped: dict, gemini: dict) -> dict:
    """Scraped data is the base; Gemini fills only what scraping left empty."""
    if not gemini:
        return dict(scraped or {})
    if not scraped:
        return dict(gemini)

    out = dict(scraped)
    scalar_fields = (
        "title_of_invention", "international_application_no",
        "international_filing_date", "international_publication_no",
        "publication_date", "category_of_applicant", "abstract_text",
    )
    for f in scalar_fields:
        if not out.get(f) and gemini.get(f):
            out[f] = gemini[f]

    # Priority details: per-key fill-if-empty.
    sp = dict(scraped.get("priority_details") or {})
    gp = gemini.get("priority_details") or {}
    for k, v in gp.items():
        if not sp.get(k) and v:
            sp[k] = v
    out["priority_details"] = sp

    out["applicants"] = _merge_people(scraped.get("applicants"), gemini.get("applicants"))
    out["inventors"] = _merge_people(scraped.get("inventors"), gemini.get("inventors"))

    # Page counts: scraping cannot read sheet counts, so take Gemini's.
    for k in ("description_pages", "claims_pages_listed",
              "abstract_pages_listed", "drawings_pages_listed"):
        if not out.get(k) and gemini.get(k):
            out[k] = gemini[k]
    return out


def _post_process(data: dict) -> dict:
    """Light normalisation so the front-end always gets a complete shape."""
    data.setdefault("title_of_invention", "")
    data.setdefault("international_application_no", "")
    data.setdefault("international_filing_date", "")
    data.setdefault("category_of_applicant", "")
    data.setdefault("applicants", [])
    data.setdefault("inventors", [])
    pr = data.setdefault("priority_details", {})
    for k in ("country", "application_number", "filing_date", "applicant_name", "title", "ipc"):
        pr.setdefault(k, "")
    for k in ("description_pages", "claims_pages_listed", "abstract_pages_listed", "drawings_pages_listed"):
        try:
            data[k] = int(data.get(k) or 0)
        except (TypeError, ValueError):
            data[k] = 0
    # Convenience comma-joined applicant name.
    names = [a.get("name", "") for a in data.get("applicants", []) if a.get("name")]
    data["applicant_name"] = ", ".join(names)
    return data
