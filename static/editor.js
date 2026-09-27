/* Europass CV editor
 * ------------------------------------------------------------------------
 * The CV lives in one JSON object (state.cv). The server renders it with the
 * same template used for the PDF; the page is shown in an iframe where text
 * marked with data-path can be edited in place and blocks marked with
 * data-select can be selected. The side panels edit everything else.
 */
(() => {
  "use strict";

  const STORAGE_KEY = "europass-cv-editor:v1";
  const LEVELS = ["", "A1", "A2", "B1", "B2", "C1", "C2"];
  const LEVEL_KEYS = [
    ["listening", "Listen"], ["reading", "Read"], ["spoken_production", "Speak"],
    ["spoken_interaction", "Interact"], ["writing", "Write"],
  ];
  const LICENCES = ["AM", "A1", "A2", "A", "B1", "B", "BE", "C1", "C1E", "C", "CE", "D1", "D1E", "D", "DE"];
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

  function scheduleSave() {
    els.saveState.textContent = "Saving…";
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, snapshot());
        els.saveState.textContent = "Saved on this computer";
      } catch {
        els.saveState.textContent = "Not saved: storage is full";
        toast("Autosave failed because the browser storage is full. Download a JSON backup, or use a smaller photo.", true);
      }
    }, 400);
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

  function resizePage(doc) {
    const body = doc.body;
    if (!body) return;
    doc.querySelectorAll(".page-guide").forEach((g) => g.remove());
    const height = Math.max(297 * MM, doc.documentElement.scrollHeight);
    els.page.style.height = `${Math.ceil(height)}px`;

    // Approximate page ends: 10 mm top margin + 275 mm of content per A4 page.
    const pageContent = 275 * MM;
    for (let y = 10 * MM + pageContent, n = 2; y < height - 20; y += pageContent, n++) {
      const g = doc.createElement("div");
      g.className = "page-guide";
      g.setAttribute("aria-hidden", "true");
      g.textContent = `Page ${n}`;
      g.style.cssText = `position:absolute;left:0;right:0;top:${y}px;border-top:1px dashed #d68b1d;
        pointer-events:none;font:600 9px/1 "Public Sans",sans-serif;color:#d68b1d;text-align:right;padding:3px 6px 0;`;
      body.appendChild(g);
    }
    body.style.position = "relative";
  }

  function wirePage(doc) {
    const plainOnly = (() => {
      const probe = doc.createElement("span");
      try { probe.contentEditable = "plaintext-only"; return probe.contentEditable === "plaintext-only"; } catch { return false; }
    })();

    doc.querySelectorAll("[data-path]").forEach((el) => {
      el.contentEditable = plainOnly ? "plaintext-only" : "true";
      el.spellcheck = true;
    });

    doc.addEventListener("click", (e) => {
      if (e.target.closest("a")) e.preventDefault();
      const block = e.target.closest("[data-select]");
      select(block ? block.dataset.select : null, { scroll: false });
    });

    doc.addEventListener("input", (e) => {
      const el = e.target.closest("[data-path]");
      if (!el) return;
      const multiline = el.dataset.multiline === "1";
      let text = multiline ? el.innerText : el.textContent;
      if (!multiline) text = text.replace(/\n/g, " ");
      update(el.dataset.path, text, { render: false });
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
      doc.execCommand("insertText", false, text);
    });

    doc.addEventListener("keydown", (e) => {
      if (handleShortcut(e)) return;
      const el = e.target.closest && e.target.closest("[data-path]");
      if (!el) return;
      const path = el.dataset.path;
      const bullet = path.match(/^(.*\.description)\.(\d+)$/);

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
      const canAdd = key === "work_experience" || key === "education" || key.startsWith("custom:");
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
    if (key === "work_experience" || key === "education") return selected.startsWith(`${key}.`);
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
  }

  function wireDesign() {
    const setDesign = (key, value, typing = false) => {
      if (typing) update(`design.${key}`, value);
      else commit((cv) => { cv.design[key] = value; });
    };
    $("#dFont").addEventListener("change", (e) => setDesign("font", e.target.value));
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
        <div class="subhead">Contact</div>
        <div class="field-row-3">
          ${input("Code", "personal.phone.country_dialing", { placeholder: "91" })}
          ${input("Number", "personal.phone.number", { type: "tel" })}
          ${selectBox("Type", "personal.phone.type", [["Mobile", "Mobile"], ["Home", "Home"], ["Work", "Work"], ["", "—"]])}
        </div>
        ${input("Email address", "personal.email", { type: "email" })}
        ${input("Website", "personal.website", { type: "url", placeholder: "https://" })}
        <div class="subhead">Address</div>
        ${input("Street and number", "personal.address.street")}
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
      img.onload = () => {
        const max = 600;
        const scale = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * scale);
        c.height = Math.round(img.height * scale);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        const data = c.toDataURL("image/jpeg", 0.86);
        commit((cv) => { cv.personal.photo = data; });
      };
      img.onerror = () => toast("That image could not be read. Try a JPG or PNG file.", true);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  // ----------------------------------------------------- import / export --

  async function openFile(file) {
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
    if (k === "s") { e.preventDefault(); download("json"); return true; }
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
      if (action === "sample" || action === "blank") {
        if (!confirm("Replace the CV you are editing? You can undo this with Ctrl+Z.")) return;
        const cv = await (await api(`/api/${action}`)).json();
        commit((c) => { Object.keys(c).forEach((k) => delete c[k]); Object.assign(c, cv); }, { select: "personal" });
      }
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
  }

  // ---------------------------------------------------------------- start --

  async function start() {
    try {
      state.meta = await (await api("/api/meta")).json();
      let cv = null;
      try { cv = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); } catch { cv = null; }
      if (!cv || !cv.personal) cv = await (await api("/api/sample")).json();
      state.cv = cv;
    } catch (err) {
      els.inspector.innerHTML = `<div class="empty-state"><strong>The editor could not start</strong>${esc(err.message)}. Check that the server is running (python app.py) and reload the page.</div>`;
      return;
    }

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
    els.saveState.textContent = "Saved on this computer";
  }

  start();
})();
