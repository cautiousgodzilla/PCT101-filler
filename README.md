# PCT → FORM 1 Filler

A deployable web app that reproduces the function of the original Colab
notebook: it extracts PCT bibliographic data and generates the filled Indian
Patent Office PCT national-phase forms:

| Form | Title |
|------|-------|
| **Form 1** | Application for Grant of Patent |
| **Form 2** | Provisional / Complete Specification cover |
| **Form 3** | Statement and Undertaking under Section 8 |
| **Form 5** | Declaration as to Inventorship |

Select any combination in the UI — one form downloads a `.docx`, several
download as a single `.zip`.

Unlike the notebook (which read RO/101 and ran Playwright + python-docx in
Colab), this app is built to run on Vercel serverless functions — no headless
browser is required.

## What it does

1. **Source data** — enter the international / publication number and/or attach
   PDFs (RO/101, IB-306, ISR, priority document). The app first **scrapes** as
   much bibliographic data as it can with **no API key** (see *How extraction
   works* below), then — if a `GEMINI_API_KEY` is configured — asks Google Gemini
   to **fill the remaining gaps** (addresses, nationality, priority country /
   number, page counts) from the PatentScope page and/or the attached PDFs.
2. **Review & edit** — every field (title, applicants, inventors, priority, PCT
   number, page counts, claim/drawing counts) is shown in an editable form. A
   lawyer reviews and corrects before generating.
3. **Generate** — pick which forms (1 / 2 / 3 / 5) to produce; the reviewed data
   fills the bundled templates and downloads in the browser (`.docx` for one,
   `.zip` for several).

### Requirements baked in (per the PCT 101 spec)

| # | Requirement | Where it's handled |
|---|-------------|--------------------|
| 1 | Latest applicant / inventor / title from the HTML page (not RO/101) | `api/_extract.py` prompt rule 1 |
| 2 | Comma always before the country name in addresses; use ISR / IB-306 style | `normalize_address()` in `api/_form1.py` + prompt rule 2 |
| 3 | Priority country / number / filing date from HTML page; priority **title** only for English applications | `api/_extract.py` rule 3 + `ENGLISH_FILING_COUNTRIES` gate in `fill_priority_and_pct()` |
| 4 | PCT no. + filing date from HTML page | Section 9 fill in `api/_form1.py` |
| 5 | Inventor names in the signature portion | `add_inventor_names_to_signature()` |

> The original template left **Section 8 (priority)** and **Section 9 (PCT)** as
> "Nil". This app now populates both.

## Project layout

```
filler/
├─ index.html            # front-end (extract → review → generate)
├─ app.js
├─ api/
│  ├─ extract.py         # POST /api/extract  (Gemini extraction)
│  ├─ generate.py        # POST /api/generate (returns the .docx)
│  ├─ _extract.py        # Gemini logic + prompt
│  └─ _forms.py          # python-docx form-filling logic (Forms 1/2/3/5)
├─ templates/
│  ├─ form_1_template.docx   # FORM templates with {placeholders}
│  ├─ form_2_template.docx
│  ├─ form_3_template.docx
│  └─ form_5_template.docx
├─ requirements.txt
├─ vercel.json
└─ local_server.py       # run everything locally without Vercel
```

## Deploy to Vercel

1. Push this `filler/` folder to a Git repo (or run `vercel` from inside it).
2. In **Project → Settings → Environment Variables**, add:
   - `GEMINI_API_KEY` = your Google Gemini API key.
3. Deploy. Vercel auto-detects the static front-end and the Python functions in
   `/api`. `vercel.json` bundles the `templates/` folder with the functions.

> The hard-coded Gemini keys in the original notebook were removed — never
> commit API keys. Set `GEMINI_API_KEY` as an environment variable instead.

## Run locally

```bash
cd filler
python -m pip install -r requirements.txt
set GEMINI_API_KEY=your_key        # Windows  (export GEMINI_API_KEY=... on macOS/Linux)
python local_server.py
# open http://localhost:8000
```

The server reads `GEMINI_API_KEY` from the shell **or** from a local `filler/.env`
file automatically (existing env vars win). `/api/generate` works without any key
(it only needs the reviewed data), so you can fill the form manually and download
a FORM 1 even offline.

## How extraction works (scrape first, AI fills the gaps)

`/api/extract` never hard-fails on a missing/broken key. It runs in two layers:

1. **Key-free scrape (`api/_scrape.py`).** Given a WO / publication number it
   pulls the bibliographic record from **Google Patents**, which serves the same
   WIPO/PCT data fully server-rendered in machine-readable `<meta>` (Dublin Core
   / `citation_*`) tags and microdata. From this it reliably gets: title,
   abstract, inventors, applicant/assignee, international application number
   (e.g. `PCT/IB2023/062067`), publication number, international filing date,
   publication date and priority date — **with no API key**.
2. **Gemini fills the gaps (`api/_extract.py`).** If `GEMINI_API_KEY` is set,
   Gemini reads the PatentScope page and any attached PDFs and supplies what the
   scrape can't: addresses, nationality / residence, priority country & number,
   priority title and page/sheet counts. The two are merged with **scraped data
   as the base — Gemini only fills empty fields** (and enriches each
   inventor/applicant by name).

If no key is set (or Gemini errors), the form is still pre-filled from the scrape
and a note explains what was skipped; the reviewer completes the rest manually.

### Why not scrape PatentScope directly?

`patentscope.wipo.int/search/en/detail.jsf?docId=WO…` returns only a
PrimeFaces/JSF **shell** (site chrome + a ViewState). The actual bibliographic
record is injected afterwards by a session-bound AJAX partial render, so a plain
server-side `GET` sees no title/applicant/inventor data — replaying that AJAX
needs the live `jsessionid` + ViewState and is brittle, and a headless browser
isn't available on Vercel serverless. Google Patents exposes the same record
server-rendered, which is why it's used as the key-free source.

## Notes & limitations

- The scrape covers the **core biblio**; addresses, nationality, priority
  country/number and page counts generally still need the Gemini step or manual
  entry. The review step exists precisely so a human verifies/corrects the data —
  and attaching the RO/101 / IB-306 / ISR PDFs gives the most reliable result.
- Google Patents may briefly rate-limit (HTTP 503) bursts of automated requests;
  the scraper retries with back-off. Human-paced use is fine.
- Forms **1, 2, 3 and 5** are implemented. Form 3's body-paragraph placeholders
  (application number / date) — which the original notebook left unfilled — are
  now populated.
- Form 3/5 `{application_number}` is the Indian national-phase number. It is
  usually not allotted at filing, so it defaults to blank (editable); `{date}` /
  `{filing_date}` default to the date the forms are signed (today).
- Extraction is AI-assisted and is not guaranteed 100% accurate; always review.
