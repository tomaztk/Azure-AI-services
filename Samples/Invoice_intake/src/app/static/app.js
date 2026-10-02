// Audience page: scan an invoice, follow its processing, ask the data.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);

  // ---------------------------------------------------------------- session
  function newId() {
    const a = new Uint8Array(12);
    crypto.getRandomValues(a);
    return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  let sessionId;
  try {
    sessionId = localStorage.getItem("ar_session") || newId();
    localStorage.setItem("ar_session", sessionId);
  } catch { sessionId = newId(); }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const eur = (n, cur) => n == null ? "–" : new Intl.NumberFormat("de-AT", { style: "currency", currency: cur || "EUR" }).format(n);

  // ---------------------------------------------------------------- tabs
  function showTab(name) {
    for (const t of ["scan", "ask"]) {
      $(`#tab-${t}`).setAttribute("aria-selected", String(t === name));
      $(`#${t}`).hidden = t !== name;
    }
  }
  $("#tab-scan").onclick = () => showTab("scan");
  $("#tab-ask").onclick = () => showTab("ask");

  // ---------------------------------------------------------------- scan
  let pending = null; // {blob, type, name}

  async function shrinkImage(file) {
    // Phone photos are 3-12 MB; 2000 px JPEG is plenty for OCR and uploads fast on conference Wi-Fi.
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.85));
      return blob || file;
    } catch {
      return file; // e.g. HEIC on a browser that can't decode it: send the original
    }
  }

  async function onPick(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    $("#upload-error").hidden = true;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    const blob = isPdf ? file : await shrinkImage(file);
    pending = { blob, name: isPdf ? file.name : "invoice.jpg" };
    const pv = $("#preview");
    if (isPdf) {
      pv.innerHTML = `<div class="file">📄 ${esc(file.name)}<br><span class="muted small">${(file.size / 1e6).toFixed(1)} MB</span></div>`;
    } else {
      const url = URL.createObjectURL(blob);
      pv.innerHTML = `<img alt="Preview of your photo" src="${url}">`;
    }
    $("#pick").hidden = true;
    $("#result").hidden = true;
    $("#confirm").hidden = false;
  }
  $("#camera").onchange = onPick;
  $("#filepick").onchange = onPick;
  $("#retake").onclick = () => { pending = null; $("#confirm").hidden = true; $("#pick").hidden = false; };

  $("#send").onclick = async () => {
    if (!pending) return;
    const btn = $("#send");
    btn.disabled = true;
    const fd = new FormData();
    fd.append("file", pending.blob, pending.name);
    fd.append("session_id", sessionId);
    fd.append("source", "audience");
    try {
      const res = await fetch("/api/invoices", { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Upload failed (${res.status})`);
      $("#confirm").hidden = true;
      $("#progress").hidden = false;
      setStage("uploaded");
      poll(body.invoice_id);
    } catch (err) {
      const el = $("#upload-error");
      el.textContent = err.message;
      el.hidden = false;
    } finally {
      btn.disabled = false;
    }
  };

  const ORDER = ["uploaded", "reading", "checking", "reviewing", "done"];
  function setStage(stage) {
    const idx = ORDER.indexOf(stage);
    document.querySelectorAll("#steps li").forEach((li, i) => {
      li.className = i < idx || stage === "done" ? "done" : i === idx ? "active" : "";
    });
  }

  async function poll(id) {
    const started = Date.now();
    while (Date.now() - started < 180000) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const res = await fetch(`/api/invoices/${id}?session_id=${encodeURIComponent(sessionId)}`);
        if (!res.ok) continue;
        const inv = await res.json();
        setStage(inv.ProcessingStage || "uploaded");
        if (inv.Status !== "Processing") { renderResult(inv); return; }
      } catch { /* network blip: keep polling */ }
    }
    renderResult({ Status: "Failed", DecisionReason: "This is taking too long. Please try again." });
  }

  const STATUS = {
    AutoApproved: ["ok", "Auto-approved", "All checks passed. Booked without anyone touching it."],
    Approved: ["ok", "Approved", "Approved by a person."],
    NeedsReview: ["warn", "Sent to a person", "Something needs a human look. Here's why:"],
    Rejected: ["bad", "Rejected", "Rejected by a person."],
    NotAnInvoice: ["neutral", "Not an invoice", "Nice try! This doesn't look like an invoice."],
    Failed: ["bad", "Something went wrong", ""],
  };

  function renderResult(inv) {
    $("#progress").hidden = true;
    const [cls, label, intro] = STATUS[inv.Status] || STATUS.Failed;
    // The agent's summary is shown on its own line below, so leave it out of the list.
    const reasons = (inv.DecisionReason || "").split(" | ")
      .filter((r) => r && r !== "All checks passed." && !r.startsWith("Review agent:"));
    const conf = inv.MinFieldConfidence;
    const lines = (inv.Lines || []).map((l) => `
      <tr><td>${esc(l.Description || l.Sku || "")}</td>
          <td class="num">${l.Quantity ?? ""}</td>
          <td class="num">${eur(l.UnitPrice, inv.Currency)}</td>
          <td class="num ${l.PriceDeviationPct > 2 ? "dev-bad" : ""}">${l.PriceDeviationPct != null ? (l.PriceDeviationPct > 0 ? "+" : "") + l.PriceDeviationPct + "%" : "–"}</td></tr>`).join("");
    $("#result").innerHTML = `
      <div class="card">
        <span class="badge ${cls}">${esc(label)}</span>
        <div class="decision">${inv.Status === "AutoApproved" ? "✓ Booked" : esc(label)}</div>
        <p class="muted small" style="margin:0">${esc(intro)}</p>
        ${reasons.length && inv.Status !== "AutoApproved" ? `<ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
        ${inv.AgentSummary ? `<p class="small" style="margin-top:10px"><strong>Review agent:</strong> ${esc(inv.AgentSummary)}</p>` : ""}
        ${inv.ProcessingMs ? `<p class="muted small">Processed in ${(inv.ProcessingMs / 1000).toFixed(1)} s</p>` : ""}
      </div>
      ${inv.VendorName || inv.TotalAmount != null ? `
      <div class="card">
        <h2>What the AI read</h2>
        <table class="kv">
          <tr><td>Vendor</td><td>${esc(inv.VendorName || "–")}</td></tr>
          <tr><td>Invoice number</td><td>${esc(inv.InvoiceNumber || "–")}</td></tr>
          <tr><td>Purchase order</td><td>${esc(inv.PONumber || "missing")}</td></tr>
          <tr><td>Invoice date</td><td>${esc(inv.InvoiceDate || "–")}</td></tr>
          <tr><td>Total</td><td>${eur(inv.TotalAmount, inv.Currency)}</td></tr>
          ${conf != null ? `<tr><td>Lowest confidence</td><td>${conf.toFixed(2)}<span class="conf ${conf < 0.8 ? "low" : ""}"><i style="width:${Math.round(conf * 100)}%"></i></span></td></tr>` : ""}
        </table>
        ${lines ? `<table class="lines"><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Price</th><th class="num">vs contract</th></tr></thead><tbody>${lines}</tbody></table>` : ""}
      </div>` : ""}
      <button class="btn primary big" id="again">Scan another invoice</button>
      <div style="height:8px"></div>
      <button class="btn big" id="to-ask">Ask the data about it →</button>`;
    $("#result").hidden = false;
    $("#again").onclick = () => { $("#result").hidden = true; $("#pick").hidden = false; window.scrollTo(0, 0); };
    $("#to-ask").onclick = () => showTab("ask");
  }

  // ---------------------------------------------------------------- ask
  let persona = "cfo";
  let conversationId = null;
  let asking = false;

  function mdToHtml(md) {
    // Minimal, safe markdown: escape first, then tables, lists, bold and paragraphs.
    const lines = esc(md).split("\n");
    let html = "", i = 0;
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        html += "<table><thead><tr>" + cells(line).map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          html += "<tr>" + cells(lines[i]).map((c) => `<td>${c}</td>`).join("") + "</tr>";
          i++;
        }
        html += "</tbody></table>";
        continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        html += "<ul>";
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          html += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`;
          i++;
        }
        html += "</ul>";
        continue;
      }
      if (line.trim()) html += `<p>${inline(line)}</p>`;
      i++;
    }
    return html;
  }

  function addMsg(role, html, meta) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.innerHTML = html + (meta ? `<div class="meta">${esc(meta)}</div>` : "");
    $("#chat").appendChild(div);
    div.scrollIntoView({ behavior: "smooth", block: "end" });
    return div;
  }

  async function askQuestion(q) {
    q = q.trim();
    if (!q || asking) return;
    asking = true;
    $("#ask-send").disabled = true;
    addMsg("user", esc(q));
    const typing = addMsg("bot", '<span class="typing"><span></span><span></span><span></span></span>');
    try {
      const res = await fetch("/api/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, persona, session_id: sessionId, conversation_id: conversationId }),
      });
      const body = await res.json().catch(() => ({}));
      typing.remove();
      if (!res.ok) throw new Error(body.detail || `Error ${res.status}`);
      conversationId = body.conversation_id;
      const meta = `${(body.duration_ms / 1000).toFixed(1)} s` + (body.tools.length ? ` · tools: ${[...new Set(body.tools)].join(", ")}` : "");
      addMsg("bot", mdToHtml(body.answer), meta);
    } catch (err) {
      typing.remove();
      addMsg("bot", `<p class="error">${esc(err.message)}</p>`);
    } finally {
      asking = false;
      $("#ask-send").disabled = false;
    }
  }

  $("#composer").onsubmit = (e) => {
    e.preventDefault();
    const input = $("#question");
    const q = input.value;
    if (q.trim().length < 3) { input.focus(); return; }
    input.value = "";
    askQuestion(q);
  };

  fetch("/api/config").then((r) => r.json()).then((cfg) => {
    const box = $("#personas");
    for (const [key, label] of Object.entries(cfg.personas)) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label.split(" (")[0];
      b.title = label;
      b.setAttribute("aria-pressed", String(key === persona));
      b.onclick = () => {
        persona = key;
        conversationId = null; // new role, new conversation
        box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        addMsg("bot", `<p class="muted small">You're now asking as <strong>${esc(label)}</strong>.</p>`);
      };
      box.appendChild(b);
    }
    const chips = $("#chips");
    for (const q of cfg.suggested_questions) {
      const c = document.createElement("button");
      c.type = "button";
      c.textContent = q;
      c.onclick = () => askQuestion(q);
      chips.appendChild(c);
    }
  }).catch(() => {});
})();
