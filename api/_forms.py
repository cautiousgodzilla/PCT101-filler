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
from docx.shared import Inches, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH

_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Templates: prefer the firm's REAL (private, git-ignored) templates if present,
# otherwise fall back to the public, firm-redacted set committed to the repo.
# The public templates carry {firm_name}/{firm_address}/{firm_phone}/{firm_email}/
# {agent_name}/{agent_inpa} placeholders, filled from firm_details (see below).
_PUBLIC_TEMPLATES = os.path.join(_ROOT, "templates")
# Always use the public (placeholder) templates. Firm + agent data is supplied
# per-user from firm_config.json (matched by the login-email domain), so it's the
# same template for everyone and no firm's data is baked in. (templates_private/
# remains on disk only as an archival backup; it is no longer auto-used.)
TEMPLATES_DIR = _PUBLIC_TEMPLATES

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
_FIRM_FIELDS = ("firm_name", "firm_address", "firm_phone", "firm_email",
                "agent_name", "agent_inpa", "agent_mobile")


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


# Shown to users whose email domain isn't a configured firm — placeholders make
# it obvious where their own firm/agent details would go.
_PLACEHOLDER_FIRM = {
    "firm_name": "[Firm name]",
    "firm_address": "[Firm address]",
    "firm_phone": "[Firm phone]",
    "firm_email": "[Firm email]",
    "agent_name": "[Agent name]",
    "agent_inpa": "[IN/PA No.]",
    "agent_mobile": "[Mobile No.]",
    "agents": [{"name": "[Agent name]", "inpa": "[IN/PA No.]", "mobile": "[Mobile No.]"}],
}


def _load_firm_config() -> dict:
    """Firm config maps email domains -> a firm's details + agent roster. PII (a
    firm's real agents) lives here, never in the repo.

    Source order:
      1. FIRM_CONFIG_JSON env var (the whole JSON, minified) — used on Render.
      2. firm_config.json file (git-ignored) — used locally.
    """
    raw = os.environ.get("FIRM_CONFIG_JSON")
    if raw:
        try:
            return json.loads(raw) or {}
        except ValueError:
            pass
    path = os.path.join(_ROOT, "firm_config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            pass
    return {}


def _firm_profile_for_email(email: str) -> dict | None:
    """Match the logged-in user's email domain to a configured firm (e.g.
    'iiprd'/'khuranaandkhurana' -> Khurana & Khurana). Returns the profile or None."""
    email = (email or "").lower().strip()
    if "@" not in email:
        return None
    domain = email.split("@", 1)[1]
    for firm in _load_firm_config().get("firms", []):
        for d in firm.get("domains", []):
            if d and d.lower() in domain:  # substring: 'iiprd' matches iiprd.com / iiprd.in
                return firm
    return None


def _resolve_firm(user_email: str = "") -> dict:
    """Pick the firm/agent data to fill, in order:
      1. Supabase firm profile matched by the user's email domain (editable in DB)
      2. firm_config.json / FIRM_CONFIG_JSON (domain match) — seed/fallback
      3. firm_details.json / FIRM_* env (interim single-firm)
      4. bracketed placeholders
    """
    # 1. Database (the account-linked, editable source of truth).
    try:
        import _db
        if user_email and _db.is_configured():
            bundle = _db.get_firm_bundle(user_email)
            if bundle:
                return _db.bundle_to_profile(bundle)
    except Exception:  # noqa: BLE001 — never let DB issues block generation
        pass

    # 2. firm_config.json / FIRM_CONFIG_JSON (domain match).
    prof = _firm_profile_for_email(user_email)
    if prof:
        sa = prof.get("signing_agent") or {}
        agents = prof.get("agents", []) or []
        first = agents[0] if agents else {}
        return {
            "firm_name": prof.get("firm_name", ""),
            "firm_address": prof.get("firm_address", ""),
            "firm_phone": prof.get("firm_phone", ""),
            "firm_email": prof.get("firm_email", ""),
            # Signing agent = explicit signing_agent, else the FIRST roster agent.
            "agent_name": sa.get("name") or first.get("name", ""),
            "agent_inpa": sa.get("inpa") or first.get("inpa", ""),
            "agent_mobile": sa.get("mobile") or first.get("mobile", ""),
            "agents": agents,
        }
    fd = _firm_details()
    if any(fd.values()):  # firm_details.json / FIRM_* env configured
        fd["agents"] = []
        return fd
    return dict(_PLACEHOLDER_FIRM)


def _unique_cells(row):
    """Row cells de-duplicated across horizontal merges."""
    seen, out = [], []
    for c in row.cells:
        if c._tc not in seen:
            seen.append(c._tc)
            out.append(c)
    return out


def fill_agent_roster(document, agents):
    """Section 6 (Authorized Registered Patent Agent(s)) — each agent is a 3-row
    group (IN/PA No. / Name / Mobile). Fills one group per agent and DELETES the
    unused groups (the template ships with 13), keeping at least one group so the
    section is never empty. Most filings have a single agent."""
    rows = []
    for table in document.tables:
        for r in table.rows:
            if "AUTHORIZED REGISTERED PATENT AGENT" in " ".join(c.text for c in r.cells):
                rows.append(r)
    groups = len(rows) // 3
    keep = max(1, len(agents))  # always leave at least one agent group
    for gi in range(groups):
        grp = rows[gi * 3: gi * 3 + 3]
        if gi < keep:
            ag = agents[gi] if gi < len(agents) else {}
            for r in grp:
                uniq = _unique_cells(r)
                if len(uniq) < 3:
                    continue
                label = uniq[1].text.strip().lower()
                if "in/pa" in label:
                    val = str(ag.get("inpa", ""))
                elif "mobile" in label:
                    val = str(ag.get("mobile", ""))
                elif "name" in label:
                    val = str(ag.get("name", ""))
                else:
                    continue
                _set_cell_text(uniq[-1], val)
        else:
            for r in grp:  # remove the whole unused 3-row group
                r._element.getparent().remove(r._element)

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


def _tiny_separator_p():
    """A ~1pt empty paragraph used to keep adjacent tables from merging without
    adding a visible blank line above/below the inserted table."""
    p = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "20")
    spacing.set(qn("w:lineRule"), "exact")
    pPr.append(spacing)
    rPr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "2")  # 1pt
    rPr.append(sz)
    pPr.append(rPr)
    p.append(pPr)
    return p


def match_form_table_margins(table):
    """Make an inserted table align with the form's own tables: same left indent
    (tblInd -5) and zero cell side-margins (the form uses 0; Word's default ~0.08"
    padding is what pushes inserted-table content out of alignment)."""
    tbl_pr = table._tbl.tblPr
    ind = tbl_pr.find(qn("w:tblInd"))
    if ind is None:
        ind = OxmlElement("w:tblInd")
        tbl_pr.append(ind)
    ind.set(qn("w:w"), "-5")
    ind.set(qn("w:type"), "dxa")
    cm = tbl_pr.find(qn("w:tblCellMar"))
    if cm is None:
        cm = OxmlElement("w:tblCellMar")
        tbl_pr.append(cm)
    for side in ("left", "right"):
        e = cm.find(qn(f"w:{side}"))
        if e is None:
            e = OxmlElement(f"w:{side}")
            cm.append(e)
        e.set(qn("w:w"), "0")
        e.set(qn("w:type"), "dxa")


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
        for run in p.runs:  # applicant/inventor tables: Times New Roman 12pt
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
    _set_cell_width(cell, width)


def insert_table_at_placeholder(document, placeholder, data_list, table_type="applicant"):
    role = "Applicant" if table_type == "applicant" else "Inventor"
    headers = [
        "Name in Full",
        "Gender (Optional, for individuals)",
        "Nationality",
        "Country of Residence",
        "Age (optional, for natural persons)",
        f"Address of the {role}",
    ]
    # Sum ~7.95" to match the form's own tables (tblW 7.97"), so the table's left
    # and right edges line up with the rest of the form.
    col_widths = [Inches(1.9), Inches(0.8), Inches(0.8), Inches(1.0), Inches(0.8), Inches(2.65)]

    for para in document.paragraphs:
        if placeholder in para.text:
            p = para._element
            table = document.add_table(rows=1 + len(data_list), cols=len(headers))
            set_table_fixed_layout(table)
            match_form_table_margins(table)

            for i, h in enumerate(headers):
                _format_cell(table.rows[0].cells[i], h, col_widths[i], center=i not in (0, 5))

            for r_idx, person in enumerate(data_list, start=1):
                row = table.rows[r_idx]
                addr = normalize_address(person.get("address", ""), best_country(person))
                _format_cell(row.cells[0], person.get("name", ""), col_widths[0], center=False)
                _format_cell(row.cells[1], "Prefer not to disclose", col_widths[1])
                _format_cell(row.cells[2], person.get("nationality", ""), col_widths[2])
                _format_cell(row.cells[3], person.get("country_of_residence", ""), col_widths[3])
                _format_cell(row.cells[4], "Prefer not to disclose", col_widths[4])
                _format_cell(row.cells[5], addr, col_widths[5], center=False)

            try:
                table.style = "Table Grid"
            except Exception:
                pass
            set_table_borders(table)

            tbl = table._tbl
            # Tiny (~1pt) separator paragraphs on BOTH sides so Word doesn't merge
            # this with the form's adjacent tables (which corrupts their layout),
            # without adding a visible blank line.
            p.addprevious(_tiny_separator_p())
            p.addprevious(tbl)
            p.addprevious(_tiny_separator_p())
            p.getparent().remove(p)
            break


# ---------------------------------------------------------------------------
# Section 9 (PCT) – fill the "Nil" data row.
# NOTE: Section 8 (convention/priority) is intentionally NOT filled — for a PCT
# national-phase application the priority is claimed through the PCT, so the
# convention-application section stays "Nil".
# ---------------------------------------------------------------------------
def _set_cell_text(cell, text):
    """Replace a cell's text while preserving its first paragraph's style."""
    cell.text = str(text)


def _row_texts(row):
    return [c.text.strip() for c in row.cells]


def fill_priority_and_pct(document, data):
    pct_no = data.get("international_application_no", "")
    pct_date = data.get("international_filing_date", "")

    for table in document.tables:
        rows = table.rows
        for i, row in enumerate(rows):
            joined = " ".join(_row_texts(row))
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
# Signature portion – make the agent/firm signature lines bold.
# (The placeholder fill collapses runs and loses the template's bold, so we
# re-apply it after filling. Inventor names are NOT added to the signature.)
# ---------------------------------------------------------------------------
def _bold_para(p):
    if not p.runs:
        return
    for run in p.runs:
        run.bold = True


def bold_signature(document):
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paras = cell.paragraphs
                for i, p in enumerate(paras):
                    txt = p.text.strip()
                    if "AGENT FOR THE APPLICANT" in txt:
                        for j in (i - 1, i, i + 1):  # Name: / AGENT / firm name
                            if 0 <= j < len(paras):
                                _bold_para(paras[j])
                    elif txt.startswith("Name:"):  # e.g. Form 5 signature line
                        _bold_para(p)
    for p in document.paragraphs:
        if p.text.strip().startswith("Name:"):
            _bold_para(p)


# ---------------------------------------------------------------------------
# Scalar placeholder replacement (shared by all forms)
# ---------------------------------------------------------------------------
def _scalar_replacements(data: dict, firm: dict = None) -> dict:
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
    # Firm/agent placeholders. Caller data wins; otherwise the resolved firm
    # (matched by the user's email domain, else env/json, else placeholders).
    firm = firm if firm is not None else _resolve_firm("")
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
def fill_form(form_id: str, data: dict, user_email: str = "") -> bytes:
    """Fill the template for `form_id` ('1','2','3','5') and return .docx bytes.

    `user_email` (from the logged-in Supabase user) selects the firm/agent data:
    a matching firm (e.g. iiprd / khuranaandkhurana domains) fills its details +
    agent roster; everyone else gets bracketed placeholders.
    """
    form_id = str(form_id)
    if form_id not in FORMS:
        raise ValueError(f"Unknown form id: {form_id!r}")

    document = Document(os.path.join(TEMPLATES_DIR, FORMS[form_id]))
    firm = _resolve_firm(user_email)
    mapping = _scalar_replacements(data, firm)

    _replace_everywhere(document, mapping)

    if form_id == "1":
        applicants = data.get("applicants", []) or []
        inventors = data.get("inventors", []) or []
        # Section 9 (PCT) only — Section 8 (convention priority) stays Nil for PCT-NP.
        fill_priority_and_pct(document, data)
        # Section 6 agent roster (from the matched firm, else placeholder).
        fill_agent_roster(document, firm.get("agents", []))
        # Applicant / inventor tables.
        insert_table_at_placeholder(document, "applicant_table_format", applicants, "applicant")
        insert_table_at_placeholder(document, "inventor_table_format", inventors, "inventor")

    bold_signature(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def fill_form1(data: dict) -> bytes:
    """Backwards-compatible alias for Form 1."""
    return fill_form("1", data)


def build_zip(form_ids, data: dict, user_email: str = "") -> bytes:
    """Generate several forms and return them bundled as a .zip."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fid in form_ids:
            fid = str(fid)
            if fid not in FORMS:
                continue
            zf.writestr(f"Form_{fid}.docx", fill_form(fid, data, user_email))
    return buf.getvalue()
