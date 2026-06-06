"""
PatentScope scraper using a real browser (Playwright/Chromium).

This is the container-friendly replacement for the Vercel @sparticuz Node
function: on Render (or any Docker host) the official Playwright image ships a
working Chromium, so we just drive it with the synchronous Playwright API — the
exact flow validated against the live site and used in the original notebook:

    1. open the PatentScope detail page (with a REAL User-Agent — the default
       headless UA gets a 403),
    2. scrape the rendered bibliographic text (the "latest data"),
    3. click the Documents tab, find the "(RO/101) Request form" row and
       download its PDF (fetched via the page's session so the token is valid).

Public function:
    scrape_patentscope(doc_id, want_pdf=True) -> dict
        { ok, docId, status, hasData, forbidden, biblio_text,
          ro101: { found, href, pdf_bytes, pdf_base64 }, notes: [...] }
    It never raises — failures come back as ok=False + notes.
"""

import base64

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ORIGIN = "https://patentscope.wipo.int"

# JS evaluated in the page to pull the RO/101 row's "PDF" link.
_RO101_HREF_JS = """() => {
  const rows = Array.from(document.querySelectorAll('tr'));
  const row = rows.find(r => r.innerText.includes('(RO/101) Request form'));
  if (!row) return null;
  const a = Array.from(row.querySelectorAll('a')).find(x => x.textContent.trim() === 'PDF');
  return a ? a.getAttribute('href') : null;
}"""

_RO101_PRESENT_JS = "() => /\\(RO\\/101\\) Request form/.test(document.body.innerText)"


def scrape_patentscope(doc_id: str, want_pdf: bool = True, timeout_ms: int = 90000) -> dict:
    from playwright.sync_api import sync_playwright

    doc_id = (doc_id or "").strip()
    notes = []
    result = {
        "ok": False,
        "docId": doc_id,
        "status": 0,
        "hasData": False,
        "forbidden": False,
        "biblio_text": "",
        "ro101": {"found": False, "href": None, "pdf_bytes": 0, "pdf_base64": None},
        "notes": notes,
    }
    if not doc_id:
        notes.append("No docId supplied.")
        return result

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=UA, accept_downloads=True)
        page = context.new_page()
        try:
            url = f"{ORIGIN}/search/en/detail.jsf?docId={doc_id}"
            resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            result["status"] = resp.status if resp else 0

            html = page.content()
            result["biblio_text"] = page.inner_text("body")
            result["hasData"] = "detailMainForm" in html
            result["forbidden"] = "403 FORBIDDEN" in html

            if result["hasData"] and not result["forbidden"]:
                try:
                    tab = 'a[href="#detailMainForm:MyTabViewId:PCTDOCUMENTS"]'
                    page.wait_for_selector(tab, timeout=15000)
                    page.click(tab)
                    page.wait_for_function(_RO101_PRESENT_JS, timeout=20000)
                    href = page.evaluate(_RO101_HREF_JS)
                    if href:
                        full = href if href.startswith("http") else ORIGIN + href
                        result["ro101"]["found"] = True
                        result["ro101"]["href"] = full
                        if want_pdf:
                            pr = context.request.get(
                                full, headers={"User-Agent": UA, "Referer": page.url}
                            )
                            if pr.ok:
                                body = pr.body()
                                result["ro101"]["pdf_bytes"] = len(body)
                                result["ro101"]["pdf_base64"] = base64.b64encode(body).decode("ascii")
                            else:
                                notes.append(f"RO/101 PDF fetch returned HTTP {pr.status}.")
                    else:
                        notes.append("RO/101 PDF link not found in the Documents tab.")
                except Exception as e:  # noqa: BLE001
                    notes.append(f"RO/101 step failed: {e}")
            elif result["forbidden"]:
                notes.append("PatentScope returned 403 FORBIDDEN (User-Agent / IP rejected).")
            else:
                notes.append("Page did not render the bibliographic form (detailMainForm absent).")

            result["ok"] = result["hasData"] and not result["forbidden"]
        except Exception as e:  # noqa: BLE001
            notes.append(f"Scrape error: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass
    return result
