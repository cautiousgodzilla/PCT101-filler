# Deploying the PCT → Form 1 Filler (Render + Supabase)

Render runs the app as a Docker container (full Playwright + Chromium for the
PatentScope scrape). Supabase provides auth + the editable firm/agent profiles.
You run every command yourself.

---

## What gets deployed

A single Docker web service started by `local_server.py`:

| Route | Purpose | Needs |
|---|---|---|
| `GET /` + static (`public/`) | Front-end (login, filler, profile) | — |
| `GET /api/config` | Public Supabase config for the browser | — |
| `GET /api/scrape` | PatentScope render + RO/101 PDF (Chromium) | auth |
| `POST /api/extract` | Gemini extraction (+ Google Patents fallback) | auth, `GEMINI_API_KEY` |
| `POST /api/generate` | python-docx fills Forms 1/2/3/5 | auth |
| `GET/POST /api/firm` | Per-firm profile (firm details + agent roster) | auth, Supabase DB |

> PII never lives in the repo: `.env`, `firm_config.json`, `templates_private/`
> are git-ignored. The public templates carry placeholders only.

---

## 1. Commit & push

```bash
cd filler
git add -A
git commit -m "Supabase auth, firm profiles, form fixes"
git push
```
(Pushing auto-redeploys once the Render service exists.)

---

## 2. Supabase setup (one-time)

1. Create a project at supabase.com. From **Project Settings → API**, copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon / publishable key** → `SUPABASE_ANON_KEY`
   - **service_role / secret key** → `SUPABASE_SECRET_KEY` (server-only!)
2. **Authentication → Sign In / Providers → Email →** turn **off "Confirm email"**
   (the built-in email sender is rate-limited; off = immediate login on signup).
3. **Authentication → URL Configuration → Site URL** → your Render URL
   (e.g. `https://pct-form-filler.onrender.com`).
4. **SQL Editor →** paste [`supabase_schema.sql`](supabase_schema.sql) → **Run**
   (creates `firms` / `firm_domains` / `agents` with RLS locked to the service role).
5. **Seed your firm** (firm details + agent roster) into the DB — run locally with
   your `.env` pointing at this Supabase project:
   ```bash
   python seed_firm.py        # reads the git-ignored firm_config.json
   ```
   Now any user in that domain edits it at `/profile`. (If you skip the DB, set
   `FIRM_CONFIG_JSON` instead — see step 4.)

---

## 3. Create the Render web service

1. Render dashboard → **New + → Web Service** → connect the GitHub repo
   `PCT101-filler`.
2. **Runtime:** Docker (auto-detected from `Dockerfile`).
   **Root Directory:** leave blank (the repo root *is* the app).
   **Instance type:** **Starter** (512 MB) to begin; switch to **Standard** (2 GB)
   if Chromium OOMs (502s on `/api/scrape`).
3. Create — the first build installs Chromium (a few minutes).

---

## 4. Environment variables (Render → Environment)

| Key | Value |
|---|---|
| `GEMINI_API_KEY` | your Google Gemini key |
| `SUPABASE_URL` | from step 2 |
| `SUPABASE_ANON_KEY` | from step 2 |
| `SUPABASE_SECRET_KEY` | from step 2 (server-only) |
| `FIRM_CONFIG_JSON` | *optional* — only if you did NOT seed the DB. Minified `firm_config.json`: `python -c "import json;print(json.dumps(json.load(open('firm_config.json'))))"` → paste the one line |

Saving env vars triggers a redeploy. (Your local `.env` is **not** pushed, so
these must be set here.)

---

## 5. Verify

```bash
# Chromium + datacenter-IP check (no auth needed for the bare probe path differs;
# if it 401s, that's auth working — log in via the UI instead):
curl "https://<service>.onrender.com/api/config"        # {"configured": true, ...}
```
Then in the browser:
1. Open the site → redirected to **/login** → **sign up** (immediate, email off).
2. Log in with a firm email (e.g. `@iiprd.com` / `@khuranaandkhurana.com`).
3. **Firm profile** link → confirm the roster; edit/add agents → Save.
4. Enter `WO2024116111` → **Extract** → review → **Generate forms** →
   the `.docx`/`.zip` downloads with the firm + agents filled.

---

## Notes & troubleshooting

| Symptom | Fix |
|---|---|
| `/api/scrape` 502 / OOM | Upgrade Render instance to **Standard** (Chromium needs RAM). |
| `/api/scrape` `403 FORBIDDEN` | PatentScope blocked the datacenter IP (rare) → proxy render service. |
| Login "invalid credentials" | Email confirmation still on, or wrong password — see step 2.2; or confirm the user via SQL: `update auth.users set email_confirmed_at=now() where email='…';` |
| Forms show `[Agent name]`/`[Firm name]` | The user's email domain isn't mapped — add it in the DB (`firm_domains`) or `FIRM_CONFIG_JSON`. |
| Changed `firm_config.json` not reflected | Re-run `python seed_firm.py` (DB) — env/file fallback updates automatically. |

**Costs:** Render Free = $0 (spins down); Starter ≈ $7/mo; Standard ≈ $25/mo.
Supabase + Gemini have free tiers. **Rotate the Gemini key** before going public
(it has been in plaintext locally).
