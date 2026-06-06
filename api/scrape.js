/*
 * Vercel Node serverless function: GET /api/scrape?docId=WO2024116111
 *
 * Renders the WIPO PatentScope detail page with a real headless Chromium
 * (@sparticuz/chromium, sized to fit Vercel's function limit) and:
 *   1. scrapes the rendered bibliographic page text (the "latest data"), and
 *   2. locates and downloads the "(RO/101) Request form" PDF.
 *
 * It also doubles as the DATACENTER-IP PROBE: deploy it, hit it once, and read
 * the JSON — if { ok:true, hasData:true, forbidden:false } then Vercel's IP can
 * reach PatentScope and the whole approach is viable.
 *
 * CRITICAL: a realistic User-Agent is mandatory. PatentScope returns HTTP 403
 * ("FORBIDDEN") to the default headless UA (which contains "HeadlessChrome").
 *
 * NOTE: this is an ES module (the package is marked "type": "module") because
 * @sparticuz/chromium v149+ and puppeteer-core v25+ are ESM-only. Loading them
 * with CommonJS require() crashes the function at startup on Node 24.
 *
 * Query params:
 *   docId  - PatentScope docId (default WO2024116111). e.g. WO2024116111
 *   pdf    - "0" to skip downloading the RO/101 PDF (faster probe). default on.
 */

import chromium from '@sparticuz/chromium';
import puppeteer from 'puppeteer-core';

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

const ORIGIN = 'https://patentscope.wipo.int';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).end();
  }

  const q = req.query || {};
  const docId = (q.docId || 'WO2024116111').toString().trim();
  const wantPdf = q.pdf !== '0';
  const notes = [];
  let browser;

  try {
    browser = await puppeteer.launch({
      args: chromium.args,
      defaultViewport: chromium.defaultViewport,
      executablePath: await chromium.executablePath(),
      headless: true,
    });

    const page = await browser.newPage();
    await page.setUserAgent(UA); // <-- without this, PatentScope 403s the request.

    const url = `${ORIGIN}/search/en/detail.jsf?docId=${encodeURIComponent(docId)}`;
    const resp = await page.goto(url, { waitUntil: 'networkidle2', timeout: 90000 });
    const status = resp ? resp.status() : 0;

    const html = await page.content();
    const biblioText = await page.evaluate(() => document.body.innerText);
    const hasData = html.includes('detailMainForm');
    const forbidden = html.includes('403 FORBIDDEN');

    const ro101 = { found: false, href: null, pdf_bytes: 0, pdf_base64: null };

    if (hasData && !forbidden) {
      try {
        // Open the "Documents" tab.
        const tabSel = 'a[href="#detailMainForm:MyTabViewId:PCTDOCUMENTS"]';
        await page.waitForSelector(tabSel, { timeout: 15000 });
        await page.click(tabSel);

        // Wait for the RO/101 row to render, then grab its "PDF" link href.
        await page.waitForFunction(
          () => /\(RO\/101\) Request form/.test(document.body.innerText),
          { timeout: 20000 }
        );
        const href = await page.evaluate(() => {
          const rows = Array.from(document.querySelectorAll('tr'));
          const row = rows.find((r) => r.innerText.includes('(RO/101) Request form'));
          if (!row) return null;
          const a = Array.from(row.querySelectorAll('a')).find(
            (x) => x.textContent.trim() === 'PDF'
          );
          return a ? a.getAttribute('href') : null;
        });

        if (href) {
          ro101.found = true;
          ro101.href = href.startsWith('http') ? href : ORIGIN + href;

          if (wantPdf) {
            // Fetch the PDF directly, reusing the browser's session cookies
            // (simpler and more reliable than headless download interception).
            const cookies = await page.cookies();
            const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
            const pr = await fetch(ro101.href, {
              headers: { 'User-Agent': UA, Cookie: cookieHeader, Referer: page.url() },
            });
            if (pr.ok) {
              const buf = Buffer.from(await pr.arrayBuffer());
              ro101.pdf_bytes = buf.length;
              ro101.pdf_base64 = buf.toString('base64');
            } else {
              notes.push(`RO/101 PDF fetch returned HTTP ${pr.status}.`);
            }
          }
        } else {
          notes.push('RO/101 PDF link not found in the Documents tab.');
        }
      } catch (e) {
        notes.push('RO/101 step failed: ' + (e && e.message ? e.message : String(e)));
      }
    } else if (forbidden) {
      notes.push('PatentScope returned 403 FORBIDDEN (User-Agent / IP rejected).');
    } else {
      notes.push('Page did not render the bibliographic form (detailMainForm absent).');
    }

    return res.status(200).json({
      ok: hasData && !forbidden,
      docId,
      status,
      hasData,
      forbidden,
      bytes: html.length,
      biblio_text: biblioText,
      ro101,
      notes,
    });
  } catch (e) {
    return res.status(500).json({
      ok: false,
      docId,
      error: e && e.message ? e.message : String(e),
      notes,
    });
  } finally {
    if (browser) {
      try { await browser.close(); } catch (_) { /* ignore */ }
    }
  }
}
