"""
Key-free bibliographic scraper for the PCT Form filler.

The goal: pull as much structured data as possible WITHOUT a Gemini API key, so
the review form is pre-filled even when no key is configured (or the key fails).
Whatever cannot be scraped is left blank for the Gemini step / human review.

Why not PatentScope directly?
    https://patentscope.wipo.int/search/en/detail.jsf?docId=WO... returns only a
    PrimeFaces/JSF *shell* (site chrome + a ViewState). The actual bibliographic
    record is injected afterwards by a session-bound AJAX partial render, so a
    plain server-side GET sees no title/applicant/inventor data. Replaying that
    AJAX needs the live jsessionid + ViewState and is brittle.

    Google Patents publishes the SAME WIPO/PCT record fully server-rendered, in
    machine-readable <meta> (Dublin Core / citation_*) tags and microdata. That
    is what we scrape here. The international application number it returns for
    WO2024116111 is PCT/IB2023/062067 - matching the original notebook example.

Public function:
    scrape_patent(number) -> (data: dict, note: str)
        data follows the same shape _extract.py produces (a subset of fields,
        the rest left as "" / 0). note is a short human-readable status string.
"""

import html
import json
import re
import time
import urllib.parse
import urllib.request

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}

# Country codes whose national applications are filed in English -> a priority
# title may be reused (kept in sync with _extract.ENGLISH_FILING intent).
_ENGLISH_PRIORITY = {"US", "GB", "AU", "CA", "IN", "NZ", "SG", "IE", "ZA"}

_COMPANY_HINTS = (
    "LTD", "LIMITED", "INC", "CORP", "GMBH", "LLC", "CO", "KK", "UNIVERSITY",
    "INSTITUTE", "AB", "BV", "SA", "PLC", "PLATFORMS", "TECHNOLOGIES",
)


def _get(url: str, timeout: int = 45, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            # 429/503 are transient throttles - back off and retry.
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    if last:
        raise last
    return ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _iso_to_ddmmyyyy(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else _clean(iso)


def normalize_publication_number(raw: str) -> str:
    """'WO 2024/116111', 'WO2024116111A1' -> 'WO2024116111A1' (kind code kept if given)."""
    s = re.sub(r"[\s/]", "", (raw or "").upper())
    return s


def _google_patents_id(raw: str) -> str:
    """
    Map user input to a Google Patents document id usable as /patent/<id>/en.

    WO publication numbers map directly (kind code optional). For anything else
    (PCT application numbers, national numbers) we ask the Google Patents query
    endpoint to resolve the first matching publication number.
    """
    norm = normalize_publication_number(raw)
    if re.fullmatch(r"WO\d{6,}[A-Z]?\d?", norm):
        return norm
    # Fall back to the query endpoint for non-WO inputs.
    try:
        q = urllib.parse.quote("q=" + raw.strip())
        data = json.loads(_get(f"https://patents.google.com/xhr/query?url={q}&exp="))
        cluster = data.get("results", {}).get("cluster", [{}])
        results = cluster[0].get("result", []) if cluster else []
        if results:
            pub = results[0].get("patent", {}).get("publication_number", "")
            if pub:
                return normalize_publication_number(pub)
    except Exception:
        pass
    return norm


def _metas(h: str, name: str):
    """All <meta name="..."> values (attribute order on Google Patents is name,content[,scheme])."""
    out = []
    for tag in re.findall(r"<meta name=\"%s\"[^>]*>" % re.escape(name), h):
        m = re.search(r'content="([^"]*)"', tag)
        sch = re.search(r'scheme="([^"]*)"', tag)
        if m:
            out.append((html.unescape(m.group(1)), sch.group(1) if sch else ""))
    return out


def _category_for(names) -> str:
    joined = " ".join(names).upper()
    tokens = re.findall(r"[A-Z]+", joined)
    if any(h in tokens for h in _COMPANY_HINTS):
        return "Other than Natural Person"
    return "Natural Person" if names else ""


def scrape_google_patents(number: str) -> dict:
    """Return the bibliographic subset Google Patents exposes server-side."""
    doc_id = _google_patents_id(number)
    page = _get(f"https://patents.google.com/patent/{doc_id}/en")

    title = ""
    for val, _ in _metas(page, "DC.title"):
        title = _clean(val)
        break

    abstract = ""
    for val, _ in _metas(page, "DC.description"):
        abstract = _clean(val)
        break

    inventors, applicants = [], []
    for val, scheme in _metas(page, "DC.contributor"):
        name = _clean(val)
        if not name:
            continue
        if scheme == "inventor":
            inventors.append({"name": name, "nationality": "",
                              "country_of_residence": "", "address": ""})
        elif scheme == "assignee":
            applicants.append({"name": name, "nationality": "",
                              "country_of_residence": "", "address": ""})

    intl_app = ""
    for val, _ in _metas(page, "citation_patent_application_number"):
        intl_app = val.replace(":", "").strip()  # 'PC:T/IB2023/062067' -> 'PCT/IB2023/062067'
        break

    pub_no = ""
    for val, _ in _metas(page, "citation_patent_publication_number"):
        pub_no = val.replace(":", "").strip()      # 'WO:2024116111:A1' -> 'WO2024116111A1'
        break

    # DC.date appears twice: scheme="dateSubmitted" (filing) and a bare one (publication).
    filing_date = publication_date = ""
    for val, scheme in _metas(page, "DC.date"):
        if scheme == "dateSubmitted":
            filing_date = _iso_to_ddmmyyyy(val)
        elif not scheme and not publication_date:
            publication_date = _iso_to_ddmmyyyy(val)

    # Priority date of THIS record. Google Patents renders it first, in the
    # header block, as <time itemprop="priorityDate" datetime="YYYY-MM-DD">;
    # later priorityDate microdata belongs to cited / similar documents, so we
    # take the first occurrence in document order rather than the global minimum.
    pm = re.search(
        r'itemprop="priorityDate"[^>]*(?:datetime|content)="(\d{4}-\d{2}-\d{2})"', page)
    if not pm:
        pm = re.search(r'itemprop="priorityDate"[^>]*>\s*(\d{4}-\d{2}-\d{2})', page)
    priority_date = _iso_to_ddmmyyyy(pm.group(1)) if pm else ""

    applicant_names = [a["name"] for a in applicants]

    return {
        "title_of_invention": title,
        "international_application_no": intl_app,
        "international_filing_date": filing_date,
        "international_publication_no": pub_no,
        "publication_date": publication_date,
        "priority_details": {
            "country": "", "application_number": "", "filing_date": priority_date,
            "applicant_name": ", ".join(applicant_names), "title": "", "ipc": "",
        },
        "applicants": applicants,
        "category_of_applicant": _category_for(applicant_names),
        "inventors": inventors,
        "applicant_name": ", ".join(applicant_names),
        "abstract_text": abstract,
        "description_pages": 0,
        "claims_pages_listed": 0,
        "abstract_pages_listed": 0,
        "drawings_pages_listed": 0,
    }


def scrape_patent(number: str):
    """
    Best-effort, key-free extraction. Returns (data, note).
    On any failure returns ({}, note) - never raises - so the caller can still
    fall back to Gemini and/or manual entry.
    """
    number = (number or "").strip()
    if not number:
        return {}, "No number supplied to scrape."
    try:
        data = scrape_google_patents(number)
        if data.get("title_of_invention") or data.get("international_application_no"):
            return data, f"Scraped bibliographic data from Google Patents ({_google_patents_id(number)})."
        return data, "Google Patents returned no recognisable bibliographic fields."
    except Exception as e:  # noqa: BLE001
        return {}, f"Scrape failed ({e.__class__.__name__}: {e})."
