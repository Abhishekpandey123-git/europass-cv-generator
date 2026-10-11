/* Europass CV editor
 * ------------------------------------------------------------------------
 * The CV lives in one JSON object (state.cv). The server renders it with the
 * same template used for the PDF; the page is shown in an iframe where text
 * marked with data-path can be edited in place and blocks marked with
 * data-select can be selected. The side panels edit everything else.
 */
(() => {
  "use strict";

  const CV_ID = (location.pathname.match(/^\/edit\/([\w-]+)/) || [])[1];
  const LEVELS = ["", "A1", "A2", "B1", "B2", "C1", "C2"];
  const LEVEL_KEYS = [
    ["listening", "Listen"], ["reading", "Read"], ["spoken_production", "Speak"],
    ["spoken_interaction", "Interact"], ["writing", "Write"],
  ];
  const LICENCES = ["AM", "A1", "A2", "A", "B1", "B", "BE", "C1", "C1E", "C", "CE", "D1", "D1E", "D", "DE"];

  // The optional Europass sections, each with its own fields. These used to be
  // free-text {heading, text} pairs, which could not hold a date, a location or
  // a link - so none of that reached the XML. Field lists mirror sections.py.
  const TYPED_SECTIONS = {
    certifications:   { label: "Certifications",
                        fields: ["title", "organisation", "date", "mode", "url", "description"],
                        blank: { title: "Certificate name", organisation: "", date: "", mode: "", url: "", description: "" } },
    honours_awards:   { label: "Honours and awards",
                        fields: ["title", "organisation", "date", "description"],
                        blank: { title: "Award name", organisation: "", date: "", description: "" } },
    conferences:      { label: "Conferences and seminars",
                        fields: ["title", "start", "end", "location", "url", "description"],
                        blank: { title: "Conference name", start: "", end: "", location: "", url: "", description: "" } },
    creative_works:   { label: "Creative works",
                        fields: ["title", "start", "end", "url", "description"],
                        blank: { title: "Work title", start: "", end: "", url: "", description: "" } },
    projects:         { label: "Projects",
                        fields: ["title", "start", "end", "url", "description"],
                        blank: { title: "Project name", start: "", end: "", url: "", description: "" } },
    publications:     { label: "Publications",
                        fields: ["title", "year", "authors", "journal", "publisher", "volume", "doi", "reference", "description"],
                        blank: { title: "Publication title", year: "", authors: "", journal: "", publisher: "", volume: "", doi: "", reference: "", description: "" } },
    recommendations:  { label: "Recommendations",
                        fields: ["name", "role", "email", "phone_dialing", "phone", "description"],
                        blank: { name: "Referee name", role: "", email: "", phone_dialing: "", phone: "", description: "" } },
    social_political: { label: "Social and political activities",
                        fields: ["title", "start", "end", "location", "description"],
                        blank: { title: "Activity name", start: "", end: "", location: "", description: "" } },
    volunteering:     { label: "Volunteering",
                        fields: ["title", "start", "end", "location", "description"],
                        blank: { title: "Role", start: "", end: "", location: "", description: "" } },
    networks:         { label: "Networks and memberships",
                        fields: ["title", "start", "end", "location", "description"],
                        blank: { title: "Network name", start: "", end: "", location: "", description: "" } },
    hobbies:          { label: "Hobbies and interests",
                        fields: ["title", "description"],
                        blank: { title: "Interest", description: "" } },
  };

  const FIELD_LABELS = {
    title: "Title", organisation: "Organisation", date: "Date", mode: "Mode of learning",
    url: "Link", description: "Description", start: "From", end: "To", location: "Location",
    year: "Year", authors: "Authors", journal: "Journal name", publisher: "Publisher",
    volume: "Volume, issue and pages", doi: "DOI", reference: "Reference",
    name: "Name", role: "Role", email: "Email", phone: "Phone number",
    phone_dialing: "Country dialling code",
  };
  const TYPED_KEYS = Object.keys(TYPED_SECTIONS);

  const SWATCHES = [
    ["#0c56a5", "Europass blue"], ["#1f4e79", "Navy"], ["#2e6b57", "Forest"],
    ["#7a2e4a", "Burgundy"], ["#a4541c", "Rust"], ["#3b3f45", "Graphite"],
  ];

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const state = {
    cv: null,
    meta: null,
    selected: null,
    history: [],
    future: [],
    typingGroup: null,
    zoom: 1,
    renderSeq: 0,
    renderTimer: null,
    saveTimer: null,
    saving: null,
    unsaved: false,
    record: null,
  };

  const els = {
    page: $("#page"),
    pageWrap: $("#pageWrap"),
    canvas: $("#canvas"),
    inspector: $("#inspector"),
    sectionList: $("#sectionList"),
    saveState: $("#saveState"),
    undo: $("#undoBtn"),
    redo: $("#redoBtn"),
    zoomFit: $("#zoomFit"),
    fileInput: $("#fileInput"),
  };

  // ---------------------------------------------------------------- utils --

  const clone = (o) => JSON.parse(JSON.stringify(o));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function splitPath(path) {
    return String(path).split(".").map((k) => (/^\d+$/.test(k) ? Number(k) : k));
  }

  function getPath(obj, path) {
    return splitPath(path).reduce((o, k) => (o == null ? undefined : o[k]), obj);
  }

  function setPath(obj, path, value) {
    const keys = splitPath(path);
    let o = obj;
    keys.slice(0, -1).forEach((k, i) => {
      if (o[k] == null || typeof o[k] !== "object") o[k] = typeof keys[i + 1] === "number" ? [] : {};
      o = o[k];
    });
    o[keys[keys.length - 1]] = value;
  }

  function thisMonth() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function toMonth(v) {
    if (!v) return "";
    const s = String(v);
    if (/^\d{4}$/.test(s)) return `${s}-01`;
    return s.slice(0, 7);
  }

  function toast(message, isError = false) {
    const t = document.createElement("div");
    t.className = "toast" + (isError ? " is-error" : "");
    t.textContent = message;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), isError ? 6000 : 3200);
  }

  async function api(url, options = {}) {
    const res = await fetch(url, options);
    if (res.status === 401) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      throw new Error("Please sign in again.");
    }
    if (!res.ok) {
      let msg = `Request failed (${res.status}).`;
      try { msg = (await res.json()).error || msg; } catch { /* keep default */ }
      throw new Error(msg);
    }
    return res;
  }

  const postJSON = (url, body) => api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  // ------------------------------------------------------ design + order --

  function design() {
    state.cv.design = Object.assign(clone(state.meta.design), state.cv.design || {});
    return state.cv.design;
  }

  function customSections() {
    const list = state.cv.additional_sections || (state.cv.additional_sections = []);
    // same rule as the server (cv_design.ensure_ids): s1, s2, ... for sections without an id
    const used = new Set(list.map((s) => s.id).filter(Boolean));
    let n = 1;
    list.forEach((s) => {
      if (s.id) return;
      while (used.has(`s${n}`)) n++;
      s.id = `s${n}`;
      used.add(s.id);
    });
    return list;
  }

  function sectionOrder() {
    const d = design();
    const valid = [...Object.keys(state.meta.sections), ...customSections().map((s) => `custom:${s.id}`)];
    const order = (d.section_order || []).filter((k) => valid.includes(k));
    valid.forEach((k) => { if (!order.includes(k)) order.push(k); });
    d.section_order = order;
    return order;
  }

  function sectionLabel(key) {
    if (key.startsWith("custom:")) {
      const sec = customSections().find((s) => `custom:${s.id}` === key);
      return (sec && sec.title) || "Untitled section";
    }
    return state.meta.sections[key] || key;
  }

  const sectionSelectKey = (key) =>
    ({ about: "section:about", work_experience: "section:work_experience", education: "section:education" }[key] || key);

  // -------------------------------------------------------------- history --

  function snapshot() { return JSON.stringify(state.cv); }

  function pushHistory() {
    state.history.push(snapshot());
    if (state.history.length > 150) state.history.shift();
    state.future = [];
    updateUndoButtons();
  }

  /** Structural change: one undo step, then re-render page + panels. */
  function commit(mutate, { select, inspector = true } = {}) {
    closeTypingGroup();
    pushHistory();
    mutate(state.cv);
    if (select !== undefined) state.selected = select;
    afterChange({ inspector });
  }

  /** Typing change: consecutive keystrokes are grouped into one undo step. */
  function update(path, value, { render = true } = {}) {
    if (!state.typingGroup) pushHistory();
    clearTimeout(state.typingGroup);
    state.typingGroup = setTimeout(closeTypingGroup, 900);
    setPath(state.cv, path, value);
    scheduleSave();
    if (render) scheduleRender();
    else syncInspectorValues();
  }

  function closeTypingGroup() {
    clearTimeout(state.typingGroup);
    state.typingGroup = null;
  }

  function afterChange({ inspector = true } = {}) {
    scheduleSave();
    renderSections();
    renderDesign();
    if (inspector) renderInspector();
    renderPage();
  }

  function undo() {
    closeTypingGroup();
    if (!state.history.length) return;
    state.future.push(snapshot());
    state.cv = JSON.parse(state.history.pop());
    updateUndoButtons();
    afterChange();
  }

  function redo() {
    if (!state.future.length) return;
    state.history.push(snapshot());
    state.cv = JSON.parse(state.future.pop());
    updateUndoButtons();
    afterChange();
  }

  function updateUndoButtons() {
    els.undo.disabled = !state.history.length;
    els.redo.disabled = !state.future.length;
  }

  // ------------------------------------------------------------- autosave --

  function setSaveState(text, isError = false) {
    els.saveState.textContent = text;
    els.saveState.classList.toggle("is-error", isError);
  }

  function scheduleSave() {
    state.unsaved = true;
    setSaveState("Saving…");
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(saveNow, 700);
  }

  async function saveNow() {
    clearTimeout(state.saveTimer);
    if (state.saving) { state.saveTimer = setTimeout(saveNow, 300); return; }
    const body = snapshot();
    state.saving = (async () => {
      try {
        const res = await api(`/api/cvs/${CV_ID}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: `{"cv":${body}}`,
        });
        const saved = await res.json();
        if (snapshot() === body) state.unsaved = false;
        applyRecord(saved);
        setSaveState(state.unsaved ? "Saving…" : "All changes saved");
      } catch (err) {
        setSaveState("Not saved. Retrying…", true);
        state.saveTimer = setTimeout(saveNow, 4000);
      } finally {
        state.saving = null;
      }
    })();
    return state.saving;
  }

  function applyRecord(rec) {
    state.record = Object.assign(state.record || {}, rec);
    const name = state.record.name || "Untitled CV";
    $("#cvName").textContent = name;
    document.title = `${name} · Europass CV service`;
    const sel = $("#statusSelect");
    sel.value = state.record.status;
    sel.dataset.v = state.record.status;
    renderChecks();
  }

  function renderChecks() {
    const box = $("#checks");
    const list = (state.record && state.record.warnings) || [];
    box.hidden = !list.length;
    box.innerHTML = list.length ? `<strong>Check before sending (${list.length})</strong>
      <ul>${list.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      <button class="btn small" id="clearChecks">Mark all as checked</button>` : "";
  }

  // ----------------------------------------------------------- page render --

  function scheduleRender() {
    clearTimeout(state.renderTimer);
    state.renderTimer = setTimeout(renderPage, 300);
  }

  async function renderPage(focusPath) {
    clearTimeout(state.renderTimer);
    const seq = ++state.renderSeq;
    let html;
    try {
      html = (await (await postJSON("/api/render", { cv: state.cv })).json()).html;
    } catch (err) {
      toast(`The page could not be updated: ${err.message}`, true);
      return;
    }
    if (seq !== state.renderSeq) return; // a newer render is on its way

    const scroll = els.canvas.scrollTop;
    const doc = els.page.contentDocument;
    if (!focusPath) {
      // keep the caret where it was if the user is typing on the page
      const active = doc.activeElement && doc.activeElement.closest && doc.activeElement.closest("[data-path]");
      if (active) { focusPath = active.dataset.path; var caret = caretOffset(doc, active); }
    }
    doc.open();
    doc.write(html);
    doc.close();
    wirePage(doc);
    highlightSelection(false);
    els.canvas.scrollTop = scroll;

    const fit = () => resizePage(doc);
    fit();
    (doc.fonts ? doc.fonts.ready : Promise.resolve()).then(fit);

    if (focusPath) {
      const target = doc.querySelector(`[data-path="${CSS.escape(focusPath)}"]`);
      if (target) placeCaret(doc, target, caret);
    }
  }

  function caretOffset(doc, el) {
    const sel = doc.getSelection();
    if (!sel.rangeCount) return undefined;
    const range = sel.getRangeAt(0).cloneRange();
    range.selectNodeContents(el);
    range.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
    return range.toString().length;
  }

  /** Focus el and put the caret at a text offset (default: the end). */
  function placeCaret(doc, el, offset) {
    el.focus();
    const range = doc.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    if (offset !== undefined) {
      const walker = doc.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let left = offset;
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (left <= node.length) { range.setStart(node, left); range.collapse(true); break; }
        left -= node.length;
      }
    }
    const sel = doc.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  const MM = 96 / 25.4;
  const GAP_PX = 28;                       // grey gap between page sheets (screen px)

  /**
   * Lay the CV out as separate page sheets, like Canva: page 1, a grey gap,
   * page 2, and so on. The CV stays one editable document; at each real page
   * break we push the first block that would cross the seam down onto the next
   * sheet (which also opens the grey gap), then draw the blue Europass frame
   * for each sheet and the grey strip that hides the join.
   */
  function resizePage(doc) {
    const body = doc.body;
    if (!body) return;
    doc.querySelectorAll(".page-frame, .page-gap").forEach((n) => n.remove());
    body.querySelectorAll("[data-pushed]").forEach((el) => {
      el.style.marginTop = el.dataset.pushed;      // undo the previous pass's nudges
      el.removeAttribute("data-pushed");
    });
    body.style.position = "relative";

    const firstTop = Number(body.dataset.firstTop || 10);
    const top = Number(body.dataset.top || 10);
    const bottom = Number(body.dataset.bottom || 12);
    const pageContent = (297 - top - bottom) * MM;    // usable height of a normal page
    const firstContent = (297 - firstTop - bottom) * MM;
    const sheetH = 297 * MM;

    // Blocks that must not be split across a page: each entry (a job or a
    // course), and the language table. Sections themselves can span two pages
    // as long as each entry inside them stays whole.
    const blocks = [...body.querySelectorAll(".entry, .other-languages")]
      .filter((el) => !el.closest(".entry .entry") && el.offsetParent);

    // Sections are position:relative (for z-indexing), so an entry's offsetTop
    // is measured against its section, not the body. Walk the offsetParent
    // chain to get the y in body coordinates.
    const absTop = (el) => {
      let y = 0, cur = el;
      while (cur && cur !== body) { y += cur.offsetTop; cur = cur.offsetParent; }
      return y;
    };

    // Page 1's content area in body coordinates. The body's own padding-top
    // gives the first page's top margin; usable content on the first sheet ends
    // where its bottom margin begins.
    const firstTopPX = firstTop * MM;
    const topPX = top * MM;
    const bottomPX = bottom * MM;
    const seamAdvance = bottomPX + GAP_PX + topPX + pageContent;    // per-break growth of pageBottom

    const sheetTops = [0];                 // body-y of each sheet's top edge
    let pageBottom = firstTopPX + firstContent;    // body-y where current page's content ends

    const pushDown = (el, extra) => {
      const prev = parseFloat(getComputedStyle(el).marginTop) || 0;
      el.dataset.pushed = el.style.marginTop || "";
      el.style.marginTop = `${prev + extra}px`;
    };

    for (const el of blocks) {
      const boxTop = absTop(el);           // live: reflects earlier pushes
      const h = el.offsetHeight;
      // Advance to the current page if this block already sits past a break.
      while (boxTop >= pageBottom - 0.5) {
        sheetTops.push(pageBottom + bottomPX + GAP_PX);
        pageBottom += seamAdvance;
      }
      if (boxTop + h <= pageBottom + 1) continue;      // fits on this sheet
      if (h <= pageContent) {
        // straddles: drop it onto the next sheet, past the grey gap
        const nextTop = pageBottom + bottomPX + GAP_PX + topPX;
        pushDown(el, nextTop - boxTop);
        sheetTops.push(pageBottom + bottomPX + GAP_PX);
        pageBottom += seamAdvance;
      } else {
        // taller than a whole page — let it flow, but count the pages it spans
        while (boxTop + h > pageBottom + 1) {
          sheetTops.push(pageBottom + bottomPX + GAP_PX);
          pageBottom += seamAdvance;
        }
      }
    }

    // Draw a white sheet (with the Europass frame) for each page, and a grey
    // gap strip at each seam. seamY[i] is where page i's content ended.
    for (let i = 0; i < sheetTops.length; i++) {
      const frame = doc.createElement("div");
      frame.className = "page-frame" + (i === 0 ? " first" : "");
      frame.setAttribute("aria-hidden", "true");
      frame.style.top = `${sheetTops[i]}px`;
      body.appendChild(frame);
      if (i === 0) continue;
      // the gap covers the join: from the bottom edge of the previous sheet to
      // the top edge of this one
      const prevSheetBottom = sheetTops[i] - GAP_PX;
      const gap = doc.createElement("div");
      gap.className = "page-gap";
      gap.setAttribute("aria-hidden", "true");
      gap.style.top = `${prevSheetBottom}px`;
      gap.style.height = `${GAP_PX}px`;
      gap.innerHTML = `<span class="page-gap-label">Page ${i + 1}</span>`;
      body.appendChild(gap);
    }

    const lastTop = sheetTops[sheetTops.length - 1];
    els.page.style.height = `${Math.ceil(lastTop + sheetH)}px`;
  }

  function wirePage(doc) {
    const plainOnly = (() => {
      const probe = doc.createElement("span");
      try { probe.contentEditable = "plaintext-only"; return probe.contentEditable === "plaintext-only"; } catch { return false; }
    })();

    doc.querySelectorAll("[data-path]").forEach((el) => {
      const rich = el.dataset.rich === "1";
      el.contentEditable = (plainOnly && !rich) ? "plaintext-only" : "true";
      el.spellcheck = true;
    });

    // show the formatting toolbar while the caret is inside a text block
    doc.addEventListener("selectionchange", positionToolbar);
    doc.addEventListener("keyup", positionToolbar);
    doc.addEventListener("mouseup", positionToolbar);
    doc.addEventListener("scroll", hideToolbar, true);

    doc.querySelectorAll("[data-photo]").forEach((el) => {
      el.style.cursor = "pointer";
      el.title = "Click to change the photo";
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        select("personal");
        requestAnimationFrame(() => {
          const input = els.inspector.querySelector("#photoInput");
          if (input) input.click();
        });
      });
    });

    doc.addEventListener("click", (e) => {
      if (e.target.closest("a")) e.preventDefault();
      const block = e.target.closest("[data-select]");
      select(block ? block.dataset.select : null, { scroll: false });
    });

    doc.addEventListener("input", (e) => {
      const el = e.target.closest("[data-path]");
      if (!el) return;
      let value;
      if (el.dataset.rich === "1") {
        value = cleanRich(el.innerHTML);
      } else {
        value = el.textContent.replace(/\n/g, " ");
      }
      update(el.dataset.path, value, { render: false });
      positionToolbar();
    });

    doc.addEventListener("focusout", (e) => {
      const el = e.target.closest && e.target.closest("[data-path]");
      if (!el) return;
      const value = getPath(state.cv, el.dataset.path);
      if (typeof value === "string" && value !== value.trim()) setPath(state.cv, el.dataset.path, value.trim());
      closeTypingGroup();
      scheduleSave();
    });

    doc.addEventListener("paste", (e) => {
      const el = e.target.closest && e.target.closest("[data-path]");
      if (!el) return;
      e.preventDefault();
      let text = e.clipboardData.getData("text/plain");
      if (el.dataset.multiline !== "1") text = text.replace(/\s*\n\s*/g, " ");
      doc.execCommand("insertText", false, text);   // never paste foreign styling
    });

    doc.addEventListener("keydown", (e) => {
      if (handleShortcut(e)) return;
      const el = e.target.closest && e.target.closest("[data-path]");
      if (!el) return;
      const path = el.dataset.path;
      const bullet = path.match(/^(.*\.description)\.(\d+)$/);

      // Space-bar behaviours from Google Docs.
      if (e.key === " ") {
        // Shift+Space → non-breaking space, so words don't split across lines.
        if (e.shiftKey && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          const sel = doc.getSelection();
          if (sel && sel.rangeCount) {
            const r = sel.getRangeAt(0);
            r.deleteContents();
            r.insertNode(doc.createTextNode("\u00a0"));
            r.collapse(false);
            el.dispatchEvent(new Event("input", { bubbles: true }));
          }
          return;
        }
        // Ctrl+Space → clear character formatting on the selection.
        if ((e.ctrlKey || e.metaKey) && el.dataset.rich === "1") {
          e.preventDefault();
          try { doc.execCommand("removeFormat"); } catch {}
          return;
        }
        // "* " or "- " at the start of a description paragraph → convert the
        // paragraph into a bullet list (only in fields that support bullets).
        if (!e.shiftKey && !e.ctrlKey && !e.metaKey && path.endsWith(".description")) {
          const raw = el.textContent;
          if (/^[*\-]$/.test(raw.trim())) {
            e.preventDefault();
            const lines = raw.replace(/^[*\-]\s*/, "").split(/\n/).map((s) => s.trim()).filter(Boolean);
            commit((cv) => setPath(cv, path, lines.length ? lines : [""]));
            pendingFocus(`${path}.0`);
            return;
          }
        }
        // "1. " at the start of a bullet → same (numbered lists aren't a
        // Europass feature, so we treat them as bullets).
        if (!e.shiftKey && !e.ctrlKey && !e.metaKey && bullet && el.textContent.trim() === "1.") {
          e.preventDefault();
          el.textContent = "";
          update(path, "", { render: false });
          return;
        }
      }

      if (e.key === "Enter" && !e.shiftKey && bullet) {
        e.preventDefault(); // new bullet after this one
        const [, listPath, i] = bullet;
        const next = `${listPath}.${Number(i) + 1}`;
        commit((cv) => getPath(cv, listPath).splice(Number(i) + 1, 0, ""), { inspector: false });
        renderInspector();
        pendingFocus(next);
      } else if (e.key === "Backspace" && bullet && el.textContent === "") {
        const [, listPath, i] = bullet;
        const list = getPath(state.cv, listPath);
        if (list.length > 1) {
          e.preventDefault();
          commit((cv) => getPath(cv, listPath).splice(Number(i), 1), { inspector: false });
          renderInspector();
          pendingFocus(`${listPath}.${Math.max(0, Number(i) - 1)}`);
        }
      } else if (e.key === "Enter" && el.dataset.multiline !== "1") {
        e.preventDefault();
        el.blur();
      } else if (e.key === "Escape") {
        el.blur();
      }
    });
  }

  function pendingFocus(path) {
    clearTimeout(state.renderTimer);
    renderPage(path);
  }

  // ------------------------------------------------- formatting toolbar --

  /** Keep only the formatting the CV template allows. */
  function cleanRich(html) {
    const box = document.createElement("div");
    box.innerHTML = html;
    const keep = { B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, BR: 1 };
    const walk = (node) => {
      [...node.childNodes].forEach((child) => {
        if (child.nodeType === 1) {
          walk(child);
          if (!keep[child.tagName]) child.replaceWith(...child.childNodes);
          else [...child.attributes].forEach((a) => child.removeAttribute(a.name));
        }
      });
    };
    walk(box);
    return box.innerHTML.replace(/<div>/g, "<br>").replace(/<\/div>/g, "").trim();
  }

  const TOOLS = [
    { cmd: "bold", label: "B", title: "Bold (Ctrl+B)", style: "font-weight:700" },
    { cmd: "italic", label: "I", title: "Italic (Ctrl+I)", style: "font-style:italic" },
    { cmd: "underline", label: "U", title: "Underline (Ctrl+U)", style: "text-decoration:underline" },
    { sep: true },
    { align: "left", label: "⯇", title: "Align left" },
    { align: "center", label: "≡", title: "Centre" },
    { align: "right", label: "⯈", title: "Align right" },
    { align: "justify", label: "☰", title: "Justify" },
    { sep: true },
    { action: "bullets", label: "• List", title: "Switch between bullet points and a paragraph" },
    { action: "clear", label: "Clear", title: "Remove formatting" },
  ];

  let toolbarEl = null;
  let lastRange = null;       // the caret inside the page, kept while the toolbar is clicked

  function buildToolbar() {
    toolbarEl = document.createElement("div");
    toolbarEl.className = "format-bar";
    toolbarEl.hidden = true;
    toolbarEl.innerHTML = TOOLS.map((t) => t.sep
      ? '<span class="fb-sep"></span>'
      : `<button type="button" data-${t.cmd ? "cmd" : t.align ? "align" : "action"}="${t.cmd || t.align || t.action}" title="${esc(t.title)}"${t.style ? ` style="${t.style}"` : ""}>${t.label}</button>`
    ).join("");
    document.body.appendChild(toolbarEl);

    toolbarEl.addEventListener("mousedown", (e) => e.preventDefault());   // keep the caret
    toolbarEl.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const doc = els.page.contentDocument;
      const el = restoreCaret();
      if (!el) return;
      if (b.dataset.cmd) {
        doc.execCommand(b.dataset.cmd, false, null);
        update(el.dataset.path, cleanRich(el.innerHTML), { render: false });
      } else if (b.dataset.align) {
        const path = el.dataset.path;
        const current = (state.cv.design && state.cv.design.block_align || {})[path];
        commit((cv) => {
          cv.design.block_align = Object.assign({}, cv.design.block_align);
          if (current === b.dataset.align) delete cv.design.block_align[path];
          else cv.design.block_align[path] = b.dataset.align;
        }, { inspector: false });
      } else if (b.dataset.action === "clear") {
        const text = el.textContent;
        el.textContent = text;
        update(el.dataset.path, text, { render: false });
      } else if (b.dataset.action === "bullets") {
        const m = el.dataset.path.match(/^(.*\.description)(?:\.\d+)?$/);
        if (!m) { toast("Bullet points are only available in a job or course description."); return; }
        const listPath = m[1];
        commit((cv) => {
          const v = getPath(cv, listPath);
          if (Array.isArray(v)) setPath(cv, listPath, v.join("\n"));
          else setPath(cv, listPath, String(v || "").split(/<br\s*\/?>|\n/).map((x) => x.trim()).filter(Boolean));
        });
      }
      updateToolbarState();
    });
  }

  /** Put the caret back where it was, so a toolbar click still knows the target. */
  function restoreCaret() {
    const doc = els.page.contentDocument;
    if (!doc || !lastRange) return null;
    const el = lastRange.commonAncestorContainer.parentElement
      ? lastRange.commonAncestorContainer.parentElement.closest("[data-path]")
      : null;
    if (!el) return null;
    els.page.contentWindow.focus();     // execCommand only works on a focused document
    el.focus();
    const sel = doc.getSelection();
    sel.removeAllRanges();
    sel.addRange(lastRange);
    return el;
  }

  function currentBlock() {
    const doc = els.page.contentDocument;
    if (!doc) return null;
    const active = doc.activeElement && doc.activeElement.closest && doc.activeElement.closest("[data-path]");
    if (active) return active;
    if (!lastRange) return null;
    const node = lastRange.commonAncestorContainer;
    const parent = node.nodeType === 1 ? node : node.parentElement;
    return parent ? parent.closest("[data-path]") : null;
  }

  function updateToolbarState() {
    const doc = els.page.contentDocument;
    if (!doc || !toolbarEl) return;
    const el = currentBlock();
    const align = el ? (state.cv.design && state.cv.design.block_align || {})[el.dataset.path] : null;
    $$("button", toolbarEl).forEach((b) => {
      let on = false;
      if (b.dataset.cmd) { try { on = doc.queryCommandState(b.dataset.cmd); } catch { on = false; } }
      if (b.dataset.align) on = align === b.dataset.align;
      b.classList.toggle("is-on", on);
    });
    const rich = el && el.dataset.rich === "1";
    $$("button[data-cmd], button[data-action=clear]", toolbarEl).forEach((b) => { b.disabled = !rich; });
  }

  function hideToolbar() { if (toolbarEl) toolbarEl.hidden = true; }

  function positionToolbar() {
    if (!toolbarEl) return;      // toolbar disabled, nothing to position
    const doc = els.page.contentDocument;
    const el = currentBlock();
    if (!el) { hideToolbar(); return; }
    const sel = doc.getSelection();
    if (sel && sel.rangeCount && el.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      lastRange = sel.getRangeAt(0).cloneRange();
    }
    const frame = els.page.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const scale = frame.width / els.page.offsetWidth;
    toolbarEl.hidden = false;
    const width = toolbarEl.offsetWidth || 320;
    let left = frame.left + (box.left + box.width / 2) * scale - width / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
    let topY = frame.top + box.top * scale - toolbarEl.offsetHeight - 8;
    if (topY < 64) topY = frame.top + (box.bottom) * scale + 8;
    toolbarEl.style.left = `${Math.round(left)}px`;
    toolbarEl.style.top = `${Math.round(topY)}px`;
    updateToolbarState();
  }

  function highlightSelection(scroll) {
    const doc = els.page.contentDocument;
    if (!doc || !doc.body) return;
    doc.querySelectorAll(".is-selected").forEach((n) => n.classList.remove("is-selected"));
    if (!state.selected) return;
    const target = doc.querySelector(`[data-select="${CSS.escape(state.selected)}"]`);
    if (target) {
      target.classList.add("is-selected");
      if (scroll) {
        const top = target.getBoundingClientRect().top * state.zoom + els.page.getBoundingClientRect().top;
        const canvasTop = els.canvas.getBoundingClientRect().top;
        els.canvas.scrollBy({ top: top - canvasTop - 80, behavior: "smooth" });
      }
    }
  }

  function select(key, { scroll = true } = {}) {
    state.selected = key;
    highlightSelection(scroll);
    renderSections();
    renderInspector();
    els.inspector.classList.toggle("is-open", !!key);
  }

  // ------------------------------------------------------- left: sections --

  const ICONS = {
    plus: '<svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg>',
    eye: '<svg viewBox="0 0 20 20"><path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z"/><circle cx="10" cy="10" r="2.3"/></svg>',
    eyeOff: '<svg viewBox="0 0 20 20"><path d="M3 3l14 14M8.2 5a8 8 0 0 1 1.8-.2c5 0 8 5.2 8 5.2a14 14 0 0 1-2.2 2.8M5.3 6.4A13.6 13.6 0 0 0 2 10s3 5.5 8 5.5a7.4 7.4 0 0 0 3.2-.7"/></svg>',
    trash: '<svg viewBox="0 0 20 20"><path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10"/></svg>',
  };

  function renderSections() {
    const hidden = new Set(design().hidden_sections || []);
    $("#personalRow").classList.toggle("is-current", state.selected === "personal");

    els.sectionList.innerHTML = sectionOrder().map((key) => {
      const isHidden = hidden.has(key);
      const canAdd = key === "work_experience" || key === "education"
        || TYPED_SECTIONS[key] || key.startsWith("custom:");
      const current = state.selected && (state.selected === sectionSelectKey(key) || isInside(state.selected, key));
      return `
        <li draggable="true" data-key="${esc(key)}">
          <div class="row-item${isHidden ? " is-hidden" : ""}${current ? " is-current" : ""}" data-open="${esc(key)}" role="button" tabindex="0">
            <span class="handle" title="Drag to reorder" aria-hidden="true"></span>
            <span class="row-title">${esc(sectionLabel(key))}</span>
            <span class="row-actions">
              ${canAdd ? `<button class="mini" data-add="${esc(key)}" title="Add an entry" aria-label="Add an entry to ${esc(sectionLabel(key))}">${ICONS.plus}</button>` : ""}
              <button class="mini" data-toggle="${esc(key)}" title="${isHidden ? "Show on CV" : "Hide from CV"}" aria-label="${isHidden ? "Show" : "Hide"} ${esc(sectionLabel(key))}">${isHidden ? ICONS.eyeOff : ICONS.eye}</button>
            </span>
          </div>
        </li>`;
    }).join("");
  }

  function isInside(selected, key) {
    if (key === "work_experience" || key === "education" || TYPED_SECTIONS[key]) return selected.startsWith(`${key}.`);
    if (key.startsWith("custom:")) {
      const i = customSections().findIndex((s) => `custom:${s.id}` === key);
      return selected === key || selected.startsWith(`additional_sections.${i}.`);
    }
    return false;
  }

  function addEntry(key) {
    if (key === "work_experience") {
      const n = (state.cv.work_experience || []).length;
      commit((cv) => {
        (cv.work_experience ||= []).push({ title: "New job title", employer: "Employer name", city: "", country: "", start: thisMonth(), end: null, description: ["Main responsibility or achievement"] });
      }, { select: `work_experience.${n}` });
    } else if (key === "education") {
      const n = (state.cv.education || []).length;
      commit((cv) => {
        (cv.education ||= []).push({ title: "Qualification name", organisation: "School or university", city: "", country: "", start: thisMonth(), end: null });
      }, { select: `education.${n}` });
    } else if (TYPED_SECTIONS[key]) {
      const n = (state.cv[key] || []).length;
      commit((cv) => { (cv[key] ||= []).push({ ...TYPED_SECTIONS[key].blank }); },
        { select: `${key}.${n}` });
    } else if (key.startsWith("custom:")) {
      const i = customSections().findIndex((s) => `custom:${s.id}` === key);
      const n = (customSections()[i].items || []).length;
      commit((cv) => { (cv.additional_sections[i].items ||= []).push({ heading: "New item", text: "Describe it here." }); },
        { select: `additional_sections.${i}.items.${n}` });
    }
    focusFirstField();
  }

  function focusFirstField() {
    requestAnimationFrame(() => {
      const input = els.inspector.querySelector("input[type=text], textarea");
      if (input) { input.focus(); input.select(); }
    });
  }

  function toggleSection(key) {
    commit((cv) => {
      const d = cv.design;
      const set = new Set(d.hidden_sections || []);
      set.has(key) ? set.delete(key) : set.add(key);
      d.hidden_sections = [...set];
    });
  }

  function addCustomSection() {
    const id = `s${Date.now().toString(36)}`;
    commit((cv) => {
      (cv.additional_sections ||= []).push({ id, title: "New section", items: [{ heading: "New item", text: "Describe it here." }] });
      cv.design.section_order = sectionOrder(); // appends the new section at the end
    }, { select: `custom:${id}` });
    focusFirstField();
  }

  function wireSectionList() {
    const list = els.sectionList;

    list.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add]");
      const toggle = e.target.closest("[data-toggle]");
      const open = e.target.closest("[data-open]");
      if (add) { e.stopPropagation(); addEntry(add.dataset.add); }
      else if (toggle) { e.stopPropagation(); toggleSection(toggle.dataset.toggle); }
      else if (open) select(sectionSelectKey(open.dataset.open));
    });

    list.addEventListener("keydown", (e) => {
      const open = e.target.closest("[data-open]");
      if (open && (e.key === "Enter" || e.key === " ") && e.target === open) {
        e.preventDefault();
        select(sectionSelectKey(open.dataset.open));
      }
    });

    let dragKey = null;
    list.addEventListener("dragstart", (e) => {
      const li = e.target.closest("li");
      dragKey = li.dataset.key;
      li.classList.add("is-dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", dragKey);
    });
    list.addEventListener("dragover", (e) => {
      const li = e.target.closest("li");
      if (!li || !dragKey) return;
      e.preventDefault();
      $$("li", list).forEach((n) => n.classList.remove("drop-before", "drop-after"));
      const r = li.getBoundingClientRect();
      li.classList.add(e.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
    });
    list.addEventListener("dragleave", (e) => {
      if (!list.contains(e.relatedTarget)) $$("li", list).forEach((n) => n.classList.remove("drop-before", "drop-after"));
    });
    list.addEventListener("drop", (e) => {
      e.preventDefault();
      const li = e.target.closest("li");
      if (!li || !dragKey || li.dataset.key === dragKey) { renderSections(); return; }
      const after = li.classList.contains("drop-after");
      const order = sectionOrder().filter((k) => k !== dragKey);
      order.splice(order.indexOf(li.dataset.key) + (after ? 1 : 0), 0, dragKey);
      commit((cv) => { cv.design.section_order = order; });
    });
    list.addEventListener("dragend", () => { dragKey = null; renderSections(); });
  }

  // ---------------------------------------------------------- left: design --

  function renderDesign() {
    const d = design();
    const font = $("#dFont");
    if (!font.options.length) {
      font.innerHTML = Object.entries(state.meta.fonts).map(([k, label]) => `<option value="${esc(k)}">${esc(label)}</option>`).join("");
    }
    font.value = d.font;
    const tpl = $("#dTemplate");
    if (tpl) tpl.value = d.template || "template1";

    $("#dSwatches").innerHTML = SWATCHES.map(([hex, name]) =>
      `<button class="swatch${d.accent.toLowerCase() === hex ? " is-active" : ""}" style="background:${hex}" data-color="${hex}" title="${name}" aria-label="${name}"></button>`
    ).join("") + `<input type="color" id="dAccentCustom" value="${esc(d.accent)}" title="Custom colour" aria-label="Custom accent colour">`;

    $("#dText").value = d.text;
    $("#dScale").value = d.scale;
    $("#dScaleOut").textContent = `${Math.round(d.scale * 100)}%`;
    $("#dMargin").value = d.margin_mm;
    $("#dMarginOut").textContent = `${d.margin_mm} mm`;
    $$("#dPhoto button").forEach((b) => b.classList.toggle("is-active", b.dataset.v === d.photo_shape));
    $("#dPages").checked = !!d.page_numbers;
    $("#dLine").value = d.line_height;
    $("#dLineOut").textContent = Number(d.line_height).toFixed(2);
    $("#dSection").value = d.section_gap;
    $("#dSectionOut").textContent = `${d.section_gap} mm`;
    $("#dEntry").value = d.entry_gap;
    $("#dEntryOut").textContent = `${d.entry_gap} mm`;
    $$("#dLangLayout button").forEach((b) => b.classList.toggle("is-active", b.dataset.v === d.languages_layout));
    $("#dFrame").checked = d.frame !== false;
  }

  function wireDesign() {
    const setDesign = (key, value, typing = false) => {
      if (typing) update(`design.${key}`, value);
      else commit((cv) => { cv.design[key] = value; });
    };
    $("#dFont").addEventListener("change", (e) => setDesign("font", e.target.value));
    $("#dTemplate")?.addEventListener("change", (e) => {
      // Each template has its own page margin, so clear the override and let
      // the template decide unless the person has moved the slider since.
      commit((cv) => { cv.design.template = e.target.value; cv.design.margin_mm = null; });
    });
    $("#dSwatches").addEventListener("click", (e) => {
      const sw = e.target.closest("[data-color]");
      if (sw) setDesign("accent", sw.dataset.color);
    });
    $("#dSwatches").addEventListener("input", (e) => {
      if (e.target.id === "dAccentCustom") { update("design.accent", e.target.value); }
    });
    $("#dSwatches").addEventListener("change", (e) => { if (e.target.id === "dAccentCustom") renderDesign(); });
    $("#dText").addEventListener("input", (e) => update("design.text", e.target.value));
    $("#dScale").addEventListener("input", (e) => {
      update("design.scale", Number(e.target.value));
      $("#dScaleOut").textContent = `${Math.round(e.target.value * 100)}%`;
    });
    $("#dMargin").addEventListener("input", (e) => {
      update("design.margin_mm", Number(e.target.value));
      $("#dMarginOut").textContent = `${e.target.value} mm`;
    });
    $("#dPhoto").addEventListener("click", (e) => {
      const b = e.target.closest("[data-v]");
      if (b) setDesign("photo_shape", b.dataset.v);
    });
    $("#dPages").addEventListener("change", (e) => setDesign("page_numbers", e.target.checked));
    const slider = (id, key, out, fmt) => $(id).addEventListener("input", (e) => {
      update(`design.${key}`, Number(e.target.value));
      $(out).textContent = fmt(e.target.value);
    });
    slider("#dLine", "line_height", "#dLineOut", (v) => Number(v).toFixed(2));
    slider("#dSection", "section_gap", "#dSectionOut", (v) => `${v} mm`);
    slider("#dEntry", "entry_gap", "#dEntryOut", (v) => `${v} mm`);
    $("#dLangLayout").addEventListener("click", (e) => {
      const b = e.target.closest("[data-v]");
      if (b) setDesign("languages_layout", b.dataset.v);
    });
    $("#dFrame").addEventListener("change", (e) => setDesign("frame", e.target.checked));
    $("#dReset").addEventListener("click", () => commit((cv) => {
      const keep = { section_order: cv.design.section_order, hidden_sections: cv.design.hidden_sections };
      cv.design = Object.assign(clone(state.meta.design), keep);
    }));
  }

  // ------------------------------------------------------ right: inspector --

  /* Small declarative form builder. Every control carries data-bind=<path>
     and writes straight into the CV as the user types. */
  function input(label, path, { type = "text", placeholder = "", help = "" } = {}) {
    const value = getPath(state.cv, path) ?? "";
    return `<label class="field"><span>${esc(label)}</span>
      <input type="${type}" data-bind="${esc(path)}" value="${esc(type === "month" ? toMonth(value) : value)}" placeholder="${esc(placeholder)}"></label>
      ${help ? `<p class="help">${esc(help)}</p>` : ""}`;
  }

  function textarea(label, path, { rows = 5, placeholder = "", list = false } = {}) {
    let value = getPath(state.cv, path) ?? "";
    if (list && Array.isArray(value)) value = value.join("\n");
    return `<label class="field"><span>${esc(label)}</span>
      <textarea rows="${rows}" data-bind="${esc(path)}"${list ? ' data-list="1"' : ""} placeholder="${esc(placeholder)}">${esc(value)}</textarea></label>`;
  }

  /**
   * A list the person can grow: "Another email", "Another website"...
   * Europass allows several of each, so one box per value plus an Add button.
   */
  function extraRows(path, label, type, placeholder) {
    const values = getPath(state.cv, path) || [];
    const rows = values.map((v, i) => `
      <div class="repeat-row">
        <input type="${type}" value="${esc(v)}" placeholder="${esc(placeholder)}"
               data-list-path="${path}" data-list-index="${i}">
        <button class="btn small btn-danger" data-list-remove="${path}" data-i="${i}"
                title="Remove">&times;</button>
      </div>`).join("");
    return `<div class="repeat-group">${rows}
      <button class="btn small" data-list-add="${path}">+ ${esc(label)}</button></div>`;
  }

  const SOCIAL_TYPES = ["LinkedIn", "Facebook", "X", "Instagram", "YouTube",
                        "Pinterest", "Tumblr", "Other"];
  const IM_TYPES = ["Skype", "WhatsApp Messenger", "WeChat", "Line", "Viber", "Other"];

  function socialRows() {
    const list = getPath(state.cv, "personal.social_media") || [];
    const rows = list.map((s, i) => `
      <div class="repeat-row">
        <select data-social="type" data-i="${i}">
          ${SOCIAL_TYPES.map((t) => `<option${s.type === t ? " selected" : ""}>${t}</option>`).join("")}
        </select>
        <input value="${esc(s.url || "")}" placeholder="username or full link"
               data-social="url" data-i="${i}">
        <button class="btn small btn-danger" data-list-remove="personal.social_media"
                data-i="${i}" title="Remove">&times;</button>
      </div>`).join("");
    return `<div class="subhead-small">Social media</div><div class="repeat-group">${rows}
      <button class="btn small" data-list-add="personal.social_media">+ Add social media</button></div>`;
  }

  function imRows() {
    const list = getPath(state.cv, "personal.instant_messaging") || [];
    const rows = list.map((s, i) => `
      <div class="repeat-row">
        <select data-im="type" data-i="${i}">
          ${IM_TYPES.map((t) => `<option${s.type === t ? " selected" : ""}>${t}</option>`).join("")}
        </select>
        <input value="${esc(s.value || "")}" placeholder="handle or number"
               data-im="value" data-i="${i}">
        <button class="btn small btn-danger" data-list-remove="personal.instant_messaging"
                data-i="${i}" title="Remove">&times;</button>
      </div>`).join("");
    return `<div class="subhead-small">Instant messaging</div><div class="repeat-group">${rows}
      <button class="btn small" data-list-add="personal.instant_messaging">+ Add instant messaging</button></div>`;
  }

  function selectBox(label, path, options) {
    const value = getPath(state.cv, path) ?? "";
    return `<label class="field"><span>${esc(label)}</span><select data-bind="${esc(path)}">
      ${options.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(l)}</option>`).join("")}
      </select></label>`;
  }

  function head(title, kind) {
    return `<div class="inspector-head"><h2>${esc(title)}</h2>${kind ? `<span class="kind">${esc(kind)}</span>` : ""}</div>`;
  }

  function entryActions(listPath, index, length) {
    return `<div class="entry-actions">
      <button class="btn" data-act="up" ${index === 0 ? "disabled" : ""}>Up</button>
      <button class="btn" data-act="down" ${index === length - 1 ? "disabled" : ""}>Down</button>
      <button class="btn" data-act="dup">Duplicate</button>
      <button class="btn btn-danger" data-act="del">Delete</button>
    </div>`.replace(/data-act="(\w+)"/g, `data-act="$1" data-list="${esc(listPath)}" data-index="${index}"`);
  }

  function datesBlock(base) {
    const item = getPath(state.cv, base) || {};
    const current = !item.end;
    return `<div class="field-row">
        ${input("Start", `${base}.start`, { type: "month" })}
        ${current ? `<label class="field"><span>End</span><input type="text" value="Current" disabled></label>` : input("End", `${base}.end`, { type: "month" })}
      </div>
      <label class="check"><input type="checkbox" data-current="${esc(base)}"${current ? " checked" : ""}> Ongoing (shows “Current”)</label>`;
  }

  const INSPECTORS = [
    [/^personal$/, () => {
      const p = state.cv.personal || (state.cv.personal = {});
      const nat = (p.nationalities || []).map((n) => n.name).join(", ");
      return head("Personal details") + `
        <div class="photo-box">
          ${p.photo ? `<img src="${esc(p.photo)}" alt="Photo">` : `<div class="ph">No photo</div>`}
          <div class="btns">
            <button class="btn small" data-photo="pick">${p.photo ? "Change photo" : "Add photo"}</button>
            ${p.photo ? `<button class="btn small" data-photo="adjust">Adjust</button>` : ""}
            ${p.photo ? `<button class="btn small btn-danger" data-photo="remove">Remove</button>` : ""}
          </div>
          <input type="file" accept="image/*" id="photoInput" hidden>
        </div>
        <div class="field-row">${input("First name", "personal.first_name")}${input("Last name", "personal.last_name")}</div>
        <div class="field-row">
          ${input("Date of birth", "personal.date_of_birth", { type: "date" })}
          ${selectBox("Gender", "personal.gender", [["", "Not shown"], ["Male", "Male"], ["Female", "Female"], ["Other", "Other"]])}
        </div>
        <label class="field"><span>Nationality</span><input type="text" data-nationality value="${esc(nat)}" placeholder="e.g. Indian, Italian"></label>
        <p class="help">Separate several nationalities with commas.</p>
        <div class="field-row">
          ${selectBox("Document", "personal.document_type", [["Passport", "Passport"], ["ID", "ID card"], ["Residence permit", "Residence permit"]])}
          ${input("Passport / ID number", "personal.passport")}
        </div>
        <div class="field-row">
          ${input("Place of birth - city", "personal.place_of_birth.city")}
          ${input("Place of birth - country", "personal.place_of_birth.country")}
        </div>
        <div class="subhead">Contact</div>
        <div class="field-row-3">
          ${input("Code", "personal.phone.country_dialing", { placeholder: "91" })}
          ${input("Number", "personal.phone.number", { type: "tel" })}
          ${selectBox("Type", "personal.phone.type", [["Mobile", "Mobile"], ["Home", "Home"], ["Work", "Work"], ["", "—"]])}
        </div>
        ${extraRows("personal.extra_phones", "Another phone", "tel", "+39 320 000 0000")}
        ${input("Email address", "personal.email", { type: "email" })}
        ${extraRows("personal.extra_emails", "Another email", "email", "name@example.com")}
        ${input("Website", "personal.website", { type: "url", placeholder: "https://" })}
        ${extraRows("personal.extra_websites", "Another website", "url", "https://")}
        ${socialRows()}
        ${imRows()}
        <div class="subhead">Address</div>
        ${input("Address line 1", "personal.address.street")}
        ${input("Address line 2", "personal.address.street2", { placeholder: "Apartment, suite, floor" })}
        <div class="field-row">${input("Postal code", "personal.address.postal_code")}${input("City", "personal.address.city")}</div>
        <div class="field-row">
          ${input("Country", "personal.address.country")}
          ${selectBox("Type", "personal.address.type", [["Home", "Home"], ["Work", "Work"], ["", "—"]])}
        </div>`;
    }],

    [/^section:about$/, () => head("About me", "Section") +
      textarea("Summary", "about", { rows: 8, placeholder: "Two or three sentences about who you are and what you are looking for." })],

    [/^section:(work_experience|education)$/, (m) => {
      const key = m[1];
      const items = state.cv[key] || [];
      const label = state.meta.sections[key];
      return head(label, `${items.length} ${items.length === 1 ? "entry" : "entries"}`) +
        `<p class="empty-state">Click an entry on the page to edit it, or add a new one.</p>
         <button class="btn full" data-add-entry="${key}">Add ${key === "education" ? "education" : "work experience"}</button>`;
    }],

    [/^work_experience\.(\d+)$/, (m) => {
      const i = Number(m[1]);
      const base = `work_experience.${i}`;
      const desc = getPath(state.cv, `${base}.description`);
      return head("Work experience", `${i + 1} of ${state.cv.work_experience.length}`) +
        entryActions("work_experience", i, state.cv.work_experience.length) +
        input("Job title", `${base}.title`) +
        input("Employer", `${base}.employer`) +
        `<div class="field-row">${input("City", `${base}.city`)}${input("Country", `${base}.country`)}</div>` +
        datesBlock(base) +
        textarea("Description", `${base}.description`, { rows: 6, list: Array.isArray(desc) }) +
        `<label class="check"><input type="checkbox" data-bullets="${base}.description"${Array.isArray(desc) ? " checked" : ""}> Show as bullet points (one per line)</label>`;
    }],

    [/^education\.(\d+)$/, (m) => {
      const i = Number(m[1]);
      const base = `education.${i}`;
      return head("Education and training", `${i + 1} of ${state.cv.education.length}`) +
        entryActions("education", i, state.cv.education.length) +
        input("Qualification", `${base}.title`) +
        input("Organisation", `${base}.organisation`) +
        `<div class="field-row">${input("City", `${base}.city`)}${input("Country", `${base}.country`)}</div>` +
        datesBlock(base) +
        input("Field(s) of study", `${base}.field`) +
        `<div class="field-row">${input("Final grade", `${base}.final_grade`)}
          ${selectBox("Level in EQF", `${base}.eqf_level`, [["", "Not shown"], ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => [n, `EQF level ${n}`])])}</div>` +
        input("Thesis", `${base}.thesis`) +
        textarea("Other details", `${base}.description`, { rows: 3 });
    }],

    [/^languages$/, () => {
      const langs = state.cv.languages || (state.cv.languages = { mother_tongues: [], other: [] });
      const mother = (langs.mother_tongues || []).map((l) => l.name).join(", ");
      const cards = (langs.other || []).map((l, i) => `
        <div class="lang-card">
          <div class="lang-top">
            <input type="text" data-bind="languages.other.${i}.name" value="${esc(l.name)}" aria-label="Language name">
            <button class="mini" data-remove-lang="${i}" title="Remove" aria-label="Remove ${esc(l.name)}">${ICONS.trash}</button>
          </div>
          <div class="lang-grid">
            ${LEVEL_KEYS.map(([k, short]) => `<label>${short}<select data-bind="languages.other.${i}.${k}">
              ${LEVELS.map((v) => `<option${(l[k] || "") === v ? " selected" : ""}>${v}</option>`).join("")}</select></label>`).join("")}
          </div>
        </div>`).join("");
      return head("Language skills", "Section") + `
        <label class="field"><span>Mother tongue(s)</span><input type="text" data-mother value="${esc(mother)}" placeholder="e.g. Hindi"></label>
        <p class="help">Separate several languages with commas.</p>
        <div class="subhead">Other languages</div>
        ${cards || '<p class="help">None added yet.</p>'}
        <button class="btn full" data-add-lang>Add a language</button>`;
    }],

    [/^digital_skills$/, () => head("Digital skills", "Section") +
      textarea("Skills", "digital_skills", { rows: 8, list: true, placeholder: "One skill per line" }) +
      `<p class="help">One skill per line.</p>`],

    [/^driving_licence$/, () => {
      const have = new Set(state.cv.driving_licence || []);
      return head("Driving licence", "Section") + `<div class="chips">${LICENCES.map((c) =>
        `<label class="chip"><input type="checkbox" data-licence="${c}"${have.has(c) ? " checked" : ""}><span>${c}</span></label>`).join("")}</div>`;
    }],

    // One section panel and one entry panel cover all eleven typed sections.
    [new RegExp(`^(${TYPED_KEYS.join("|")})$`), (m) => {
      const key = m[1], spec = TYPED_SECTIONS[key];
      const n = (state.cv[key] || []).length;
      return head(spec.label, `${n} ${n === 1 ? "entry" : "entries"}`) +
        `<button class="btn full" data-add-entry="${key}">Add an entry</button>` +
        (n ? "" : `<p class="help">Nothing here yet. An empty section is left off the CV.</p>`);
    }],

    [new RegExp(`^(${TYPED_KEYS.join("|")})\\.(\\d+)$`), (m) => {
      const key = m[1], i = Number(m[2]), spec = TYPED_SECTIONS[key];
      const list = state.cv[key] || [];
      if (!list[i]) return null;
      const base = `${key}.${i}`;
      const fields = spec.fields.map((f) => {
        const label = FIELD_LABELS[f] || f;
        if (f === "description") return textarea(label, `${base}.description`, { rows: 5, list: true });
        if (f === "start" || f === "end") return input(label, `${base}.${f}`, { type: "month" });
        return input(label, `${base}.${f}`);
      }).join("");
      return head(spec.label, `${i + 1} of ${list.length}`) +
        entryActions(key, i, list.length) + fields;
    }],

    [/^custom:(.+)$/, (m) => {
      const i = customSections().findIndex((s) => s.id === m[1]);
      if (i < 0) return null;
      const sec = customSections()[i];
      return head("Custom section", `${(sec.items || []).length} items`) +
        input("Section title", `additional_sections.${i}.title`) +
        `<button class="btn full" data-add-entry="custom:${esc(sec.id)}">Add an item</button>
         <button class="btn full btn-danger" data-del-section="${i}">Delete this section</button>`;
    }],

    [/^additional_sections\.(\d+)\.items\.(\d+)$/, (m) => {
      const [si, ii] = [Number(m[1]), Number(m[2])];
      const sec = customSections()[si];
      if (!sec) return null;
      const base = `additional_sections.${si}.items.${ii}`;
      return head(sec.title || "Custom section", `${ii + 1} of ${sec.items.length}`) +
        entryActions(`additional_sections.${si}.items`, ii, sec.items.length) +
        input("Heading", `${base}.heading`) +
        textarea("Text", `${base}.text`, { rows: 6 });
    }],
  ];

  function renderInspector() {
    const key = state.selected;
    let html = null;
    if (key) {
      for (const [re, fn] of INSPECTORS) {
        const m = key.match(re);
        if (m) { html = fn(m); break; }
      }
    }
    const close = key ? `<button class="btn small drawer-close" data-close-inspector>Close</button>` : "";
    els.inspector.innerHTML = close + (html || `
      <div class="empty-state">
        <strong>Nothing selected</strong>
        Click any text on the page to change it directly. Click a block, such as a job or the language table,
        to see all of its details here.
      </div>`);
  }

  function syncInspectorValues() {
    $$("[data-bind]", els.inspector).forEach((el) => {
      if (el === document.activeElement) return;
      let v = getPath(state.cv, el.dataset.bind) ?? "";
      if (el.dataset.list && Array.isArray(v)) v = v.join("\n");
      if (el.type === "month") v = toMonth(v);
      if (el.value !== String(v)) el.value = v;
    });
  }

  function wireInspector() {
    const box = els.inspector;

    box.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.listPath) {                       // extra phone / email / website
        const path = t.dataset.listPath, i = Number(t.dataset.listIndex);
        commit((cv) => {
          const list = (getPath(cv, path) || []).slice();
          list[i] = t.value;
          setPath(cv, path, list);
        }, { inspector: false });
        return;
      }
      if (t.dataset.social || t.dataset.im) {          // social media / messaging
        const path = t.dataset.social ? "personal.social_media" : "personal.instant_messaging";
        const key = t.dataset.social || t.dataset.im;
        const i = Number(t.dataset.i);
        commit((cv) => {
          const list = (getPath(cv, path) || []).map((x) => ({ ...x }));
          if (!list[i]) list[i] = {};
          list[i][key] = t.value;
          setPath(cv, path, list);
        }, { inspector: false });
        return;
      }
      if (t.dataset.bind) {
        let value = t.value;
        if (t.dataset.list) value = value.split("\n").map((s) => s.trim()).filter((s, i, arr) => s || i < arr.length - 1);
        if (t.tagName === "SELECT" && /eqf_level$/.test(t.dataset.bind)) value = value ? Number(value) : null;
        if (t.dataset.list && /digital_skills$/.test(t.dataset.bind)) value = value.filter(Boolean);
        update(t.dataset.bind, value);
      } else if ("nationality" in t.dataset) {
        update("personal.nationalities", t.value.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name })));
      } else if ("mother" in t.dataset) {
        update("languages.mother_tongues", t.value.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name })));
      }
    });

    box.addEventListener("change", (e) => {
      const t = e.target;
      if (t.tagName === "SELECT" && t.dataset.bind) closeTypingGroup();
      if (t.dataset.current) {
        const base = t.dataset.current;
        commit((cv) => {
          const item = getPath(cv, base);
          item.end = t.checked ? null : (toMonth(item.start) || thisMonth());
        });
      } else if (t.dataset.bullets) {
        const path = t.dataset.bullets;
        commit((cv) => {
          const v = getPath(cv, path);
          if (t.checked) setPath(cv, path, String(v || "").split("\n").map((s) => s.trim()).filter(Boolean));
          else setPath(cv, path, (Array.isArray(v) ? v : []).join("\n"));
        });
      } else if (t.dataset.licence) {
        const codes = $$("[data-licence]", box).filter((c) => c.checked).map((c) => c.dataset.licence);
        commit((cv) => { cv.driving_licence = codes; }, { inspector: false });
      } else if (t.id === "photoInput" && t.files[0]) {
        loadPhoto(t.files[0]);
      }
    });

    box.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if ("closeInspector" in b.dataset) {
        select(null);
      } else if (b.dataset.act) {
        entryAction(b.dataset.act, b.dataset.list, Number(b.dataset.index));
      } else if (b.dataset.addEntry) {
        addEntry(b.dataset.addEntry);
      } else if ("addLang" in b.dataset) {
        commit((cv) => {
          cv.languages ||= { mother_tongues: [], other: [] };
          (cv.languages.other ||= []).push({ name: "New language", listening: "B1", reading: "B1", spoken_production: "B1", spoken_interaction: "B1", writing: "B1" });
        });
        const inputs = $$(".lang-card input[type=text]", box);
        if (inputs.length) { inputs[inputs.length - 1].focus(); inputs[inputs.length - 1].select(); }
      } else if (b.dataset.removeLang !== undefined) {
        commit((cv) => cv.languages.other.splice(Number(b.dataset.removeLang), 1));
      } else if (b.dataset.delSection !== undefined) {
        const i = Number(b.dataset.delSection);
        const sec = customSections()[i];
        if (!confirm(`Delete the section “${sec.title || "Untitled"}” and all its items?`)) return;
        commit((cv) => {
          cv.additional_sections.splice(i, 1);
          cv.design.section_order = (cv.design.section_order || []).filter((k) => k !== `custom:${sec.id}`);
        }, { select: null });
        toast("Section deleted. Press Ctrl+Z to undo.");
      } else if (b.dataset.photo === "pick") {
        $("#photoInput", box).click();
      } else if (b.dataset.listAdd) {
        const path = b.dataset.listAdd;
        const blank = path.endsWith("social_media") ? { type: "LinkedIn", url: "" }
                    : path.endsWith("instant_messaging") ? { type: "WhatsApp Messenger", value: "" }
                    : "";
        commit((cv) => setPath(cv, path, [...(getPath(cv, path) || []), blank]));
      } else if (b.dataset.listRemove) {
        const path = b.dataset.listRemove, i = Number(b.dataset.i);
        commit((cv) => setPath(cv, path, (getPath(cv, path) || []).filter((_, n) => n !== i)));
      } else if (b.dataset.photo === "adjust") {
        editExistingPhoto();
      } else if (b.dataset.photo === "remove") {
        commit((cv) => { cv.personal.photo = null; });
      }
    });
  }

  function entryAction(act, listPath, i) {
    const list = getPath(state.cv, listPath);
    const base = listPath;
    if (act === "up" && i > 0) {
      commit((cv) => { const l = getPath(cv, base); [l[i - 1], l[i]] = [l[i], l[i - 1]]; }, { select: `${base}.${i - 1}` });
    } else if (act === "down" && i < list.length - 1) {
      commit((cv) => { const l = getPath(cv, base); [l[i + 1], l[i]] = [l[i], l[i + 1]]; }, { select: `${base}.${i + 1}` });
    } else if (act === "dup") {
      commit((cv) => { const l = getPath(cv, base); l.splice(i + 1, 0, clone(l[i])); }, { select: `${base}.${i + 1}` });
    } else if (act === "del") {
      const parentSection = base.startsWith("additional_sections")
        ? `custom:${customSections()[Number(base.split(".")[1])].id}`
        : `section:${base}`;
      commit((cv) => getPath(cv, base).splice(i, 1), { select: parentSection });
      toast("Entry deleted. Press Ctrl+Z to undo.");
    }
  }

  function loadPhoto(file) {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => openPhotoEditor(img);
      img.onerror = () => toast("That image could not be read. Try a JPG or PNG file.", true);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  /**
   * Crop, zoom and reposition a photo before it goes on the CV.
   *
   * Students send holiday snaps and group photos; the CV needs a head-and-
   * shoulders portrait. The dialog shows the picture behind a round window
   * (the shape the CV uses) which the person drags and zooms to frame the face.
   */
  function openPhotoEditor(img, existing) {
    const OUT = 600;                        // saved at 600x600, plenty for print
    const BOX = 320;                        // on-screen size of the crop window
    let zoom = 1, minZoom = 1, x = 0, y = 0, angle = 0;   // angle in degrees

    const dlg = document.createElement("dialog");
    dlg.className = "photo-dialog";
    dlg.innerHTML = `
      <h2>Adjust the photo</h2>
      <p class="photo-hint">Drag the picture to move it, and use the slider to zoom.
        The circle shows what appears on the CV.</p>
      <div class="photo-stage" style="width:${BOX}px;height:${BOX}px">
        <canvas width="${BOX}" height="${BOX}"></canvas>
        <div class="photo-mask" aria-hidden="true"></div>
      </div>
      <label class="field photo-zoom"><span>Zoom</span>
        <input type="range" id="photoZoom" min="1" max="4" step="0.01" value="1"></label>
      <div class="photo-rotate">
        <span>Rotate</span>
        <button class="btn small" data-photo-rot="-90" type="button" title="Turn left">⟲ Left</button>
        <button class="btn small" data-photo-rot="90" type="button" title="Turn right">⟳ Right</button>
        <button class="btn small" data-photo-rot="-1" type="button" title="Nudge left">−1°</button>
        <button class="btn small" data-photo-rot="1" type="button" title="Nudge right">+1°</button>
      </div>
      <div class="photo-actions">
        <button class="btn" data-photo-cancel type="button">Cancel</button>
        <button class="btn" data-photo-reset type="button">Reset</button>
        <button class="btn btn-primary" data-photo-save type="button">Use this photo</button>
      </div>`;
    document.body.appendChild(dlg);

    const canvas = dlg.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    const zoomInput = dlg.querySelector("#photoZoom");

    /** Width and height of the picture once turned by `angle`. */
    const turned = () => {
      const quarter = Math.abs(angle % 180) === 90;
      return quarter ? { w: img.height, h: img.width } : { w: img.width, h: img.height };
    };

    const reset = () => {
      angle = 0;
      minZoom = Math.max(BOX / img.width, BOX / img.height);
      zoom = minZoom;
      zoomInput.min = String(minZoom);
      zoomInput.max = String(minZoom * 4);
      zoomInput.step = String(minZoom / 100);
      zoomInput.value = String(zoom);
      const t = turned();
      x = (BOX - t.w * zoom) / 2;            // start centred
      y = (BOX - t.h * zoom) / 2;
      draw();
    };

    /** Keep the picture covering the whole window, never letting a gap show. */
    const clamp = () => {
      const t = turned();
      const w = t.w * zoom, h = t.h * zoom;
      x = w <= BOX ? (BOX - w) / 2 : Math.min(0, Math.max(BOX - w, x));
      y = h <= BOX ? (BOX - h) / 2 : Math.min(0, Math.max(BOX - h, y));
    };

    /** Paint the picture into a square canvas, turned by `angle`. */
    function paint(target, size) {
      const c = target.getContext("2d");
      const k = size / BOX;                       // 1 on screen, larger when saving
      const t = turned();
      c.clearRect(0, 0, size, size);
      // JPEG has no transparency, so anything not covered would save as black
      c.fillStyle = "#ffffff";
      c.fillRect(0, 0, size, size);
      c.save();
      // move to the middle of where the picture sits, turn, then draw centred
      c.translate((x + t.w * zoom / 2) * k, (y + t.h * zoom / 2) * k);
      c.rotate(angle * Math.PI / 180);
      c.drawImage(img, -img.width * zoom * k / 2, -img.height * zoom * k / 2,
                  img.width * zoom * k, img.height * zoom * k);
      c.restore();
    }

    function draw() {
      clamp();
      paint(canvas, BOX);
    }

    let dragging = false, startX = 0, startY = 0;
    canvas.addEventListener("pointerdown", (e) => {
      dragging = true; startX = e.clientX - x; startY = e.clientY - y;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      x = e.clientX - startX; y = e.clientY - startY;
      draw();
    });
    canvas.addEventListener("pointerup", () => { dragging = false; });

    zoomInput.addEventListener("input", () => {
      const next = Number(zoomInput.value);
      const cx = BOX / 2, cy = BOX / 2;            // zoom about the centre
      x = cx - (cx - x) * (next / zoom);
      y = cy - (cy - y) * (next / zoom);
      zoom = next;
      draw();
    });

    dlg.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.photoRot) {
        angle = (angle + Number(b.dataset.photoRot) + 360) % 360;
        // A quarter turn swaps the picture's width and height, so the old
        // x/y no longer cover the frame: rescale and centre on the new bounds.
        const t = turned();
        minZoom = Math.max(BOX / t.w, BOX / t.h);
        if (zoom < minZoom) zoom = minZoom;
        zoomInput.min = String(minZoom);
        zoomInput.max = String(minZoom * 4);
        zoomInput.step = String(minZoom / 100);
        zoomInput.value = String(zoom);
        x = (BOX - t.w * zoom) / 2;
        y = (BOX - t.h * zoom) / 2;
        draw();
        return;
      }
      if ("photoReset" in b.dataset) { reset(); return; }
      if ("photoCancel" in b.dataset) { dlg.close(); dlg.remove(); return; }
      if ("photoSave" in b.dataset) {
        const out = document.createElement("canvas");
        out.width = out.height = OUT;
        paint(out, OUT);                            // same framing, at print size
        const data = out.toDataURL("image/jpeg", 0.88);
        commit((cv) => { cv.personal.photo = data; });
        dlg.close(); dlg.remove();
        toast("Photo updated.");
      }
    });
    dlg.addEventListener("close", () => dlg.remove());

    reset();
    dlg.showModal();
  }

  /** Re-open the editor for the photo already on the CV. */
  function editExistingPhoto() {
    const src = (state.cv.personal || {}).photo;
    if (!src) { toast("Add a photo first."); return; }
    const img = new Image();
    img.onload = () => openPhotoEditor(img);
    img.onerror = () => toast("That photo could not be opened.", true);
    img.src = src;
  }

  // ----------------------------------------------------- import / export --

  async function openFile(file) {
    if (!confirm(`Replace this CV's content with ${file.name}? You can undo this with Ctrl+Z.`)) {
      els.fileInput.value = "";
      return;
    }
    const form = new FormData();
    form.append("file", file);
    document.body.classList.add("busy");
    try {
      const data = await (await api("/api/import", { method: "POST", body: form })).json();
      commit((cv) => {
        Object.keys(cv).forEach((k) => delete cv[k]);
        Object.assign(cv, data.cv);
      }, { select: "personal" });
      toast(`Opened ${file.name}.`);
      (data.warnings || []).forEach((w) => toast(w));
    } catch (err) {
      toast(err.message, true);
    } finally {
      document.body.classList.remove("busy");
      els.fileInput.value = "";
    }
  }

  function cleanForExport() {
    const cv = clone(state.cv);
    (cv.work_experience || []).forEach((j) => {
      if (Array.isArray(j.description)) j.description = j.description.map((s) => s.trim()).filter(Boolean);
    });
    return cv;
  }

  async function download(fmt) {
    document.body.classList.add("busy");
    try {
      const res = await postJSON(`/api/export/${fmt}`, { cv: cleanForExport() });
      const blob = await res.blob();
      const name = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || `cv.${fmt}`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast(`Downloaded ${name}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      document.body.classList.remove("busy");
    }
  }

  async function previewPdf() {
    document.body.classList.add("busy");
    try {
      const blob = await (await postJSON("/api/export/pdf", { cv: cleanForExport() })).blob();
      const frame = $("#previewFrame");
      if (frame.dataset.url) URL.revokeObjectURL(frame.dataset.url);
      frame.dataset.url = URL.createObjectURL(blob);
      frame.src = frame.dataset.url;
      $("#previewDialog").showModal();
    } catch (err) {
      toast(err.message, true);
    } finally {
      document.body.classList.remove("busy");
    }
  }

  // ------------------------------------------------------------ top bar --

  function setZoom(z) {
    state.zoom = Math.min(2, Math.max(0.4, z));
    els.pageWrap.style.zoom = state.zoom;
    els.zoomFit.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function fitZoom() {
    const available = els.canvas.clientWidth - 64;
    setZoom(Math.min(1.25, available / (210 * MM)));
  }

  function handleShortcut(e) {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return false;
    const inForm = ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) && els.inspector.contains(e.target);
    const k = e.key.toLowerCase();
    if (k === "z" && !e.shiftKey && !inForm) { e.preventDefault(); undo(); return true; }
    if (((k === "z" && e.shiftKey) || k === "y") && !inForm) { e.preventDefault(); redo(); return true; }
    if (k === "s") { e.preventDefault(); saveNow(); return true; }
    return false;
  }

  function wireMenus() {
    const menus = [["#fileBtn", "#fileMenu"], ["#downloadBtn", "#downloadMenu"]];
    const closeAll = () => menus.forEach(([b, m]) => { $(m).hidden = true; $(b).setAttribute("aria-expanded", "false"); });
    menus.forEach(([b, m]) => {
      $(b).addEventListener("click", (e) => {
        e.stopPropagation();
        const open = $(m).hidden;
        closeAll();
        $(m).hidden = !open;
        $(b).setAttribute("aria-expanded", String(open));
        if (open) $(m).querySelector("button").focus();
      });
    });
    document.addEventListener("click", closeAll);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

    $("#fileMenu").addEventListener("click", async (e) => {
      const action = e.target.closest("[data-action]")?.dataset.action;
      if (action === "open") els.fileInput.click();
    });
    $("#downloadMenu").addEventListener("click", (e) => {
      const fmt = e.target.closest("[data-fmt]")?.dataset.fmt;
      if (fmt) download(fmt);
    });
  }

  function wireTopbar() {
    els.undo.addEventListener("click", undo);
    els.redo.addEventListener("click", redo);
    $("#zoomIn").addEventListener("click", () => setZoom(state.zoom + 0.1));
    $("#zoomOut").addEventListener("click", () => setZoom(state.zoom - 0.1));
    els.zoomFit.addEventListener("click", fitZoom);
    $("#previewBtn").addEventListener("click", previewPdf);
    $("#previewClose").addEventListener("click", () => $("#previewDialog").close());
    els.fileInput.addEventListener("change", () => { if (els.fileInput.files[0]) openFile(els.fileInput.files[0]); });
    $("#personalRow").addEventListener("click", () => select("personal"));
    $("#addCustom").addEventListener("click", addCustomSection);

    $$(".tab").forEach((tab) => tab.addEventListener("click", () => {
      $$(".tab").forEach((t) => { t.classList.toggle("is-active", t === tab); t.setAttribute("aria-selected", String(t === tab)); });
      $("#tab-content").hidden = tab.dataset.tab !== "content";
      $("#tab-design").hidden = tab.dataset.tab !== "design";
    }));

    document.addEventListener("keydown", (e) => {
      if (handleShortcut(e)) return;
      if (e.key === "Escape" && state.selected && !els.inspector.contains(e.target)) select(null);
    });

    // drag a file anywhere onto the window to open it
    let depth = 0;
    const overlay = $("#dropOverlay");
    const hasFile = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
    window.addEventListener("dragenter", (e) => { if (hasFile(e)) { depth++; overlay.hidden = false; } });
    window.addEventListener("dragleave", (e) => { if (hasFile(e) && --depth <= 0) { depth = 0; overlay.hidden = true; } });
    window.addEventListener("dragover", (e) => { if (hasFile(e)) e.preventDefault(); });
    window.addEventListener("drop", (e) => {
      if (!hasFile(e)) return;
      e.preventDefault();
      depth = 0;
      overlay.hidden = true;
      if (e.dataTransfer.files[0]) openFile(e.dataTransfer.files[0]);
    });

    window.addEventListener("resize", () => { if (window.innerWidth < 900) fitZoom(); });

    $("#statusSelect").addEventListener("change", async (e) => {
      const status = e.target.value;
      e.target.dataset.v = status;
      try {
        applyRecord(await (await api(`/api/cvs/${CV_ID}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
        })).json());
        toast(`Marked as ${e.target.selectedOptions[0].text.toLowerCase()}.`);
      } catch (err) { toast(err.message, true); }
    });

    $("#checks").addEventListener("click", async (e) => {
      if (e.target.id !== "clearChecks") return;
      try {
        applyRecord(await (await api(`/api/cvs/${CV_ID}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ warnings: [] }),
        })).json());
      } catch (err) { toast(err.message, true); }
    });

    window.addEventListener("beforeunload", (e) => {
      if (state.unsaved) { saveNow(); e.preventDefault(); e.returnValue = ""; }
    });
    $(".back-link").addEventListener("click", async (e) => {
      if (!state.unsaved) return;
      e.preventDefault();
      await saveNow();
      location.href = "/";
    });
  }

  // ---------------------------------------------------------------- start --

  async function start() {
    if (!CV_ID) { location.href = "/"; return; }
    try {
      state.meta = await (await api("/api/meta")).json();
      const record = await (await api(`/api/cvs/${CV_ID}`)).json();
      state.cv = record.cv;
      delete record.cv;
      delete record.original;
      applyRecord(record);
    } catch (err) {
      els.inspector.innerHTML = `<div class="empty-state"><strong>The editor could not start</strong>${esc(err.message)}. Check that the server is running (python app.py), then reload the page or go back to the list of CVs.</div>`;
      return;
    }

    // the floating format toolbar is off; Ctrl+B / I / U still work
    wireSectionList();
    wireDesign();
    wireInspector();
    wireMenus();
    wireTopbar();
    updateUndoButtons();

    renderSections();
    renderDesign();
    renderInspector();
    fitZoom();
    await renderPage();
    setSaveState("All changes saved");
  }

  start();
})();