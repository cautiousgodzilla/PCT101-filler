/* PCT -> FORM 1 filler front-end */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function personRow(kind, p = {}) {
    const block = document.createElement("div");
    block.className = "row-block";
    block.dataset.kind = kind;
    block.innerHTML = `
      <button type="button" class="btn-danger rm">Remove</button>
      <div class="grid g2">
        <div class="field"><label>Name in full</label><input type="text" class="f-name" /></div>
        <div class="field"><label>Nationality</label><input type="text" class="f-nationality" /></div>
      </div>
      <div class="grid g2">
        <div class="field"><label>Country of residence</label><input type="text" class="f-country" /></div>
        <div class="field"><label></label></div>
      </div>
      <div class="field"><label>Address (comma kept before country)</label><textarea class="f-address"></textarea></div>
    `;
    block.querySelector(".f-name").value = p.name || "";
    block.querySelector(".f-nationality").value = p.nationality || "";
    block.querySelector(".f-country").value = p.country_of_residence || "";
    block.querySelector(".f-address").value = p.address || "";
    block.querySelector(".rm").addEventListener("click", () => block.remove());
    return block;
  }

  function addPerson(kind, data) {
    $(kind === "applicant" ? "applicants" : "inventors").appendChild(personRow(kind, data));
  }

  function collectPeople(containerId) {
    return Array.from($(containerId).querySelectorAll(".row-block")).map((b) => ({
      name: b.querySelector(".f-name").value.trim(),
      nationality: b.querySelector(".f-nationality").value.trim(),
      country_of_residence: b.querySelector(".f-country").value.trim(),
      address: b.querySelector(".f-address").value.trim(),
    })).filter((p) => p.name || p.address);
  }

  function fillForm(d) {
    d = d || {};
    $("title_of_invention").value = d.title_of_invention || "";
    $("international_application_no").value = d.international_application_no || "";
    $("international_filing_date").value = d.international_filing_date || "";
    const pr = d.priority_details || {};
    $("pr_country").value = pr.country || "";
    $("pr_application_number").value = pr.application_number || "";
    $("pr_filing_date").value = pr.filing_date || "";
    $("pr_applicant_name").value = pr.applicant_name || "";
    $("pr_title").value = pr.title || "";
    $("pr_ipc").value = pr.ipc || "";
    if (d.category_of_applicant) $("category_of_applicant").value = d.category_of_applicant;
    $("application_number").value = d.application_number || "";
    $("filing_date").value = d.filing_date || "";
    ["description_pages", "claims_pages_listed", "abstract_pages_listed", "drawings_pages_listed"].forEach((k) => {
      $(k).value = d[k] != null ? d[k] : "";
    });

    $("applicants").innerHTML = "";
    (d.applicants && d.applicants.length ? d.applicants : [{}]).forEach((a) => addPerson("applicant", a));
    $("inventors").innerHTML = "";
    (d.inventors && d.inventors.length ? d.inventors : [{}]).forEach((i) => addPerson("inventor", i));

    $("reviewForm").classList.remove("hidden");
    $("reviewForm").scrollIntoView({ behavior: "smooth" });
  }

  function collectForm() {
    const num = (id) => parseInt($(id).value, 10) || 0;
    const forms = Array.from(document.querySelectorAll(".form-chk:checked")).map((c) => c.value);
    return {
      forms,
      title_of_invention: $("title_of_invention").value.trim(),
      international_application_no: $("international_application_no").value.trim(),
      international_filing_date: $("international_filing_date").value.trim(),
      category_of_applicant: $("category_of_applicant").value,
      application_number: $("application_number").value.trim(),
      filing_date: $("filing_date").value.trim(),
      priority_details: {
        country: $("pr_country").value.trim(),
        application_number: $("pr_application_number").value.trim(),
        filing_date: $("pr_filing_date").value.trim(),
        applicant_name: $("pr_applicant_name").value.trim(),
        title: $("pr_title").value.trim(),
        ipc: $("pr_ipc").value.trim(),
      },
      applicants: collectPeople("applicants"),
      inventors: collectPeople("inventors"),
      claims_count: num("claims_count"),
      drawings_count: num("drawings_count"),
      description_pages: num("description_pages"),
      claims_pages_listed: num("claims_pages_listed"),
      abstract_pages_listed: num("abstract_pages_listed"),
      drawings_pages_listed: num("drawings_pages_listed"),
    };
  }

  const fileToB64 = (file) =>
    new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",", 2)[1]);
      r.onerror = reject;
      r.readAsDataURL(file);
    });

  function setStatus(el, msg, cls) {
    el.className = cls || "";
    el.innerHTML = msg;
  }

  // ---- events ----
  $("pdfs").addEventListener("change", () => {
    const names = Array.from($("pdfs").files).map((f) => f.name);
    $("filelist").textContent = names.length ? "Attached: " + names.join(", ") : "";
  });

  $("btnManual").addEventListener("click", () => fillForm({}));

  // Download the RO/101 Request form PDF via the PatentScope browser scraper.
  $("btnRo101").addEventListener("click", async () => {
    const status = $("status");
    const num = $("pct_number").value.trim();
    if (!num) {
      setStatus(status, "Enter the international / publication number first.", "status-err");
      return;
    }
    setStatus(status, '<span class="spin"></span> Fetching RO/101 from PatentScope…', "status-busy");
    $("btnRo101").disabled = true;
    try {
      const res = await fetch(`/api/scrape?docId=${encodeURIComponent(num)}&pdf=1`, { headers: await Auth.getAuthHeader() });
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) {
        throw new Error((d.notes && d.notes.join("; ")) || d.error || "PatentScope scrape failed.");
      }
      if (!d.ro101 || !d.ro101.pdf_base64) {
        const link = d.ro101 && d.ro101.href;
        if (link) { window.open(link, "_blank"); setStatus(status, "Opened the RO/101 link in a new tab (PDF bytes unavailable).", "status-ok"); return; }
        throw new Error("RO/101 PDF link not found on the page.");
      }
      const bin = atob(d.ro101.pdf_base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `RO101_${num.replace(/[^A-Za-z0-9]/g, "_")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(status, `✓ RO/101 PDF downloaded (${(d.ro101.pdf_bytes / 1024).toFixed(0)} KB).`, "status-ok");
    } catch (e) {
      setStatus(status, "✗ RO/101 download failed: " + e.message, "status-err");
    } finally {
      $("btnRo101").disabled = false;
    }
  });

  $("btnExtract").addEventListener("click", async () => {
    const status = $("status");
    const pct = $("pct_number").value.trim();
    const files = Array.from($("pdfs").files);
    if (!pct && !files.length) {
      setStatus(status, "Enter a number or attach at least one PDF.", "status-err");
      return;
    }
    $("btnExtract").disabled = true;
    try {
      const pdfs = await Promise.all(
        files.map(async (f) => ({ mime: f.type || "application/pdf", data: await fileToB64(f) }))
      );

      // 1) PRIMARY: scrape the live PatentScope page (rendered text + RO/101 PDF).
      let biblioText = "";
      const preNotes = [];
      if (pct) {
        setStatus(status, '<span class="spin"></span> Reading PatentScope…', "status-busy");
        try {
          const sres = await fetch(`/api/scrape?docId=${encodeURIComponent(pct)}&pdf=1`, { headers: await Auth.getAuthHeader() });
          const sd = await sres.json().catch(() => ({}));
          if (sd && sd.ok) {
            biblioText = sd.biblio_text || "";
            preNotes.push("PatentScope page scraped.");
            if (sd.ro101 && sd.ro101.pdf_base64) {
              pdfs.push({ mime: "application/pdf", data: sd.ro101.pdf_base64 });
              preNotes.push("RO/101 PDF retrieved from PatentScope.");
            }
          } else {
            preNotes.push("PatentScope unavailable" + (sd && sd.notes && sd.notes.length ? " (" + sd.notes.join("; ") + ")" : "") + " — using fallback.");
          }
        } catch (e) {
          preNotes.push("PatentScope scrape error: " + e.message + " — using fallback.");
        }
      }

      // 2) Extract structured fields (Gemini reads the PatentScope text + PDFs).
      setStatus(status, '<span class="spin"></span> Extracting fields…', "status-busy");
      const res = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await Auth.getAuthHeader()) },
        body: JSON.stringify({ pct_number: pct, biblio_text: biblioText, pdfs }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Extraction failed");
      fillForm(data);
      const meta = data._meta || {};
      const notes = preNotes.concat(meta.notes || []).map((n) => "• " + n).join("<br>");
      setStatus(status, "✓ Data extracted — please review carefully." + (notes ? "<br>" + notes : ""), "status-ok");
    } catch (e) {
      setStatus(status, "✗ " + e.message + " — you can still fill the form manually.", "status-err");
      fillForm({});
    } finally {
      $("btnExtract").disabled = false;
    }
  });

  document.addEventListener("click", (e) => {
    const add = e.target.dataset && e.target.dataset.add;
    if (add) addPerson(add, {});
  });

  $("reviewForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const gs = $("genstatus");
    setStatus(gs, '<span class="spin"></span> Generating…', "status-busy");
    $("btnGenerate").disabled = true;
    try {
      const payload = collectForm();
      if (!payload.forms.length) throw new Error("Select at least one form to generate.");
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await Auth.getAuthHeader()) },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Generation failed");
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const filename = m ? m[1] : "Form_1.docx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(gs, "✓ Downloaded " + filename, "status-ok");
    } catch (e) {
      setStatus(gs, "✗ " + e.message, "status-err");
    } finally {
      $("btnGenerate").disabled = false;
    }
  });

  // ---- auth gate + user bar (no-op when Supabase isn't configured) ----
  (async () => {
    if (!(await Auth.requireAuthOrRedirect("/login.html"))) return; // redirected
    if (!(await Auth.isConfigured())) return; // auth disabled -> nothing to show
    const user = await Auth.getUser();
    const bar = $("userbar");
    if (user && bar) {
      bar.innerHTML =
        '<span style="opacity:.9">' + (user.email || "signed in") + '</span> ' +
        '<a href="/profile.html" style="margin-left:8px;color:#dbeafe;font-size:12px;">Firm profile</a> ' +
        '<button id="btnSignOut" style="margin-left:8px;cursor:pointer;border:1px solid #ffffff66;background:transparent;color:#fff;border-radius:6px;padding:4px 10px;font-size:12px;">Sign out</button>';
      document.getElementById("btnSignOut").addEventListener("click", async () => {
        await Auth.signOut();
        window.location.href = "/login.html";
      });
    }
  })();
})();
