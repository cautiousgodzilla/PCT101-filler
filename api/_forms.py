"""
Core Form 1 filling logic.

Ported from the original Colab notebook and extended to satisfy the PCT 101
requirements:

  1. Latest applicant / inventor / title come from the input data (HTML page),
     not from RO/101.
  2. Addresses are normalised so that there is always a comma before the
     country name (the "ISR / IB-306" comma style).
  3. Priority country / number / filing date + priority title are written into
     Section 8 (the original template left this as "Nil").
  4. PCT number + international filing date are written into Section 9.
  5. Inventor names are added to the signature portion.

This module is pure `python-docx` so it runs unchanged on a Vercel Python
serverless function or locally.
"""

import io
import json
import os
import re
from datetime import date

from docx import Document
from docx.shared import Inches
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH

_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Templates: prefer the firm's REAL (private, git-ignored) templates if present,
# otherwise fall back to the public, firm-redacted set committed to the repo.
# The public templates carry {firm_name}/{firm_address}/{firm_phone}/{firm_email}/
# {agent_name}/{agent_inpa} placeholders, filled from firm_details (see below).
_PRIVATE_TEMPLATES = os.path.join(_ROOT, "templates_private")
_PUBLIC_TEMPLATES = os.path.join(_ROOT, "templates")
TEMPLATES_DIR = _PRIVATE_TEMPLATES if os.path.isdir(_PRIVATE_TEMPLATES) else _PUBLIC_TEMPLATES

# Supported forms and their template files.
FORMS = {
    "1": "form_1_template.docx",  # Application for Grant of Patent
    "2": "form_2_template.docx",  # Provisional / Complete Specification cover
    "3": "form_3_template.docx",  # Statement and Undertaking (Section 8)
    "5": "form_5_template.docx",  # Declaration as to Inventorship
}

# Kept for backwards-compatibility.
TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, FORMS["1"])

# Firm / agent details used to fill the public templates' placeholders. Interim
# mechanism (precursor to the per-user login feature in TODO.md): read from a
# git-ignored firm_details.json or FIRM_* env vars; default to blank so the
# public deployment never shows anyone's details.
_FIRM_FIELDS = ("firm_name", "firm_address", "firm_phone", "firm_email", "agent_name", "agent_inpa")


def _firm_details() -> dict:
    details = {k: "" for k in _FIRM_FIELDS}
    path = os.path.join(_ROOT, "firm_details.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            for k in _FIRM_FIELDS:
                if data.get(k):
                    details[k] = str(data[k])
        except (OSError, ValueError):
            pass
    for k in _FIRM_FIELDS:  # env vars win (e.g. FIRM_NAME, AGENT_INPA)
        env = os.environ.get(k.upper())
        if env:
            details[k] = env
    return details

# ISO-ish list of countries whose first filing is normally in English.  Used to
# decide whether a priority *title* should be carried over (requirement 3:
# "Priority Title ... title only for Engl App.").
ENGLISH_FILING_COUNTRIES = {
    "US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA",
    "GB", "UK", "UNITED KINGDOM", "GREAT BRITAIN",
    "AU", "AUSTRALIA", "NZ", "NEW ZEALAND",
    "CA", "CANADA", "IE", "IRELAND",
    "IN", "INDIA", "SG", "SINGAPORE", "ZA", "SOUTH AFRICA",
    "PH", "PHILIPPINES",
}


# ---------------------------------------------------------------------------
# Address / comma normalisation  (requirement 2)
# ---------------------------------------------------------------------------
def normalize_address(address: str, country: str = "") -> str:
    """Collapse whitespace and ensure a comma sits immediately before the
    country name, e.g. "... Tokyo 100-0001 Japan" -> "... Tokyo 100-0001, Japan".

    The house style ("ISR / IB-306 comma style") always keeps a comma
    before the country name in every address.
    """
    if not address:
        return ""

    addr = address.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    addr = re.sub(r"\s+", " ", addr).strip().rstrip(",").strip()

    country = (country or "").strip().rstrip(".").strip()
    if not country:
        return addr

    # If the address already ends with the country, normalise the separator.
    pattern = re.compile(r"[,\s]*" + re.escape(country) + r"\.?$", re.IGNORECASE)
    if pattern.search(addr):
        addr = pattern.sub("", addr).rstrip().rstrip(",").strip()

    return f"{addr}, {country}"


def best_country(person: dict) -> str:
    """Pick the country to use for the comma-before-country rule."""
    return (
        person.get("country_of_residence")
        or person.get("country")
        or person.get("nationality")
        or ""
    ).strip()


# ---------------------------------------------------------------------------
# Inventor declaration block  (used for the {inventor_list_format} placeholder)
# ---------------------------------------------------------------------------
def generate_inventor_list_format(inventors: list) -> str:
    if not inventors:
        return "N/A"

    blocks = []
    for i, inv in enumerate(inventors, 1):
        name = inv.get("name", "N/A")
        nationality = inv.get("nationality", "N/A")
        address = normalize_address(inv.get("address", ""), best_country(inv))
        blocks.append(
            f"\n\n{i}.\na.\tName: {name}\n"
            f"b.\tNationality: {nationality}\n"
            f"c.\tAddress: {address}"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Table helpers (ported from form_editors.py, fixed-layout version)
# ---------------------------------------------------------------------------
def set_table_borders(table):
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_borders = tbl_pr.find(qn("w:tblBorders"))
    if tbl_borders is None:
        tbl_borders = OxmlElement("w:tblBorders")
        tbl_pr.append(tbl_borders)
    for border_name in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        el = tbl_borders.find(qn(f"w:{border_name}"))
        if el is None:
            el = OxmlElement(f"w:{border_name}")
            tbl_borders.append(el)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "8")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")


def set_table_fixed_layout(table):
    tbl_pr = table._tbl.tblPr
    tbl_layout = tbl_pr.find(qn("w:tblLayout"))
    if tbl_layout is None:
        tbl_layout = OxmlElement("w:tblLayout")
        tbl_pr.append(tbl_layout)
    tbl_layout.set(qn("w:type"), "fixed")


def _set_cell_width(cell, width):
    tcPr = cell._tc.get_or_add_tcPr()
    tcW = tcPr.find(qn("w:tcW"))
    if tcW is None:
        tcW = OxmlElement("w:tcW")
        tcPr.append(tcW)
    tcW.set(qn("w:w"), str(int(width.twips)))
    tcW.set(qn("w:type"), "dxa")


def _format_cell(cell, text, width, center=True):
    cell.text = text
    for p in cell.paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    _set_cell_width(cell, width)


def insert_table_at_placeholder(document, placeholder, data_list, table_type="applicant"):
    role = "Applicant" if table_type == "applicant" else "Inventor"
    headers = [
        "Name·in·Full",
        "Gender·(Optional, for individuals)",
        "Nationality",
        "Country·of·Residence",
        "Age·(optional, for natural persons)",
        f"Address·of·the·{role}",
    ]
    col_widths = [Inches(1.9), Inches(0.8), Inches(0.8), Inches(0.8), Inches(0.8), Inches(3.0)]

    for para in document.paragraphs:
        if placeholder in para.text:
            p = para._element
            table = document.add_table(rows=1 + len(data_list), cols=len(headers))
            set_table_fixed_layout(table)

            for i, h in enumerate(headers):
                _format_cell(table.rows[0].cells[i], h, col_widths[i], center=i not in (0, 5))

            for r_idx, person in enumerate(data_list, start=1):
                row = table.rows[r_idx]
                addr = normalize_address(person.get("address", ""), best_country(person))
                _format_cell(row.cells[0], person.get("name", ""), col_widths[0], center=False)
                _format_cell(row.cells[1], "-Prefer·not·to·disclose", col_widths[1])
                _format_cell(row.cells[2], person.get("nationality", ""), col_widths[2])
                _format_cell(row.cells[3], person.get("country_of_residence", ""), col_widths[3])
                _format_cell(row.cells[4], "-Prefer·not·to·disclose", col_widths[4])
                _format_cell(row.cells[5], addr, col_widths[5], center=False)

            try:
                table.style = "Table Grid"
            except Exception:
                pass
            set_table_borders(table)

            tbl = table._tbl
            p.addprevious(tbl)
            p.getparent().remove(p)
            break


# ---------------------------------------------------------------------------
# Section 8 (priority) & Section 9 (PCT) – fill the "Nil" data rows
# ---------------------------------------------------------------------------
def _set_cell_text(cell, text):
    """Replace a cell's text while preserving its first paragraph's style."""
    cell.text = str(text)


def _row_texts(row):
    return [c.text.strip() for c in row.cells]


def fill_priority_and_pct(document, data):
    priority = data.get("priority_details") or {}
    pct_no = data.get("international_application_no", "")
    pct_date = data.get("international_filing_date", "")

    for table in document.tables:
        rows = table.rows
        for i, row in enumerate(rows):
            texts = _row_texts(row)
            joined = " ".join(texts)

            # --- Section 8: priority / convention row ---------------------
            if "Country" in texts and "Application Number" in texts and i + 1 < len(rows):
                data_row = rows[i + 1]
                if all(t.lower() in ("", "nil") for t in _row_texts(data_row)):
                    p_country = priority.get("country", "")
                    if p_country:
                        cells = data_row.cells
                        _set_cell_text(cells[0], p_country)
                        _set_cell_text(cells[1], priority.get("application_number", ""))
                        _set_cell_text(cells[2], priority.get("filing_date", ""))
                        _set_cell_text(cells[4], priority.get("applicant_name", "") or data.get("applicant_name", ""))
                        # Title only for English-language priority applications.
                        title = priority.get("title", "")
                        if p_country.upper() in ENGLISH_FILING_COUNTRIES:
                            _set_cell_text(cells[7], title)
                        else:
                            _set_cell_text(cells[7], "")
                        _set_cell_text(cells[10], priority.get("ipc", ""))

            # --- Section 9: PCT national-phase row ------------------------
            if "International Application Number" in joined and i + 1 < len(rows):
                data_row = rows[i + 1]
                if all(t.lower() in ("", "nil") for t in _row_texts(data_row)) and pct_no:
                    cells = data_row.cells
                    _set_cell_text(cells[0], pct_no)
                    # International filing date starts at the merged cell ~index 5.
                    date_idx = 5 if len(cells) > 5 else len(cells) - 1
                    _set_cell_text(cells[date_idx], pct_date)


# ---------------------------------------------------------------------------
# Signature portion – add inventor names  (requirement 5)
# ---------------------------------------------------------------------------
def add_inventor_names_to_signature(document, inventors):
    names = [inv.get("name", "").strip() for inv in inventors if inv.get("name", "").strip()]
    if not names:
        return
    names_line = "Name(s) of Inventor(s): " + ", ".join(names)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if "AGENT FOR THE APPLICANT" in p.text:
                        # Add a run on a new line listing the inventors.
                        run = p.add_run("\n" + names_line)
                        return


# ---------------------------------------------------------------------------
# Scalar placeholder replacement (shared by all forms)
# ---------------------------------------------------------------------------
def _scalar_replacements(data: dict) -> dict:
    """Build the flat {placeholder: value} map used across all four forms."""
    applicants = data.get("applicants", []) or []
    inventors = data.get("inventors", []) or []
    first = applicants[0] if applicants else {}

    today = date.today().strftime("%d %B %Y")
    filing_date = data.get("filing_date") or today

    mapping = {
        "title_of_invention": data.get("title_of_invention", ""),
        "applicant_name": data.get("applicant_name")
        or ", ".join(a.get("name", "") for a in applicants if a.get("name")),
        "applicant_address": normalize_address(first.get("address", ""), best_country(first)),
        "applicant_nationality": first.get("nationality", ""),
        "inventor_list_format": generate_inventor_list_format(inventors),
        "filing_date": filing_date,
        # Form 3 uses {date} ("Filed on") and {filing_date} ("dated"); for a PCT
        # national-phase filing both default to the date the form is signed.
        "date": data.get("date") or filing_date,
        "application_number": data.get("application_number")
        or data.get("national_application_number")
        or "",
        "claims_count": data.get("claims_count", ""),
        "drawings_count": data.get("drawings_count", ""),
        "description_pages": data.get("description_pages", ""),
        "claims_pages_listed": data.get("claims_pages_listed", ""),
        "abstract_pages_listed": data.get("abstract_pages_listed", ""),
        "drawings_pages_listed": data.get("drawings_pages_listed", ""),
    }
    # Firm/agent placeholders (public templates). Caller data wins; otherwise the
    # configured firm_details / FIRM_* env; otherwise blank.
    firm = _firm_details()
    for k in _FIRM_FIELDS:
        mapping[k] = data.get(k) or firm.get(k, "")
    return mapping


def _replace_in_paragraphs(paragraphs, mapping):
    for p in paragraphs:
        if "{" not in p.text:
            continue
        for key, value in mapping.items():
            token = "{" + key + "}"
            if token in p.text:
                p.text = p.text.replace(token, str(value))


def _replace_everywhere(document, mapping):
    """Replace scalar placeholders in body paragraphs and every table cell.

    (The original notebook only replaced inside tables, which silently left the
    body-paragraph placeholders in Form 3 unfilled — this fixes that.)
    """
    _replace_in_paragraphs(document.paragraphs, mapping)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                _replace_in_paragraphs(cell.paragraphs, mapping)


# ---------------------------------------------------------------------------
# Per-form entry points
# ---------------------------------------------------------------------------
def fill_form(form_id: str, data: dict) -> bytes:
    """Fill the template for `form_id` ('1','2','3','5') and return .docx bytes."""
    form_id = str(form_id)
    if form_id not in FORMS:
        raise ValueError(f"Unknown form id: {form_id!r}")

    document = Document(os.path.join(TEMPLATES_DIR, FORMS[form_id]))
    mapping = _scalar_replacements(data)

    _replace_everywhere(document, mapping)

    if form_id == "1":
        applicants = data.get("applicants", []) or []
        inventors = data.get("inventors", []) or []
        # Sections 8 (priority) & 9 (PCT) — not template placeholders.
        fill_priority_and_pct(document, data)
        # Inventor names in the signature portion.
        add_inventor_names_to_signature(document, inventors)
        # Applicant / inventor tables.
        insert_table_at_placeholder(document, "applicant_table_format", applicants, "applicant")
        insert_table_at_placeholder(document, "inventor_table_format", inventors, "inventor")

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def fill_form1(data: dict) -> bytes:
    """Backwards-compatible alias for Form 1."""
    return fill_form("1", data)


def build_zip(form_ids, data: dict) -> bytes:
    """Generate several forms and return them bundled as a .zip."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fid in form_ids:
            fid = str(fid)
            if fid not in FORMS:
                continue
            zf.writestr(f"Form_{fid}.docx", fill_form(fid, data))
    return buf.getvalue()
