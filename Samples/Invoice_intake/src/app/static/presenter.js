// Presenter screen: /presenter?key=<PRESENTER_KEY>
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const key = new URLSearchParams(location.search).get("key") || "";
  const headers = { "X-Presenter-Key": key };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const eur = (n, cur) => n == null ? "–" : new Intl.NumberFormat("de-AT", { style: "currency", currency: cur || "EUR" }).format(n);
  const time = (iso) => iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
  const BADGE = { AutoApproved: "ok", Approved: "ok", NeedsReview: "warn", Rejected: "bad", NotAnInvoice: "neutral", Failed: "bad", Processing: "neutral" };
  const LABEL = { AutoApproved: "auto-approved", Approved: "approved", NeedsReview: "needs review", Rejected: "rejected", NotAnInvoice: "not an invoice", Failed: "failed", Processing: "processing" };

  $("#url").textContent = location.host;
  const sessionId = "presenter" + Math.random().toString(16).slice(2, 10);

  async function refresh() {
    try {
      const res = await fetch("/api/feed", { headers });
      if (res.status === 401 || res.status === 403) { $("#status").textContent = "Wrong or missing ?key= in the URL"; return; }
      const data = await res.json();
      render(data);
      $("#status").textContent = `Live · updated ${new Date().toLocaleTimeString()}`;
    } catch {
      $("#status").textContent = "Reconnecting…";
    }
  }

  function render({ counters, recent, queue, questions }) {
    let total = 0, auto = 0, review = 0, other = 0, ms = 0, msN = 0;
    for (const c of counters) {
      total += c.N;
      if (c.Status === "AutoApproved") auto += c.N;
      if (c.Status === "NeedsReview") review += c.N;
      if (c.Status === "NotAnInvoice" || c.Status === "Failed") other += c.N;
      if (c.AvgMs) { ms += c.AvgMs * c.N; msN += c.N; }
    }
    $("#s-total").textContent = total;
    $("#s-auto").textContent = auto;
    $("#s-review").textContent = review;
    $("#s-other").textContent = other;
    $("#s-time").textContent = msN ? (ms / msN / 1000).toFixed(1) : "–";

    $("#queue").innerHTML = queue.length ? queue.map((q) => `
      <div class="item" data-id="${q.InvoiceId}">
        <div class="head"><span class="who">${esc(q.VendorName || "Unknown vendor")}<span class="src">${esc(q.Source)}</span></span>
          <span class="amt">${eur(q.TotalAmount, q.Currency)}</span></div>
        <div class="why">${q.InjectionDetected ? "⚠️ " : ""}${esc((q.DecisionReason || "").split(" | ").filter((r) => !r.startsWith("Review agent:")).join(" · "))}</div>
        ${q.AgentSummary ? `<div class="why"><strong>Agent:</strong> ${esc(q.AgentSummary)}</div>` : ""}
        <div class="row">
          <a class="btn" href="/api/invoices/${q.InvoiceId}/document?key=${encodeURIComponent(key)}" target="_blank" rel="noopener">View</a>
          <button class="btn bad" data-act="reject">Reject</button>
          <button class="btn ok" data-act="approve">Approve</button>
        </div>
      </div>`).join("") : '<p class="muted small">Nothing to review.</p>';

    $("#recent").innerHTML = recent.map((r) => `
      <div class="item">
        <div class="head"><span class="who">#${r.InvoiceId} ${esc(r.VendorName || "…")}<span class="src">${esc(r.Source)}</span></span>
          <span class="badge ${BADGE[r.Status] || "neutral"}">${esc(LABEL[r.Status] || r.Status)}</span></div>
        <div class="why">${time(r.ReceivedAt)} · ${eur(r.TotalAmount, r.Currency)}${r.ProcessingMs ? ` · ${(r.ProcessingMs / 1000).toFixed(1)} s` : ""}${r.Status === "Processing" ? ` · ${esc(r.ProcessingStage)}` : ""}</div>
      </div>`).join("");

    $("#questions").innerHTML = questions.length ? questions.map((q) => `
      <div class="item">
        <div class="head"><span class="who">${esc(q.Question)}</span><span class="src">${esc(q.Persona)}</span></div>
        <div class="why">${esc((q.Answer || "").slice(0, 280))}</div>
      </div>`).join("") : '<p class="muted small">No questions yet.</p>';
  }

  $("#queue").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const id = btn.closest(".item").dataset.id;
    btn.disabled = true;
    await fetch(`/api/invoices/${id}/${btn.dataset.act}`, {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify({ comment: "Decided on stage" }),
    });
    refresh();
  });

  // Stage uploads (source = stage)
  async function uploadStage(file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("session_id", sessionId);
    fd.append("source", "stage");
    const res = await fetch("/api/invoices", { method: "POST", body: fd, headers });
    if (!res.ok) alert((await res.json().catch(() => ({}))).detail || "Upload failed");
    refresh();
  }
  const drop = $("#drop");
  drop.onclick = () => $("#stage-file").click();
  $("#stage-file").onchange = (e) => { for (const f of e.target.files) uploadStage(f); e.target.value = ""; };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); for (const f of e.dataTransfer.files) uploadStage(f); };

  refresh();
  setInterval(refresh, 2000);
})();
