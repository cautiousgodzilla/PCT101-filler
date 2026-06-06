# TODO

## Firm / agent details — login & auto-insertion (planned)

**Goal.** Let each user (or firm) store their patent-agent details once and have
them inserted into the generated forms automatically — instead of baking any
firm's PII into the templates.

### Why / context
The repo is public, so no firm's personal data may live in it. The real
firm-specific templates (with the agent roster, mobile numbers, IN/PA numbers,
firm address/phones/emails) are kept **out of git**:

- `templates_private/` — the REAL templates (git-ignored). If present, the app
  uses these automatically (see `TEMPLATES_DIR` in `api/_forms.py`).
- `templates/` — PUBLIC, firm-redacted templates committed to the repo. All PII
  is replaced with placeholders: `{firm_name}`, `{firm_address}`, `{firm_phone}`,
  `{firm_email}`, `{agent_name}`, `{agent_inpa}` (agent roster table blanked).
- `firm_details.json` (git-ignored) / `FIRM_*` env vars — the current **interim**
  way to fill those placeholders. Copy `firm_details.example.json`.

### What to build
1. **Auth / login.** User accounts (email + password or SSO). Sessions.
2. **Per-user firm profile.** Persist each user's firm + agent details
   (`firm_name`, `firm_address`, `firm_phone`, `firm_email`, and one or more
   agents: `agent_name`, `agent_inpa`, `agent_mobile`, `agent_email`). Store in a
   DB (e.g. Postgres on Render), not in files.
3. **Auto-fill on generate.** When a logged-in user generates forms, populate the
   `{firm_*}` / `{agent_*}` placeholders from their saved profile. Replace the
   interim `_firm_details()` file/env lookup in `api/_forms.py`.
4. **Per-firm auto-detection.** If the user belongs to a known firm, default the
   firm block automatically; let them pick the signing agent from the roster.
5. **Agent roster table (Form 1 Section 6).** Re-introduce the "Authorized
   Registered Patent Agent(s)" table from the user's saved roster (the public
   template currently leaves it blank) — generate rows dynamically.
6. **Profile UI.** A settings screen to add/edit firm + agents; "remember for
   next time"; manage multiple agents.
7. **Security.** Treat agent mobiles / emails / IN-PA as PII: encrypt at rest,
   scope to the owning user/firm, never log, keep out of any public artifact.

### Acceptance
- A logged-in user's details auto-insert into Forms 1/2/3/5.
- A brand-new user with no profile gets clean forms with blank firm/agent fields
  (today's public behavior).
- No firm PII is ever committed to the repo or returned to another user.

---

## Word output formatting (needs a better approach)

**Problem.** Filling the templates currently mutates `paragraph.text` / clears and
rewrites runs (`_replace_in_paragraphs`, `set_cell_text`, the table builders in
`api/_forms.py`). Setting `paragraph.text` **collapses all runs into one**, which
drops intra-paragraph formatting (bold, italics, font, size, partial styling) and
can disturb spacing/line breaks. Inserted tables also don't inherit the
template's cell styles cleanly. Result: the generated `.docx` doesn't always
match the template's formatting.

**Better means to resolve (pick one):**
1. **Use `docxtpl` (python-docx-template / Jinja2).** Convert the templates to
   `{{ jinja }}` fields and render with `docxtpl` — it preserves the run/paragraph
   formatting of the placeholder itself. Best fit for the firm's styled forms;
   also handles loops (the agent roster + applicant/inventor tables) natively.
2. **Run-aware replacement.** Replace placeholder text *within* runs (and across
   run boundaries by merging only the spanning runs) instead of rewriting whole
   paragraphs, so surrounding formatting survives. More code, no new dependency.
3. **Real table cells with explicit styles.** When building applicant/inventor
   tables, copy the template's cell/paragraph styles (or a reference row) rather
   than creating bare cells.

**Acceptance:** a generated form is visually indistinguishable from the template
(fonts, bold, spacing, table borders, page layout) with only the data changed.

---

## Other / smaller
- [ ] Rotate the Gemini API key before the repo goes public (it was in `.env`).
- [ ] Consider deleting the now-unused Vercel files (`vercel.json`,
      `package.json`, `api/scrape.js`, `.vercelignore`) once Render is the
      committed target — or keep them as a documented fallback.
- [ ] Optionally let the user pick the signing agent in the UI (feeds
      `agent_name` / `agent_inpa` into `/api/generate`).
