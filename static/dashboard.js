/* Dashboard: list, search, create, import, download and delete CVs. */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const STATUS = { new: "New", in_review: "In review", ready: "Ready" };
  const SOURCE = { website: "Website", upload: "File import", manual: "Created here",
                   student: "Student form" };
  const filter = { status: "", q: "" };

  function toast(message, isError = false) {
    const t = document.createElement("div");
    t.className = "toast" + (isError ? " is-error" : "");
    t.textContent = message;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), isError ? 6000 : 3000);
  }

  async function api(url, options = {}) {
    const res = await fetch(url, options);
    if (res.status === 401) { location.href = "/login"; throw new Error("Please sign in again."); }
    if (!res.ok) {
      let msg = `Request failed (${res.status}).`;
      try { msg = (await res.json()).error || msg; } catch { /* keep */ }
      throw new Error(msg);
    }
    return res;
  }

  function when(ts) {
    const d = new Date(ts * 1000);
    const mins = Math.round((Date.now() - d) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    if (mins < 24 * 60) return `${Math.round(mins / 60)} h ago`;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  async function load() {
    const params = new URLSearchParams({ q: filter.q, status: filter.status });
    let data;
    try {
      data = await (await api(`/api/cvs?${params}`)).json();
    } catch (err) {
      toast(err.message, true);
      return;
    }
    const counts = data.counts;
    document.querySelectorAll("[data-count]").forEach((el) => {
      const k = el.dataset.count;
      const n = k === "all" ? Object.values(counts).reduce((a, b) => a + b, 0) : counts[k];
      el.textContent = n ? n : "";
    });

    $("#rows").innerHTML = data.items.map((cv) => `
      <tr>
        <td class="cv-name">
          <a href="/edit/${cv.id}">${esc(cv.name || "Untitled CV")}</a>
          <small>${esc(cv.email || "")}${cv.external_id ? `${cv.email ? " · " : ""}website id ${esc(cv.external_id)}` : ""}</small>
          ${cv.warnings.length ? `<small class="warn">${cv.warnings.length} thing${cv.warnings.length > 1 ? "s" : ""} to check</small>` : ""}
        </td>
        <td><span class="pill ${cv.status}">${STATUS[cv.status] || cv.status}</span></td>
        <td class="muted">${SOURCE[cv.source] || esc(cv.source)}</td>
        <td class="muted" title="${new Date(cv.updated_at * 1000).toLocaleString()}">${when(cv.updated_at)}</td>
        <td class="row-actions-cell">
          <a class="btn" href="/edit/${cv.id}">Edit</a>
          <a class="btn" href="/api/cvs/${cv.id}/export/pdf" data-download>PDF</a>
          <button class="btn btn-danger" data-delete="${cv.id}" data-name="${esc(cv.name || "this CV")}">Delete</button>
        </td>
      </tr>`).join("");

    const empty = $("#empty");
    empty.hidden = data.items.length > 0;
    if (!data.items.length) {
      empty.innerHTML = filter.q || filter.status
        ? "<strong>No CVs match</strong>Try another search or status."
        : "<strong>No CVs yet</strong>CVs sent by the website appear here automatically. You can also start one from scratch, or upload a CV in almost any format: PDF, Word, text, a spreadsheet, a web page, or a photo of a printed CV.";
    }
  }

  async function downloadLink(a) {
    try {
      const res = await api(a.href);
      const blob = await res.blob();
      const name = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "cv.pdf";
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    } catch (err) {
      toast(err.message, true);
    }
  }

  function wire() {
    document.querySelectorAll(".status-tabs button").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll(".status-tabs button").forEach((x) => x.classList.toggle("is-active", x === b));
      filter.status = b.dataset.status;
      load();
    }));

    let t;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { filter.q = e.target.value; load(); }, 250);
    });

    $("#rows").addEventListener("click", async (e) => {
      const dl = e.target.closest("[data-download]");
      const del = e.target.closest("[data-delete]");
      if (dl) { e.preventDefault(); downloadLink(dl); }
      if (del) {
        if (!confirm(`Delete ${del.dataset.name}? This cannot be undone.`)) return;
        try {
          await api(`/api/cvs/${del.dataset.delete}`, { method: "DELETE" });
          toast("CV deleted.");
          load();
        } catch (err) { toast(err.message, true); }
      }
    });

    $("#newBtn").addEventListener("click", async () => {
      try {
        const cv = await (await api("/api/cvs", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json();
        location.href = `/edit/${cv.id}`;
      } catch (err) { toast(err.message, true); }
    });

    $("#importBtn").addEventListener("click", () => $("#importInput").click());
    $("#guideUpload").addEventListener("click", () => $("#importInput").click());
    $("#shareBtn").addEventListener("click", shareFormLink);
    $("#guideNew").addEventListener("click", () => $("#newBtn").click());
    $("#importInput").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      try {
        const cv = await (await api("/api/cvs/import", { method: "POST", body: form })).json();
        location.href = `/edit/${cv.id}`;
      } catch (err) { toast(err.message, true); }
      e.target.value = "";
    });
  }

  async function start() {
    wire();
    try {
      const meta = await (await api("/api/meta")).json();
      $("#logoutForm").hidden = !meta.password;
      const notes = [];
      if (!meta.password) notes.push("No staff password is set, so anyone who can open this address can see the CVs. Set <b>ADMIN_PASSWORD</b> in the .env file before putting this online.");
      if (!meta.website_api) notes.push("The website API is off. Set <b>API_KEYS</b> in the .env file so the client's website can send student details.");
      if (new URLSearchParams(location.search).has("missing")) notes.push("That CV no longer exists.");
      if (notes.length) { $("#notice").innerHTML = notes.join("<br>"); $("#notice").hidden = false; }
    } catch (err) { toast(err.message, true); }
    load();
    setInterval(() => { if (!document.hidden) load(); }, 30000); // new website submissions appear without reloading
    maybeShowCoach();
  }

  /** Copy the student form link so staff can paste it into an email. */
  async function shareFormLink() {
    try {
      const { url } = await api("/api/form-link");
      try {
        await navigator.clipboard.writeText(url);
        toast("Link copied. Paste it into an email or message to the student.");
      } catch {
        window.prompt("Copy this link and send it to the student:", url);
      }
    } catch (err) {
      toast(err.message || "Could not get the link.", true);
    }
  }

  function maybeShowCoach() {
    let seen = false;
    try { seen = localStorage.getItem("cv_coach_seen") === "1"; } catch {}
    if (seen) return;
    const target = document.querySelector("#importBtn");
    const coach = document.querySelector("#coach");
    const pop = document.querySelector("#coachPop");
    if (!target || !coach) return;

    const place = () => {
      const r = target.getBoundingClientRect();
      let hi = coach.querySelector(".coach-highlight");
      if (!hi) { hi = document.createElement("div"); hi.className = "coach-highlight"; coach.appendChild(hi); }
      hi.style.left = `${r.left - 6}px`;
      hi.style.top = `${r.top - 6}px`;
      hi.style.width = `${r.width + 12}px`;
      hi.style.height = `${r.height + 12}px`;
      pop.style.top = `${r.bottom + 14}px`;
      pop.style.left = `${Math.max(12, Math.min(r.right - pop.offsetWidth, window.innerWidth - pop.offsetWidth - 12))}px`;
    };

    coach.hidden = false;
    place();
    window.addEventListener("resize", place);

    const dismiss = () => {
      coach.hidden = true;
      try { localStorage.setItem("cv_coach_seen", "1"); } catch {}
      window.removeEventListener("resize", place);
    };
    document.querySelector("#coachGotIt").addEventListener("click", dismiss);
    coach.querySelector(".coach-backdrop").addEventListener("click", dismiss);
    // clicking the highlighted button both dismisses the coach and opens the picker
    target.addEventListener("click", dismiss, { once: true });
  }

  start();
})();