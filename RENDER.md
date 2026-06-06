# Deploying the PCT → Form 1 Filler to Render

Render runs a real Docker container, so this build uses **full Playwright +
Chromium** — the exact flow we validated against the live PatentScope site. None
of the Vercel/serverless machinery (`@sparticuz/chromium`, `libnss3`, ESM
shims, the Node `api/scrape.js`) is used here.

---

## 1. What runs on Render

A single **Docker web service** started by [`local_server.py`](local_server.py),
which serves everything:

| Route | Purpose |
|---|---|
| `GET /` + static | Front-end from `public/` |
| `GET /api/scrape?docId=…&pdf=1` | **PatentScope** browser scrape — rendered biblio text + RO/101 PDF ([api/_browser.py](api/_browser.py)) |
| `POST /api/extract` | Gemini structures the PatentScope text / PDFs |
| `POST /api/generate` | python-docx fills Forms 1/2/3/5 |

Flow: the **Extract** button scrapes PatentScope first (primary source) and
feeds the rendered text + RO/101 PDF to Gemini; Google Patents is only a
last-resort fallback. The **Download RO/101 PDF** button also uses `/api/scrape`.

> The Vercel files (`vercel.json`, `package.json`, `api/scrape.js`,
> `.vercelignore`) are now unused. Keep them if you want Vercel as a fallback, or
> delete them — Render ignores them.

---

## 2. Prerequisites

- A **Render account** (free to sign up).
- This folder pushed to a **GitHub/GitLab repo** (Render deploys from Git).
- Your **Google Gemini API key**.

---

## 3. Deploy (dashboard, Docker)

1. Push the repo to GitHub.
2. Render dashboard → **New +** → **Web Service** → connect the repo.
3. Settings:
   - **Runtime:** `Docker` (Render auto-detects the `Dockerfile`).
   - **Root Directory:** set to `filler` **if** the app lives in a `filler/`
     subfolder of your repo (otherwise leave blank).
   - **Instance type:** `Starter` (512 MB) to begin; choose `Standard` (2 GB) if
     you hit out-of-memory/browser crashes (Chromium is RAM-hungry).
4. **Environment** → add a variable:
   - `GEMINI_API_KEY` = your key.
5. **Create Web Service.** Render builds the image (installs Playwright +
   Chromium — first build takes a few minutes) and starts it. You get a
   `https://<service>.onrender.com` URL.

> `PORT` is injected by Render automatically; `local_server.py` reads it. No
> port config needed.

### Or: one-click Blueprint
With [`render.yaml`](render.yaml) committed, use **New + → Blueprint**, point it
at the repo, and Render provisions the service from that file (you'll still be
prompted for `GEMINI_API_KEY`).

---

## 4. Verify

```bash
# Homepage
curl https://<service>.onrender.com/

# PatentScope scrape (the thing Vercel couldn't run). ~10–40 s on a cold start.
curl "https://<service>.onrender.com/api/scrape?docId=WO2024116111&pdf=0"
#   expect: {"ok":true,"hasData":true,"forbidden":false,...,"biblio_text":"...WO2024116111 SYSTEM AND METHOD..."}
```

Then open the site, enter **`WO2024116111`**, click **Extract data** → the
review form fills from PatentScope; **Download RO/101 PDF** returns the PDF.

| Probe result | Meaning |
|---|---|
| `ok:true, hasData:true` | 🎉 PatentScope renders from Render's IP — done |
| `forbidden:true` | Render's IP got a 403 (rare; would need a proxy) |
| 502 / timeout | Cold start or OOM — retry; if it persists, use `Standard` (2 GB) |

---

## 5. Notes & tuning

- **RAM:** one Chromium tab is the memory driver. `Starter` (512 MB) usually
  works with the `--disable-dev-shm-usage` flag already set; `Standard` (2 GB)
  is the safe choice for steady use.
- **Free instances spin down** after ~15 min idle → the first request after that
  is slow (cold start + Chromium launch). `Starter`+ stay warm.
- **Cost:** Free = $0 (with spin-down). Starter ≈ $7/mo. Standard ≈ $25/mo.
  Gemini API is billed separately (fractions of a cent per extraction).
- **`local_server.py` runs this same app locally** — `pip install -r
  requirements.txt && playwright install chromium && python local_server.py`,
  then open http://localhost:8000.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/scrape` 500, "Executable doesn't exist" | The Chromium binary didn't install — ensure the Docker build ran `playwright install chromium` (it's in the `Dockerfile`). |
| Browser crashes / 502 under load | Out of memory — upgrade to `Standard` (2 GB), or reduce concurrency. |
| `403 FORBIDDEN` in scrape result | PatentScope rejected the request — the real Chrome User-Agent is already set; if it's the IP, a proxy/residential egress is needed. |
| `/api/extract` returns empty | No `GEMINI_API_KEY`, or the scrape returned no text — check the `_meta.notes` in the response. |
