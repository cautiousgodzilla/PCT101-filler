# Deploying the PCT → Form 1 Filler to Vercel (CLI)

This guide deploys the app **including the PatentScope browser scraper**. You run
every command yourself; nothing here changes your Vercel account on its own.

---

## 1. What gets deployed

It's a **hybrid project** — Vercel runs Python and Node functions side by side:

```
filler/
├─ public/                      # static front-end — Vercel serves this at "/"
│  ├─ index.html
│  └─ app.js
├─ api/
│  ├─ extract.py   (Python)     # Gemini extraction + Google Patents fallback
│  ├─ generate.py  (Python)     # python-docx → fills Forms 1/2/3/5
│  ├─ _extract.py / _forms.py / _scrape.py   (Python helpers)
│  └─ scrape.js    (NODE)       # @sparticuz/chromium → renders PatentScope,
│                               #   scrapes biblio + downloads RO/101 PDF
├─ templates/                   # the .docx form templates (bundled with the Py fns)
├─ requirements.txt             # Python deps
├─ package.json                # Node deps (@sparticuz/chromium, puppeteer-core)
├─ vercel.json                 # runtimes + memory/timeout
└─ .vercelignore
```

| Endpoint | Runtime | Purpose | Needs |
|---|---|---|---|
| `GET /api/scrape` | Node | Render PatentScope, scrape biblio, fetch RO/101 PDF | (browser only) |
| `POST /api/extract` | Python | Gemini extraction (+ Google Patents fallback) | `GEMINI_API_KEY` |
| `POST /api/generate` | Python | Build the `.docx` / `.zip` | (none) |

> **Why a Node function?** A browser engine can't run in Vercel's *Python* runtime.
> `@sparticuz/chromium` is a stripped, compressed Chromium (~50 MB) that fits the
> function size limit and runs under `puppeteer-core` in the **Node** runtime.

---

## 2. Prerequisites

- A **Vercel account** (free Hobby plan is fine to start).
- **Node.js ≥ 18** and **npm** locally (`node -v`).
- Your **Google Gemini API key**.
- Run everything from inside the `filler/` directory:
  ```powershell
  cd path\to\filler
  ```

---

## 3. Install Node dependencies

This generates `package-lock.json` and verifies the deps resolve. Vercel will
reinstall them during the build.

```powershell
npm install
```

---

## 4. Install the Vercel CLI and log in

```powershell
npm install -g vercel
vercel login
```

`vercel login` opens a browser to authenticate — complete it there.

---

## 5. Link the directory to a Vercel project

First run from `filler/`:

```powershell
vercel link
```

Answer the prompts (scope = your account; **Link to existing project?** → No;
**project name** → e.g. `pct-form-filler`; **directory** → `./`). This creates a
local `.vercel/` folder (already safe to keep out of git).

---

## 6. Set the Gemini API key as an environment variable

Do **not** commit the key. Add it to Vercel for all environments:

```powershell
vercel env add GEMINI_API_KEY production
vercel env add GEMINI_API_KEY preview
vercel env add GEMINI_API_KEY development
```

Each command prompts for the value — paste your key. (Or set it in the Vercel
dashboard: *Project → Settings → Environment Variables*.)

> `/api/generate` works without the key. `/api/extract` needs it; `/api/scrape`
> doesn't (it only drives the browser).

---

## 7. Deploy a preview build

```powershell
vercel
```

This builds and gives you a temporary `https://<project>-<hash>.vercel.app` URL.
Use it for the validation step next.

---

## 8. ✅ Validate the datacenter IP (the make-or-break test)

Local tests proved the scrape works from a residential IP. The one thing only a
deployed function can answer is whether **Vercel's datacenter IP** can reach
PatentScope. Hit the probe (replace the host with your preview URL):

```powershell
curl "https://<your-preview-url>/api/scrape?docId=WO2024116111&pdf=0"
```

Read the JSON:

| Result | Meaning | Action |
|---|---|---|
| `{"ok":true,"hasData":true,"forbidden":false,...}` | Vercel's IP renders the page fine | **Green light** — proceed |
| `{"forbidden":true}` or `status:403` | PatentScope blocks Vercel's IP / UA | Pivot to a proxy-backed render service (Browserless / Bright Data) |
| `status:0` / timeout / 500 | Cold start or render too slow | Raise `maxDuration` (see §10), retry |

Once happy, add `&pdf=1` (the default) to confirm the RO/101 PDF downloads —
look for `ro101.found:true` and a non-zero `ro101.pdf_bytes`.

---

## 9. Deploy to production

```powershell
vercel --prod
```

This publishes to your production domain. Re-run the probe against the prod URL
to confirm.

---

## 10. Tuning (`vercel.json`)

Already configured, but adjust if needed:

```json
{
  "functions": {
    "api/*.py":     { "runtime": "@vercel/python@4.3.1", "memory": 1024, "maxDuration": 60, "includeFiles": "templates/**" },
    "api/scrape.js": { "memory": 1024, "maxDuration": 60 }
  }
}
```

- **`maxDuration`** — PatentScope render + RO/101 can take 15–40 s. `60` is the
  **Hobby** ceiling; on **Pro** you can raise `api/scrape.js` to `300` if you see
  timeouts.
- **`memory`** — keep at **1024 MB** for Chromium (512 will OOM).

---

## 11. (Optional, Phase 2) Wire PatentScope scraping into the UI

The deploy above ships `/api/scrape` as a standalone endpoint; the existing UI
still uses the Google Patents + Gemini path. To make the **Extract** button use
PatentScope first, add this to `app.js` and call it before `/api/extract`:

```js
// app.js — fetch the RO/101 PDF + biblio text from PatentScope, then hand off
async function scrapePatentScope(docId) {
  const r = await fetch(`/api/scrape?docId=${encodeURIComponent(docId)}`);
  const d = await r.json();
  if (!d.ok) throw new Error((d.notes || []).join("; ") || "scrape failed");
  const pdfs = [];
  if (d.ro101 && d.ro101.pdf_base64) {
    pdfs.push({ mime: "application/pdf", data: d.ro101.pdf_base64 }); // RO/101 PDF
  }
  // Pass the RO/101 PDF (and, if you extend _extract.py, d.biblio_text) to /api/extract.
  return { pdfs, biblio_text: d.biblio_text };
}
```

Then in the `btnExtract` handler, try `scrapePatentScope(pct)` first and merge
its `pdfs` into the body you POST to `/api/extract`. To also feed the rendered
page text to Gemini, add an optional `biblio_text` field to the `/api/extract`
request and append it to the prompt in `api/_extract.py` (`_gemini_extract`).

> Keep this behind a try/catch so a scrape failure falls back to the existing
> Google Patents + manual path — that way a bad PatentScope day never blocks a
> user from filling the form.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/api/scrape` returns `forbidden:true` / 403 | UA missing or IP blocked. The function already sets a real UA; if it's the IP, use a proxy render service. |
| `Could not find Chromium` / launch fails | `@sparticuz/chromium` and `puppeteer-core` must target the **same Chromium major**. Bump both together per the [@sparticuz/chromium compatibility table](https://github.com/Sparticuz/chromium#-versioning) (e.g. `chromium@131` + `puppeteer-core@23/24`). |
| `libnss3.so: cannot open shared object file` on launch | The `@sparticuz/chromium` version is too old for the runtime (its extracted lib pack lacks the libs Node 22/24 + Amazon Linux 2023 need). Fix: upgrade to the latest `@sparticuz/chromium` + matching `puppeteer-core`. |
| `FUNCTION_INVOCATION_FAILED`, ~150 ms duration, `-1MB` memory | The function crashed at **module load**, not at runtime. `@sparticuz/chromium` v149+ and `puppeteer-core` v25+ are **ESM-only** — loading them with CommonJS `require()` crashes on Node 24. Fix: `"type": "module"` in `package.json` and write `api/scrape.js` as ESM (`import …`, `export default async function handler`). |
| Function exceeds size limit | Use `@sparticuz/chromium-min` + host the brotli pack, or keep deps minimal. |
| Timeouts (`status:0`) | Raise `maxDuration` (Pro), keep `memory:1024`, expect a 1–3 s cold-start decompress. |
| `/api/extract` 500: key not set | Add `GEMINI_API_KEY` (§6) and redeploy. |
| `/` or `/app.js` returns 404 while `/api/*` works | The front-end must live in **`public/`** (Vercel serves that dir at root). Adding `package.json` makes Vercel stop serving loose root files; `public/` fixes it unconditionally. Redeploy after moving. |
| `/api/generate` works but forms look wrong | That's the Python/docx path — unrelated to scraping; check the review data. |

---

## 13. Costs

- **Hobby** plan + scale-to-zero ≈ **$0** at low volume (free tier: 2 M
  requests, generous compute). The browser function uses more memory/time per
  call but you only pay while it runs.
- `maxDuration > 60 s` requires **Pro** (~$20/mo) — only needed if PatentScope
  renders slowly.
- **Gemini API** is billed separately (fractions of a cent per extraction).

---

## 14. Rollback / teardown

```powershell
vercel ls                      # list deployments
vercel rollback <url>          # roll back to a previous deployment
vercel remove pct-form-filler  # delete the project entirely
```
