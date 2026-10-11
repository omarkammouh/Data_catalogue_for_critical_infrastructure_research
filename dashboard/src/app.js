/*
 * Dashboard application: DOM, URL state, views, export, keyboard, theme.
 *
 * State lives in the query string. `readState()` parses it, `writeState()`
 * pushes it, and `popstate` re-reads it, so back and forward are undo and
 * redo for every filter, sort and view change. Rendering is one `update()`:
 * run the engine, refresh the counts in the facet panel in place (so focus and
 * scroll are kept), rebuild the chips and the result area.
 *
 * Nothing here knows a field name: every facet, column and export field is
 * derived from the facet definitions and the records that build.py inlined.
 */
(function () {
  "use strict";

  const PAGE_SIZE = 50;
  const SHOW_MORE_AFTER = 8;
  const MAX_BARS = 120;              // bars drawn in a year histogram
  const DETACH_ABOVE = 300;          // facets with more top-level values keep only the visible rows attached to the page
  const SEARCH_SHOW_LIMIT = 60;      // matches listed at once while a filter search is active (providers number in the tens of thousands)
  const FACET_SEARCH_MIN_VALUES = 6; // facets with fewer values are short enough to read; the all-filters box still finds them
  const DEBOUNCE_ABOVE = 2000;       // lists longer than this wait for a pause in typing
  const STORAGE = { theme: "catalogue.theme", help: "catalogue.helpSeen", columns: "catalogue.columns" };
  const SORT_LABELS = { relevance: "Relevance", name: "Name", provider: "Provider", date_catalogued: "Date catalogued", date_verified: "Links checked", last_updated: "Last updated" };
  const VIEWS = ["list", "table", "coverage"];

  /* ------------------------------------------------------------ helpers */

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  function store(key, value) { try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable */ } }
  function load(key, fallback) { try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; } }
  function humanise(s) { return /^[a-z0-9]+(_[a-z0-9]+)*$/.test(s) ? s.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : s; }
  const t = (key, vars) => I18N.t(key, vars);
  /** Singular or plural message; `{n}` in the message is the number, formatted for the language. */
  const tn = (n, one, many) => I18N.t(n === 1 ? one : many, { n: fmtInt(n) });
  function fmtInt(n) { return I18N.number(n); }

  /* --------------------------------------------------------------- data */

  let DATA, ENGINE, FACETS, RECORDS, META;
  const byId = new Map();
  const valueLabel = new Map(); // facetId -> Map(value -> label)

  /* -------------------------------------------------------------- state */

  function emptyState() { return { text: "", facets: {}, order: [], sort: "relevance", dir: null, view: "list", record: null, page: 1 }; }

  /** decodeURIComponent that never throws: a stray "%" in a hand-edited or truncated address is kept as written (audit 2026-09-24: it used to replace the whole page with the error state). */
  function safeDecode(v) { try { return decodeURIComponent(v); } catch (e) { return v; } }

  function readState() {
    const params = new URLSearchParams(location.search);
    const s = emptyState();
    for (const [key, raw] of params) {
      if (key === "q") s.text = raw;
      else if (key === "sort") s.sort = raw in SORT_LABELS ? raw : "relevance";
      else if (key === "dir") s.dir = raw === "asc" || raw === "desc" ? raw : null;
      else if (key === "view") s.view = VIEWS.includes(raw) ? raw : "list";
      else if (key === "r") s.record = raw;
      else if (key === "page") s.page = Math.max(1, parseInt(raw, 10) || 1);
      else if (key.endsWith(".all")) {
        const fid = key.slice(0, -4);
        if (ENGINE.facetById.has(fid)) { s.facets[fid] = s.facets[fid] || { values: [] }; s.facets[fid].all = raw === "1"; }
      } else if (ENGINE.facetById.has(key)) {
        const facet = ENGINE.facetById.get(key);
        if (facet.kind === "range") {
          const m = /^(-?\d+(?:\.\d+)?)?\.\.(-?\d+(?:\.\d+)?)?$/.exec(raw); // decimals: log-scale facets step below 1 (0.1 m)
          if (m) { s.facets[key] = { min: m[1] ? Number(m[1]) : null, max: m[2] ? Number(m[2]) : null }; if (!s.order.includes(key)) s.order.push(key); }
        } else if (facet.kind !== "text") {
          const values = raw.split(",").map(safeDecode).filter(Boolean);
          const prev = s.facets[key] || {};
          s.facets[key] = { values, all: !!prev.all };
          if (!s.order.includes(key)) s.order.push(key);
        }
      }
    }
    return s;
  }

  function toQuery(s) {
    const p = new URLSearchParams();
    if (s.text) p.set("q", s.text);
    for (const fid of s.order) {
      const sel = s.facets[fid];
      if (!sel) continue;
      if ("min" in sel || "max" in sel) {
        if (sel.min != null || sel.max != null) p.set(fid, (sel.min ?? "") + ".." + (sel.max ?? ""));
      } else if (sel.values && sel.values.length) {
        p.set(fid, sel.values.map(v => encodeURIComponent(v)).join(","));
        if (sel.all) p.set(fid + ".all", "1");
      }
    }
    if (s.sort !== "relevance") p.set("sort", s.sort);
    if (s.dir) p.set("dir", s.dir);
    if (s.view !== "list") p.set("view", s.view);
    if (s.page > 1) p.set("page", String(s.page));
    if (s.record) p.set("r", s.record);
    const q = p.toString().replace(/%2C/g, "%2C"); // keep commas inside values encoded
    return q ? "?" + q : location.pathname.split("/").pop() || "?";
  }

  let state = emptyState();

  function writeState(next, { replace = false } = {}) {
    state = next;
    const url = toQuery(state);
    try { history[replace ? "replaceState" : "pushState"]({ s: state }, "", url); }
    catch (e) { /* some hosts refuse pushState; the page still works without it */ }
    update();
  }

  function cloneState() { return JSON.parse(JSON.stringify(state)); }

  function isActive(s) { return !!s.text || s.order.some(fid => { const sel = s.facets[fid]; return sel && ((sel.values && sel.values.length) || sel.min != null || sel.max != null); }); }

  /* ------------------------------------------------- facet interactions */

  function toggleValue(fid, value, on) {
    const s = cloneState();
    const sel = s.facets[fid] || { values: [], all: false };
    const set = new Set(sel.values);
    if (on) set.add(value); else set.delete(value);
    sel.values = Array.from(set);
    s.facets[fid] = sel;
    if (sel.values.length && !s.order.includes(fid)) s.order.push(fid);
    if (!sel.values.length) { delete s.facets[fid]; s.order = s.order.filter(x => x !== fid); }
    s.page = 1; s.record = null;
    if (s.view === "coverage") { /* stay */ }
    writeState(s);
  }

  function setMatchAll(fid, all) {
    const s = cloneState();
    const sel = s.facets[fid] || { values: [], all: false };
    sel.all = all; s.facets[fid] = sel; s.page = 1;
    if (sel.values.length && !s.order.includes(fid)) s.order.push(fid);
    writeState(s);
  }

  function setRange(fid, min, max) {
    const s = cloneState();
    if (min == null && max == null) { delete s.facets[fid]; s.order = s.order.filter(x => x !== fid); }
    else { s.facets[fid] = { min, max }; if (!s.order.includes(fid)) s.order.push(fid); }
    s.page = 1; s.record = null;
    writeState(s);
  }

  function setText(text) {
    const s = cloneState();
    s.text = text; s.page = 1; s.record = null;
    if (s.view === "coverage") s.view = "list";
    writeState(s, { replace: state.text !== "" && text !== "" });
  }

  function clearAll() {
    const s = emptyState();
    s.sort = state.sort; s.dir = state.dir; s.view = state.view === "coverage" ? "coverage" : state.view;
    writeState(s);
    toast(t("Filters cleared"), { label: t("Undo"), action: () => history.back() });
  }

  function removeLast() {
    const s = cloneState();
    if (s.order.length) { const fid = s.order.pop(); delete s.facets[fid]; }
    else s.text = "";
    s.page = 1;
    writeState(s);
  }

  /* ---------------------------------------------------- facet panel DOM */

  const panel = { rows: new Map(), facetEls: new Map(), rangeEls: new Map(), groups: [], globalActive: false, savedOpen: new Map(), labelNorm: new Map(), totalValues: 0 };
  let globalTokens = []; // normalised words typed in the all-filters box
  const tokensOf = text => ENGINE_NORMALISE(text).split(" ").filter(Boolean);
  const debounced = (fn, wait) => { let id = 0; return () => { clearTimeout(id); id = setTimeout(fn, wait); }; };

  function buildFacetPanel() {
    const host = $("#facets");
    host.textContent = "";
    const groups = new Map();
    for (const facet of FACETS) {
      if (facet.kind === "text" || facet.empty) continue;
      const g = facet.group || "Other";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(facet);
    }
    const order = META.panel_groups || [];
    const keys = Array.from(groups.keys()).sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
    panel.groups = [];
    panel.totalValues = 0;
    panel.labelNorm.clear();
    for (const g of keys) {
      const title = h("div", { class: "facet-group-title", text: t(g) });
      host.append(title);
      const members = [];
      for (const facet of groups.get(g)) {
        const el = facet.kind === "range" ? buildRangeFacet(facet) : buildValueFacet(facet);
        host.append(el);
        members.push({ facet, details: el });
        if (facet.kind !== "range") panel.totalValues += facet.values.length;
      }
      panel.groups.push({ title, members });
    }
    applyGlobalSearch();
  }

  function buildValueFacet(facet) {
    const labels = new Map();
    for (const v of facet.values) labels.set(v.value, v.label);
    valueLabel.set(facet.id, labels);
    const openByDefault = ["type", "data_resource_type", "sectors", "data_family", "model_kind", "platform_kind", "case_study_kind"].includes(facet.id);
    const details = h("details", { class: "facet", open: openByDefault, dataset: { facet: facet.id } });
    const badge = h("span", { class: "badge", hidden: true });
    const summary = h("summary", null, h("span", { class: "facet-label", text: t(facet.label) }), badge);
    details.append(summary);
    const body = h("div", { class: "facet-body" });
    details.append(body);

    // tools: search within facet, sort, match all
    const tools = h("div", { class: "facet-tools" });
    let search = null;
    if (facet.values.length >= FACET_SEARCH_MIN_VALUES) {
      search = h("input", { type: "search", placeholder: t("Find in {facet}", { facet: I18N.lang === "de" ? t(facet.label) : t(facet.label).toLowerCase() }), "aria-label": t("Find in {facet}", { facet: t(facet.label) }), id: "facet-search-" + facet.id, autocomplete: "off", spellcheck: "false" });
      const run = () => applyFacetOrder(facet);
      search.addEventListener("input", facet.values.length > DEBOUNCE_ABOVE ? debounced(run, 80) : run);
      tools.append(search);
    }
    const sortBtn = h("button", { type: "button", class: "link-button", text: t("A–Z"), title: t("Sort alphabetically"), "aria-pressed": "false", id: "facet-sort-" + facet.id });
    sortBtn.addEventListener("click", () => { const on = sortBtn.getAttribute("aria-pressed") !== "true"; sortBtn.setAttribute("aria-pressed", String(on)); sortBtn.textContent = on ? t("By count") : t("A–Z"); applyFacetOrder(facet); });
    tools.append(sortBtn);
    let allSwitch = null;
    if (facet.multi_valued) {
      allSwitch = h("input", { type: "checkbox", id: "facet-all-" + facet.id });
      allSwitch.addEventListener("change", () => setMatchAll(facet.id, allSwitch.checked));
      tools.append(h("label", { class: "switch", title: t("Records must carry every selected value") }, allSwitch, t("Match all")));
    }
    body.append(tools);

    const list = h("ul", { class: "facet-values", "aria-label": t(facet.label) }); // no role="group": it removed the list semantics and orphaned every <li> (axe, audit 2026-09-24)
    const rows = new Map();
    const children = new Map();
    for (const v of facet.values) if (v.parent) { if (!children.has(v.parent)) children.set(v.parent, []); children.get(v.parent).push(v.value); }

    // ids must be unique: values that differ only in non-Latin letters used to collapse to the same id, and the
    // label's `for` then ticked the first of them (clicking Incheon filtered by Seoul; round 2 check, 2026-10-01)
    const usedIds = new Set();
    for (const v of facet.values) {
      let id = "fv-" + facet.id + "-" + v.value.replace(/[^a-zA-Z0-9_-]/g, "_");
      for (let n = 2; usedIds.has(id); n++) id = "fv-" + facet.id + "-" + v.value.replace(/[^a-zA-Z0-9_-]/g, "_") + "-" + n;
      usedIds.add(id);
      const input = h("input", { type: "checkbox", id, dataset: { facet: facet.id, value: v.value } });
      input.addEventListener("change", () => toggleValue(facet.id, v.value, input.checked));
      const count = h("span", { class: "count tabular", text: fmtInt(v.count) });
      const label = h("label", { class: "value", for: id, title: v.note || null }, input, h("span", { class: "value-label", text: v.label }), count);
      const li = h("li", { class: v.parent ? "child" : "parent", dataset: { value: v.value } });
      let toggle = null;
      if (children.has(v.value)) {
        toggle = h("button", { type: "button", class: "tree-toggle", "aria-expanded": "false", "aria-label": t("Show the values under {value}", { value: v.label }) });
        toggle.addEventListener("click", () => { const open = toggle.getAttribute("aria-expanded") !== "true"; toggle.setAttribute("aria-expanded", String(open)); for (const c of children.get(v.value)) rows.get(c).li.hidden = !open; });
        li.append(h("div", { style: "display:flex;align-items:center;gap:2px" }, toggle, label));
        label.style.flex = "1";
      } else li.append(label);
      if (v.parent) li.hidden = true;
      rows.set(v.value, { li, input, count, label, base: v.count, labelText: v.label, value: v.value, note: v.note || "", hay: null, parent: v.parent, toggle, kids: children.get(v.value) || [] });
      list.append(li);
    }
    const more = h("button", { type: "button", class: "link-button", hidden: true });
    let expanded = false;
    more.addEventListener("click", () => { expanded = !expanded; applyFacetOrder(facet); });
    const none = h("p", { class: "facet-empty", hidden: true, text: t("No matching values") });
    body.append(none, list, more);
    panel.rows.set(facet.id, rows);
    panel.facetEls.set(facet.id, { details, badge, list, more, none, search, sortBtn, allSwitch, isExpanded: () => expanded, setExpanded: v => { expanded = v; }, children, orderedAlpha: null, top: [], lastNeedle: "" });
    applyFacetOrder(facet);
    return details;
  }

  /** Order the rows of one facet by catalogue count or A–Z; rows are moved in the DOM only when this order changes. */
  function orderRows(rows, el, alpha) {
    const cmp = ([, a], [, b]) => alpha ? a.labelText.localeCompare(b.labelText) : (b.base - a.base) || a.labelText.localeCompare(b.labelText);
    const top = Array.from(rows.entries()).filter(([, r]) => !r.parent).sort(cmp);
    el.top = [];
    const big = top.length > DETACH_ABOVE; // applyFacetOrder attaches only the visible rows of these, in this order
    for (const [value, r] of top) {
      const kids = r.kids.map(k => [k, rows.get(k)]).sort(cmp);
      if (!big) { el.list.append(r.li); for (const [, kr] of kids) el.list.append(kr.li); }
      el.top.push({ value, r, kids });
    }
    el.orderedAlpha = alpha;
  }

  /** What the search boxes ask of one facet: the words a value must carry, and whether the facet's own name answered the all-filters words. */
  function facetLabelNorm(facet) {
    let norm = panel.labelNorm.get(facet.id);
    if (norm == null) { norm = ENGINE_NORMALISE(facet.label + " " + t(facet.label) + " " + (facet.group ? t(facet.group) : "")); panel.labelNorm.set(facet.id, norm); }
    return norm;
  }
  function queryFor(facet, el) {
    const local = el && el.search ? tokensOf(el.search.value) : [];
    let rest = [], byLabel = false;
    if (globalTokens.length) {
      const norm = facetLabelNorm(facet);
      rest = globalTokens.filter(tok => !norm.includes(tok));
      byLabel = rest.length === 0;
    }
    return { tokens: local.concat(rest), byLabel };
  }
  function rowMatches(r, tokens) {
    if (r.hay == null) r.hay = ENGINE_NORMALISE(r.labelText + " " + r.value + " " + r.note);
    for (const tok of tokens) if (!r.hay.includes(tok)) return false;
    return true;
  }
  const setHidden = (node, hidden) => { if (node.hidden !== hidden) node.hidden = hidden; };

  /** Make `list` hold exactly `wanted`, in that order. A row with keyboard focus is never detached and re-attached (that would drop the focus). */
  function syncList(list, wanted) {
    if (!list.contains(document.activeElement)) {
      const frag = document.createDocumentFragment();
      for (const li of wanted) frag.append(li);
      list.replaceChildren(frag);
      return;
    }
    const keep = new Set(wanted);
    let cur = list.firstChild;
    for (const li of wanted) {
      while (cur && !keep.has(cur)) { const next = cur.nextSibling; cur.remove(); cur = next; }
      if (cur === li) cur = cur.nextSibling; else list.insertBefore(li, cur);
    }
    while (cur) { const next = cur.nextSibling; cur.remove(); cur = next; }
  }

  /** Apply the sort, the in-facet search, the all-filters search and the show-more limit to one facet. Ticked values always stay visible. */
  function applyFacetOrder(facet) {
    const rows = panel.rows.get(facet.id);
    const el = panel.facetEls.get(facet.id);
    const alpha = el.sortBtn.getAttribute("aria-pressed") === "true";
    if (el.orderedAlpha !== alpha) orderRows(rows, el, alpha);
    const q = queryFor(facet, el);
    const searching = q.tokens.length > 0;
    const key = q.tokens.join(" ");
    const cleared = key === "" && el.lastNeedle !== ""; // a search that opened parent values closes them again when it is cleared
    if (key !== el.lastNeedle) { el.lastNeedle = key; el.setExpanded(false); }
    const limit = searching ? SEARCH_SHOW_LIMIT : SHOW_MORE_AFTER;
    let shown = 0, matched = 0, hiddenByLimit = 0, anySelected = false;
    // Lists of thousands of rows (provider 26,153, regions, publishers) keep only the visible rows in the page: hiding or
    // showing 20,000 attached rows made the browser redo style work per row, and clearing a provider search after
    // "Show 26,153 more" froze the page for 85 s (round 2 check). The other rows stay in panel.rows, detached, and are
    // still counted and ticked like the rest.
    const detach = el.top.length > DETACH_ABOVE;
    const attach = detach ? [] : null;
    for (const { r, kids } of el.top) {
      const selfMatch = !searching || rowMatches(r, q.tokens);
      let kidMatch = false, kidSelected = false;
      const kidHit = kids.map(([, kr]) => {
        if (kr.input.checked) kidSelected = true;
        const hit = !searching || rowMatches(kr, q.tokens);
        if (hit && searching) kidMatch = true;
        return hit;
      });
      const match = selfMatch || kidMatch;
      const selected = r.input.checked || kidSelected;
      if (selected) anySelected = true;
      if (match) matched++;
      let visible = match || selected;
      if (visible && !selected && !el.isExpanded() && shown >= limit) { visible = false; hiddenByLimit++; }
      setHidden(r.li, !visible);
      if (visible) { shown++; if (attach) attach.push(r.li); }
      let openKids = false;
      if (r.toggle) {
        openKids = cleared ? kidSelected : (searching && kidMatch) || kidSelected || r.toggle.getAttribute("aria-expanded") === "true";
        if (searching || kidSelected || cleared) r.toggle.setAttribute("aria-expanded", String(openKids));
      }
      kids.forEach(([, kr], i) => {
        setHidden(kr.li, !visible || !openKids || (searching && !selfMatch && !kidHit[i] && !kr.input.checked));
        if (attach && visible) attach.push(kr.li);
      });
    }
    if (attach) syncList(el.list, attach);
    el.more.hidden = !(hiddenByLimit > 0 || (el.isExpanded() && matched > limit));
    el.more.textContent = el.isExpanded() ? t("Show fewer") : t("Show {n} more", { n: hiddenByLimit });
    el.none.hidden = !(searching && matched === 0);
    setHidden(el.details, globalTokens.length > 0 && !(q.byLabel || matched > 0 || anySelected));
  }

  /** The "search all filters" box: narrows every facet to the values (and facets) that match, opens them, and restores the panel when cleared. */
  function applyGlobalSearch() {
    const input = $("#filter-search");
    if (!input || !panel.groups.length) return;
    globalTokens = tokensOf(input.value);
    const active = globalTokens.length > 0;
    if (active && !panel.globalActive) {
      panel.savedOpen.clear();
      for (const g of panel.groups) for (const m of g.members) panel.savedOpen.set(m.facet.id, m.details.open);
    }
    let shownFacets = 0, total = 0;
    for (const g of panel.groups) {
      let anyVisible = false;
      for (const { facet, details } of g.members) {
        total++;
        if (facet.kind === "range") {
          const hidden = active && !queryFor(facet, null).byLabel;
          setHidden(details, hidden);
          if (active && !hidden) details.open = true;
        } else {
          applyFacetOrder(facet);
          if (active && !details.hidden) details.open = true;
        }
        if (!active && panel.globalActive && panel.savedOpen.has(facet.id)) {
          const sel = state.facets[facet.id];
          details.open = panel.savedOpen.get(facet.id) || !!(sel && (sel.values ? sel.values.length : sel.min != null || sel.max != null));
        }
        if (!details.hidden) { anyVisible = true; shownFacets++; }
      }
      setHidden(g.title, !anyVisible);
    }
    panel.globalActive = active;
    $("#filter-search-status").textContent = active ? t("Filters matching: {n} of {m}", { n: shownFacets, m: total }) : "";
  }
  function updateGroupTitles() {
    for (const g of panel.groups) setHidden(g.title, g.members.every(m => m.details.hidden));
  }

  /* Numbers of a logarithmic range facet (size in bytes, resolution in metres) are chosen by decade. */
  function fmtQuantity(v, unit) {
    if (v == null) return "";
    const steps = unit === "bytes" ? [[1e15, "PB"], [1e12, "TB"], [1e9, "GB"], [1e6, "MB"], [1e3, "kB"], [1, "B"]]
      : unit === "metres" ? [[1e3, "km"], [1, "m"], [1e-2, "cm"], [1e-3, "mm"]] : [[1, ""]];
    for (const [f, u] of steps) if (Math.abs(v) >= f || f === steps[steps.length - 1][0]) { const x = v / f; return (Number.isInteger(x) ? String(x) : String(Number(x.toPrecision(3)))) + (u ? " " + u : ""); }
    return String(v);
  }
  function decades(facet) {
    const out = [];
    if (facet.min == null || facet.max == null) return out;
    const lo = facet.min > 0 ? facet.min : Math.min(1, facet.max > 0 ? facet.max : 1); // a zero (an empty file) has no decade
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(Math.max(lo, facet.max))); e++) out.push(Math.pow(10, e));
    return out;
  }
  function rangeText(facet, sel) {
    const f = v => facet.scale === "log10" ? fmtQuantity(v, facet.unit) : String(v);
    return sel.min != null && sel.max != null ? f(sel.min) + "–" + f(sel.max) : sel.min != null ? t("from") + " " + f(sel.min) : t("to") + " " + f(sel.max);
  }

  function buildRangeFacet(facet) {
    if (facet.scale === "log10") return buildLogRangeFacet(facet);
    const details = h("details", { class: "facet", dataset: { facet: facet.id } });
    const badge = h("span", { class: "badge", hidden: true });
    details.append(h("summary", null, h("span", { class: "facet-label", text: t(facet.label) }), badge));
    const body = h("div", { class: "facet-body" });
    const hist = h("div", { class: "range-hist", "aria-hidden": "true" });
    const minIn = h("input", { type: "number", inputmode: "numeric", placeholder: String(facet.min), "aria-label": t(facet.label) + " " + t("from"), id: "range-min-" + facet.id, min: facet.min, max: facet.max });
    const maxIn = h("input", { type: "number", inputmode: "numeric", placeholder: String(facet.max), "aria-label": t(facet.label) + " " + t("to"), id: "range-max-" + facet.id, min: facet.min, max: facet.max });
    const commit = () => {
      const lo = minIn.value === "" ? null : Number(minIn.value); const hi = maxIn.value === "" ? null : Number(maxIn.value);
      const cur = state.facets[facet.id] || { min: null, max: null };
      if ((cur.min ?? null) === lo && (cur.max ?? null) === hi) return; // blur after Enter re-fires change; nothing changed
      setRange(facet.id, lo, hi);
    };
    for (const el of [minIn, maxIn]) { el.addEventListener("change", commit); el.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); commit(); } }); }
    body.append(hist, h("div", { class: "range" }, minIn, h("span", { text: t("to"), "aria-hidden": "true" }), maxIn));
    details.append(body);
    panel.rangeEls.set(facet.id, { details, badge, hist, minIn, maxIn });
    return details;
  }

  function buildLogRangeFacet(facet) {
    const details = h("details", { class: "facet", dataset: { facet: facet.id } });
    const badge = h("span", { class: "badge", hidden: true });
    details.append(h("summary", null, h("span", { class: "facet-label", text: t(facet.label) }), badge));
    const body = h("div", { class: "facet-body" });
    const hist = h("div", { class: "range-hist", "aria-hidden": "true" });
    const steps = decades(facet);
    const select = (label, id) => h("select", { "aria-label": t(facet.label) + " " + label, id },
      h("option", { value: "", text: t("any") }), steps.map(v => h("option", { value: String(v), text: fmtQuantity(v, facet.unit) })));
    const minIn = select(t("from"), "range-min-" + facet.id), maxIn = select(t("to"), "range-max-" + facet.id);
    const commit = () => setRange(facet.id, minIn.value === "" ? null : Number(minIn.value), maxIn.value === "" ? null : Number(maxIn.value));
    minIn.addEventListener("change", commit); maxIn.addEventListener("change", commit);
    body.append(hist, h("div", { class: "range" }, minIn, h("span", { text: t("to"), "aria-hidden": "true" }), maxIn));
    details.append(body);
    panel.rangeEls.set(facet.id, { details, badge, hist, minIn, maxIn, log: true, steps });
    return details;
  }

  /** Refresh counts, disabled state, checked state and badges in place after a query. */
  function refreshFacetPanel(result) {
    let activeFacets = 0;
    for (const facet of FACETS) {
      if (facet.kind === "text" || facet.empty) continue;
      const sel = state.facets[facet.id];
      if (facet.kind === "range") {
        const el = panel.rangeEls.get(facet.id);
        const active = sel && (sel.min != null || sel.max != null);
        el.badge.hidden = !active; el.badge.textContent = active ? "1" : "";
        if (active) activeFacets++;
        el.minIn.value = active && sel.min != null ? sel.min : "";
        el.maxIn.value = active && sel.max != null ? sel.max : "";
        const histo = result.ranges[facet.id] || {};
        if (el.log) { // one bar per decade: [10^e, 10^(e+1))
          const bins = el.steps.map(() => 0);
          for (const [v, c] of Object.entries(histo)) { const k = el.steps.findIndex((d, j) => Number(v) >= d && (j === el.steps.length - 1 || Number(v) < el.steps[j + 1])); if (k >= 0) bins[k] += c; }
          const top = Math.max(1, ...bins);
          el.hist.textContent = "";
          el.steps.forEach((d, k) => {
            const inRange = !active || ((sel.min == null || d * 10 > sel.min) && (sel.max == null || d <= sel.max));
            el.hist.append(h("span", { class: inRange ? "" : "off", style: "height:" + Math.max(2, Math.round(100 * bins[k] / top)) + "%", title: fmtQuantity(d, facet.unit) + ": " + bins[k] }));
          });
          continue;
        }
        // at most MAX_BARS bars: a facet spanning the years 1 to 9999 (bad dates in the data) used to draw 9,999 elements per query
        const span = facet.max - facet.min + 1, width = Math.max(1, Math.ceil(span / MAX_BARS));
        const bars = [];
        for (let y0 = facet.min; y0 <= facet.max; y0 += width) {
          const y1 = Math.min(facet.max, y0 + width - 1);
          let c = 0; for (let y = y0; y <= y1; y++) c = Math.max(c, histo[y] || 0);
          bars.push({ y0, y1, c });
        }
        const max = Math.max(1, ...bars.map(b => b.c));
        el.hist.textContent = "";
        for (const bar of bars) {
          const inRange = !active || ((sel.min == null || bar.y1 >= sel.min) && (sel.max == null || bar.y0 <= sel.max));
          el.hist.append(h("span", { class: inRange ? "" : "off", style: "height:" + Math.max(2, Math.round(100 * bar.c / max)) + "%", title: (bar.y0 === bar.y1 ? bar.y0 : bar.y0 + "–" + bar.y1) + ": " + bar.c }));
        }
        continue;
      }
      const rows = panel.rows.get(facet.id);
      const el = panel.facetEls.get(facet.id);
      const chosen = new Set(sel ? sel.values : []);
      const counts = result.counts[facet.id] || {};
      for (const [value, r] of rows) {
        const c = counts[value] || 0;
        r.count.textContent = fmtInt(c);
        r.input.checked = chosen.has(value);
        const zero = c === 0 && !chosen.has(value);
        r.input.disabled = zero;
        r.label.classList.toggle("zero", zero);
        r.label.setAttribute("aria-disabled", zero ? "true" : "false");
      }
      el.badge.hidden = chosen.size === 0; el.badge.textContent = String(chosen.size);
      if (chosen.size) { activeFacets++; el.details.open = true; }
      if (el.allSwitch) el.allSwitch.checked = !!(sel && sel.all);
      applyFacetOrder(facet);
    }
    if (panel.globalActive) updateGroupTitles();
    const n = activeFacets + (state.text ? 1 : 0);
    const railBadge = $("#rail-badge"); railBadge.hidden = n === 0; railBadge.textContent = String(n);
    $("#clear-all-rail").hidden = n === 0;
  }

  /* --------------------------------------------------------------- chips */

  function renderChips() {
    const host = $("#chips");
    host.textContent = "";
    const chips = [];
    if (state.text) chips.push({ facet: t("Search"), label: "“" + state.text + "”", remove: () => setText("") });
    for (const fid of state.order) {
      const facet = ENGINE.facetById.get(fid); const sel = state.facets[fid];
      if (!facet || !sel) continue;
      if (facet.kind === "range") {
        if (sel.min == null && sel.max == null) continue;
        chips.push({ facet: t(facet.label), label: rangeText(facet, sel), remove: () => setRange(fid, null, null) });
      } else {
        const labels = valueLabel.get(fid) || new Map();
        sel.values.forEach((v, i) => chips.push({ facet: t(facet.label) + (sel.all && sel.values.length > 1 ? " " + (i === 0 ? t("(all of)") : t("(and)")) : ""), label: labels.get(v) || v, remove: () => toggleValue(fid, v, false) }));
      }
    }
    for (const c of chips) {
      host.append(h("span", { class: "chip" }, h("span", { class: "chip-facet", text: c.facet + ":" }), " ", h("span", { text: c.label }),
        h("button", { type: "button", class: "chip-remove", "aria-label": t("Remove filter {facet} {value}", { facet: c.facet, value: c.label }), onclick: c.remove }, "×")));
    }
    if (chips.length) host.append(h("button", { type: "button", class: "link-button", id: "clear-all", text: t("Clear all"), onclick: clearAll }));
  }

  /* ------------------------------------------------------------- results */

  let lastResult = null;

  function update() {
    try {
      const result = ENGINE.query({ text: state.text, facets: state.facets, sort: state.sort, dir: state.dir });
      lastResult = result;
      refreshFacetPanel(result);
      renderChips();
      syncControls(result);
      renderMain(result);
      document.getElementById("app").dataset.state = "ready";
    } catch (err) {
      showError(err);
    }
  }

  function syncControls(result) {
    $("#q").value = state.text;
    $("#sort").value = result.sort;
    const dirBtn = $("#dir");
    dirBtn.setAttribute("aria-label", t("Sort direction: {dir}", { dir: t(result.dir === "asc" ? "ascending" : "descending") }));
    dirBtn.style.transform = result.dir === "asc" ? "rotate(180deg)" : "";
    // relevance without a search text orders by name whatever the arrow says (round 2 check), so the arrow is off there
    const noRelevanceOrder = result.sort === "relevance" && !state.text;
    dirBtn.disabled = noRelevanceOrder;
    dirBtn.title = noRelevanceOrder ? t("Relevance needs a search text; choose another sort to reverse the order") : t("Sort direction");
    for (const b of $$("#view-switch .seg")) b.setAttribute("aria-pressed", String(b.dataset.view === state.view));
    $("#columns-menu").hidden = state.view !== "table" || !!state.record;
    $(".toolbar-right").hidden = !!state.record;
    const summary = $("#summary");
    summary.textContent = "";
    if (state.record) summary.append(t("Record") + " ", h("strong", { text: state.record }));
    else if (state.view === "coverage") summary.append(t("Coverage of") + " ", h("strong", { text: fmtInt(result.total) }), " " + tn(result.total, "record", "records") + (isActive(state) ? " " + t("in the current selection") : ""));
    else summary.append(h("strong", { text: fmtInt(result.total) }), " " + t("of") + " " + fmtInt(RECORDS.length) + " " + tn(RECORDS.length, "record", "records") + ", " + t("sorted by") + " " + t(SORT_LABELS[result.sort]).toLowerCase());
    summary.title = t("Filtered in {ms} ms", { ms: result.ms.toFixed(1) });
    summary.dataset.ms = result.ms.toFixed(2);
  }

  function renderMain(result) {
    const host = $("#results");
    host.textContent = "";
    if (state.record) { renderDetail(host, state.record); return; }
    if (!RECORDS.length) { host.append(emptyCatalogue()); return; }
    if (state.view === "coverage") { renderCoverage(host, result); return; }
    if (!result.total) { host.append(noResults()); return; }
    if (state.view === "table") renderTable(host, result); else renderList(host, result);
    renderPager(host, result);
  }

  function emptyCatalogue() {
    return h("div", { class: "state empty" }, h("h2", { text: t("The catalogue is empty") }),
      h("p", { text: t("No records have been compiled yet. Add records under catalog/<type>/ and rebuild with make build. The filters on the left show every vocabulary value the catalogue can hold.") }));
  }

  function noResults() {
    return h("div", { class: "state no-results" }, h("h2", { text: t("No records match") }),
      h("p", { text: t("Every value that would return nothing is greyed in the filter panel, so you can see which choice excluded the rest. Remove the last filter or start again.") }),
      h("div", { class: "actions" }, h("button", { type: "button", class: "button", text: t("Remove last filter"), onclick: removeLast }), h("button", { type: "button", class: "button primary", text: t("Clear all filters"), onclick: clearAll })));
  }

  function recordHref(id) { const s = cloneState(); s.record = id; return toQuery(s); }

  function openRecord(id, ev) {
    if (ev) ev.preventDefault();
    lastFocusedResult = document.activeElement && document.activeElement.closest ? document.activeElement.closest("[data-id]") : null;
    const s = cloneState(); s.record = id; writeState(s);
    const title = $(".detail-title"); if (title) title.focus();
  }

  function pageSlice(result) {
    const pages = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
    const page = Math.min(state.page, pages);
    return { page, pages, start: (page - 1) * PAGE_SIZE, items: result.indices.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) };
  }

  /** The written label of a facet value (labels.yaml via build.py), else the humanised value. */
  function vlabel(fid, v) { const m = valueLabel.get(fid); return (m && m.get(String(v))) || humanise(String(v)); }
  function typePill(r) { return h("span", { class: "pill type-" + r.type, text: r.type === "data" && r.data_resource_type && r.data_resource_type !== "unknown" ? vlabel("data_resource_type", r.data_resource_type) : vlabel("type", r.type) }); }
  function displayTitle(r) { return r.title_en || r.name; }
  function originalTitle(r) {
    return r.title_en ? h("p", { class: "original-title" }, t("Original title") + ": ", h("span", { dir: "auto", text: r.name })) : null;
  }

  function renderList(host, result) {
    const { items } = pageSlice(result);
    const list = h("ul", { class: "card-list", role: "list" });
    items.forEach((i, k) => {
      const r = RECORDS[i];
      const sectors = (r.sectors || []).map(s => (valueLabel.get("sectors") || new Map()).get(s) || humanise(s.split(".").pop()));
      const a = h("a", { class: "card", href: recordHref(r.id), dataset: { id: r.id }, tabindex: k === 0 ? "0" : "-1", onclick: e => openRecord(r.id, e) },
        h("div", { class: "card-head" }, h("span", { class: "card-title", lang: "en", text: displayTitle(r) }), h("span", { class: "card-provider", text: r.provider })),
        originalTitle(r),
        h("p", { class: "card-desc", text: r.description || "" }),
        h("div", { class: "card-meta" }, typePill(r), sectors.slice(0, 3).map(s => h("span", { class: "pill", text: s })), sectors.length > 3 ? h("span", { class: "pill muted", text: "+" + (sectors.length - 3) }) : null,
          r.licence ? h("span", { class: "pill muted", text: shownLicence(r), title: shownLicence(r) }) : null, r.cost ? h("span", { class: "pill muted", text: vlabel("cost", r.cost) }) : null,
          r.date_verified ? h("span", { class: "pill muted tabular", text: t("Links checked") + " " + r.date_verified, title: t("Date the record's links were last checked; not a check of its content") }) : null,
          r.description_checked ? null : h("span", { class: "pill attention", text: t("Description not checked yet"), title: t("The description has not yet been checked against the provider's own pages") })));
      list.append(h("li", null, a));
    });
    host.append(list);
  }

  /* table columns are the facet fields plus the dates: nothing per field */
  function columnCatalogue() {
    const cols = [{ id: "name", label: t("Name") }, { id: "type", label: t("Type") }, { id: "provider", label: t("Provider") }];
    for (const f of FACETS) if (f.kind !== "text" && !["type", "provider"].includes(f.id) && !f.empty) cols.push({ id: f.id, label: t(f.label), facet: f });
    for (const d of ["date_catalogued", "date_verified", "last_updated"]) cols.push({ id: d, label: t(SORT_LABELS[d] || humanise(d)) });
    return cols;
  }
  const DEFAULT_COLUMNS = ["name", "type", "provider", "sectors", "licence", "cost", "date_verified"];
  function chosenColumns() { const c = load(STORAGE.columns, null); return Array.isArray(c) && c.length ? c : DEFAULT_COLUMNS; }

  function cellValue(r, col, i) {
    if (col.facet) {
      const labels = valueLabel.get(col.id) || new Map();
      let vals = ENGINE.valuesOf(i, col.id);
      if (col.facet.kind === "hierarchy") vals = vals.filter(v => !(col.facet.values || []).some(x => x.value === v && !x.parent) || (r[col.facet.path] || []).includes(v));
      return vals.map(v => labels.get(String(v)) || String(v)).join(", ");
    }
    const v = r[col.id];
    return v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v);
  }

  function renderTable(host, result) {
    const { items } = pageSlice(result);
    const cols = columnCatalogue().filter(c => chosenColumns().includes(c.id));
    const table = h("table", { class: "grid" }, h("thead", null, h("tr", null, cols.map(c => h("th", { scope: "col", text: c.label })))));
    const tbody = h("tbody");
    items.forEach((i, k) => {
      const r = RECORDS[i];
      tbody.append(h("tr", { dataset: { id: r.id } }, cols.map(c => {
        if (c.id === "name") return h("td", { class: "name" }, h("a", { href: recordHref(r.id), lang: "en", dataset: { id: r.id }, tabindex: k === 0 ? "0" : "-1", text: displayTitle(r), onclick: e => openRecord(r.id, e) }), originalTitle(r));
        if (c.id === "type") return h("td", null, typePill(r));
        const cls = /^(date_|last_|year_)/.test(c.id) ? "tabular" : null;
        return h("td", { class: cls, text: cellValue(r, c, i) });
      })));
    });
    table.append(tbody);
    host.append(h("div", { class: "table-wrap" }, table));
    buildColumnsMenu();
  }

  function buildColumnsMenu() {
    const list = $("#columns-menu .menu-list");
    if (list.dataset.built) return;
    list.dataset.built = "1";
    const chosen = new Set(chosenColumns());
    for (const c of columnCatalogue()) {
      const input = h("input", { type: "checkbox", id: "col-" + c.id, checked: chosen.has(c.id) || null });
      input.addEventListener("change", () => { const set = new Set(chosenColumns()); if (input.checked) set.add(c.id); else set.delete(c.id); store(STORAGE.columns, columnCatalogue().map(x => x.id).filter(x => set.has(x))); update(); });
      list.append(h("label", null, input, c.label));
    }
  }

  function renderPager(host, result) {
    const { page, pages, start, items } = pageSlice(result);
    if (pages <= 1) return;
    const go = p => { const s = cloneState(); s.page = p; writeState(s); $("#results").focus(); };
    host.append(h("div", { class: "pager" },
      h("button", { type: "button", class: "button", text: t("Previous"), disabled: page <= 1 || null, onclick: () => go(page - 1) }),
      h("span", { text: fmtInt(start + 1) + "–" + fmtInt(start + items.length) + " " + t("of") + " " + fmtInt(result.total) }),
      h("button", { type: "button", class: "button", text: t("Next"), disabled: page >= pages || null, onclick: () => go(page + 1) })));
  }

  /* -------------------------------------------------------------- detail */

  const GENERIC_LABELS = { crs: "Coordinate reference system" };
  /** The licence text of a record; a stored licence identifier such as "cc_by" or "custom_other" is shown as words, not as the raw slug. */
  function shownLicence(r) {
    const l = r.licence;
    if (typeof l !== "string" || !/^[a-z0-9]+(_[a-z0-9]+)+$/.test(l)) return l;
    // A stored identifier (cc_zero_1, custom_active_acceptance) shows as the vocabulary name it stands for (CC0), else in its own words;
    // never as the bare "Other" of its licence type, which is the filter value and loses what the record says.
    const key = x => String(x).toLowerCase().replace(/zero/g, "0").replace(/[^a-z0-9]/g, "");
    const wanted = key(l).replace(/\d$/, "");
    for (const [value, label] of valueLabel.get("licence_name") || []) if (key(value) === wanted) return label;
    return humanise(l);
  }

  const DETAIL_SKIP = new Set(["id", "type", "name", "title_en", "provider", "description", "homepage", "access_links", "sources", "discovery_routes", "related_ids", "catalogue_membership_evidence", "dedupe_keys", "link_health", "date_verified", "date_catalogued", "description_checked", "runs_on", "validated_on", "hosted_models"]);

  function crossLinks(values) {
    return (values || []).map(v => byId.has(v)
      ? h("a", { class: "pill", href: recordHref(v), text: displayTitle(byId.get(v)), onclick: e => openRecord(v, e) })
      : h("span", { class: "pill missing", title: t("Not in the catalogue"), text: v }));
  }

  function renderDetail(host, id) {
    const r = byId.get(id);
    const back = h("button", { type: "button", class: "button", text: "← " + t("Back to results"), onclick: () => { if (history.state && history.length > 1 && cameFromApp) history.back(); else { const s = cloneState(); s.record = null; writeState(s); } } });
    if (!r) {
      host.append(h("div", { class: "state error" }, h("h2", { text: t("Record not found") }), h("p", { text: t("No record with id “{id}” is in this build of the catalogue.", { id }) }), h("div", { class: "actions" }, back)));
      return;
    }
    const labels = fid => valueLabel.get(fid) || new Map();
    const deadLinks = new Set((r.link_health && r.link_health.dead) || []);
    const box = h("article", { class: "detail", "aria-labelledby": "detail-title" });
    box.append(h("div", { class: "detail-nav" }, back, h("span", { class: "summary", text: r.id })));
    box.append(h("header", null, h("h1", { class: "detail-title", lang: "en", id: "detail-title", tabindex: "-1", text: displayTitle(r) }),
      originalTitle(r),
      h("p", { class: "detail-sub" }, typePill(r), " ", r.provider),
      h("div", { class: "detail-actions", style: "margin-top:12px" },
        r.homepage ? h("a", { class: "button primary", href: r.homepage, target: "_blank", rel: "noopener noreferrer", text: t(r.data_resource_type === "data_catalogue" ? "Open catalogue" : "Open homepage"), title: deadLinks.has(r.homepage) ? t("dead at the last check") : null }) : null,
        r.homepage && deadLinks.has(r.homepage) ? h("span", { class: "pill attention", text: t("Homepage dead at the last check") }) : null,
        h("button", { type: "button", class: "button", text: t("Copy citation"), onclick: () => copyText(citation(r), t("Citation copied")) }),
        h("button", { type: "button", class: "button", text: t("Copy JSON"), onclick: () => copyText(JSON.stringify(r, null, 2), t("Record JSON copied")) }),
        h("button", { type: "button", class: "button", text: t("Copy link"), onclick: () => copyText(location.href, t("Link copied")) }))));
    if (r.catalogue_index_id && (META.catalogues || {})[r.catalogue_index_id]) {
      const members = cloneState(); members.record = null; members.facets = { catalogues: { values: [r.catalogue_index_id], all: false } }; members.order = ["catalogues"];
      box.append(h("a", { class: "button", href: toQuery(members), text: t("View listed members"), onclick: e => { e.preventDefault(); writeState(members); } }));
    }
    if (r.data_resource_type === "data_catalogue") box.append(h("p", { class: "prose", text: t("This links to an external catalogue. Its inventory may include resources outside our scope. A catalogue link does not mean that all its members are listed or checked here.") }));
    box.append(h("section", null, h("h2", { text: t("Description") }), h("p", { class: "prose", text: r.description || "" })));
    box.append(h("section", null, h("h2", { text: t("Access") }), h("div", { class: "link-buttons" },
      (r.access_links || []).map(l => h("a", { class: "button" + (deadLinks.has(l.url) ? " dead" : ""), href: l.url, target: "_blank", rel: "noopener noreferrer", title: l.note || null }, l.label || l.url, " ", h("span", { class: "kind", text: l.kind || "" }), deadLinks.has(l.url) ? h("span", { class: "pill attention", text: t("dead at the last check"), title: t("The last link check found this address gone (404 or 410); it is kept so the record can be repaired") }) : null)))));

    const grid = h("div", { class: "detail-grid" });
    const facts = h("dl", { class: "kv" });
    const shownLabels = new Set();
    const addFact = (label, node) => { if (node == null || node === "" || (Array.isArray(node) && !node.length)) return; shownLabels.add(label); facts.append(h("dt", { text: label }), h("dd", null, node)); };
    const pills = (fid, values) => (values || []).map(v => { const l = labels(fid).get(String(v)) || (typeof v === "string" ? humanise(v) : String(v)); const s = cloneState(); s.record = null; s.facets = { [fid]: { values: [String(v)], all: false } }; s.order = [fid]; return h("a", { class: "pill", href: toQuery(s), text: l, onclick: e => { e.preventDefault(); writeState(s); } }); });
    addFact(t("Sectors"), pills("sectors", r.sectors));
    for (const f of FACETS) {
      if (f.kind === "text" || f.kind === "range" || ["type", "provider", "sectors", "discovery_route", "link_health", "access_link_kinds", "content_check"].includes(f.id)) continue; // content_check: the Provenance block shows the date
      const key = f.path.split(".")[0].replace("[]", "");
      const raw = r[key];
      if (raw == null || (Array.isArray(raw) && !raw.length)) continue;
      addFact(t(f.label), f.transform === "bool" ? (raw ? t("Yes") : t("No")) : pills(f.id, Array.isArray(raw) ? raw : [raw]));
    }
    const span = r.temporal_coverage_years;
    if (span && span.start != null) addFact(t("Years covered"), span.start + "–" + (span.end == null ? t("ongoing") : span.end));
    if (r.last_updated) addFact(t("Last updated"), String(r.last_updated)); // the provider's own update date, also a sort order and a table column
    if (typeof r.size_bytes === "number") addFact(t("Size"), fmtQuantity(r.size_bytes, "bytes"));
    if (typeof r.spatial_resolution_m === "number") addFact(t("Resolution"), fmtQuantity(r.spatial_resolution_m, "metres"));
    for (const [k, v] of Object.entries(r)) {
      if (DETAIL_SKIP.has(k) || FACETS.some(f => f.path && f.path.split(".")[0].replace("[]", "") === k)) continue;
      // the stored text of a field that also has a controlled filter (size, spatial resolution) must not repeat that fact's label
      const name = t(GENERIC_LABELS[k] || humanise(k));
      addFact(shownLabels.has(name) ? name + " (" + t("as stated") + ")" : name, k === "licence" ? shownLicence(r) : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v));
    }
    grid.append(h("section", null, h("h2", { text: t("Facts") }), facts));

    const prov = h("section", null, h("h2", { text: t("Provenance and verification") }));
    const pv = h("dl", { class: "kv" });
    pv.append(h("dt", { text: t("Catalogued") }), h("dd", { class: "tabular", text: r.date_catalogued || "" }));
    pv.append(h("dt", { text: t("Links checked") }), h("dd", { class: "tabular", text: r.date_verified || "" }));
    pv.append(h("dt", { text: t("Description checked") }), h("dd", { class: "tabular", text: r.description_checked || t("Not checked yet") }));
    pv.append(h("dt", { text: t("Link health") }), h("dd", null, linkHealthText(r)));
    prov.append(pv);
    prov.append(h("h2", { text: t("Sources consulted"), style: "margin-top:16px" }), h("ul", { class: "provenance" }, (r.sources || []).map(s => h("li", null, h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.url }), h("span", { class: "when", text: t("accessed") + " " + (s.accessed || "") }), s.note ? h("span", { class: "summary", text: s.note }) : null))));
    prov.append(h("h2", { text: t("Discovery routes"), style: "margin-top:16px" }), h("ul", { class: "provenance" }, (r.discovery_routes || []).map(d => h("li", null, h("strong", { text: labels("discovery_route").get(d.route) || d.route }), d.source ? h("span", { text: t("via") + " " + d.source }) : null, d.query ? h("span", { class: "summary", text: "“" + d.query + "”" }) : null, h("span", { class: "when", text: d.date || "" })))));
    grid.append(prov);
    box.append(grid);

    const links = [[t("Related records"), r.related_ids], [t("Runs on"), r.runs_on], [t("Validated on"), r.validated_on], [t("Hosted models"), r.hosted_models]].filter(([, v]) => v && v.length);
    if (links.length) {
      const sec = h("section", null, h("h2", { text: t("Cross-links") }));
      for (const [label, values] of links) sec.append(h("div", { style: "margin-bottom:8px" }, h("div", { class: "summary", text: label }), h("div", { class: "related" }, crossLinks(values))));
      box.append(sec);
    }
    box.append(h("details", null, h("summary", { class: "link-button", text: t("Record as JSON") }), h("pre", { class: "json", text: JSON.stringify(r, null, 2) })));
    host.append(box);
  }

  /** Plain statement of the last link check: dead and unverified links are named, never folded into "checked". */
  function linkHealthText(r) {
    const lh = r.link_health;
    if (!lh || !lh.checked) return t("Links not checked yet");
    const total = new Set([r.homepage, ...(r.access_links || []).map(l => l.url)].filter(Boolean)).size;
    const dead = (lh.dead || []).length, unverified = (lh.unverified || []).length;
    const parts = [];
    if (dead) parts.push(tn(dead, "{n} dead link", "{n} dead links"));
    if (unverified) parts.push(tn(unverified, "{n} link not confirmed", "{n} links not confirmed"));
    if (!parts.length) parts.push(tn(total, "All {n} link alive", "All {n} links alive"));
    return parts.join(", ") + " " + t("at the check of {date}", { date: lh.checked });
  }

  function citation(r) {
    const when = META.built || new Date().toISOString().slice(0, 10);
    return r.provider + ". " + r.name + ". " + (r.homepage || "") + " (record " + r.id + ", Data catalogue for critical infrastructure research, catalogue build " + when + ", verified " + (r.date_verified || "n/a") + ")";
  }

  function copyText(text, done) {
    const fallback = () => { const ta = h("textarea", { style: "position:fixed;opacity:0", text }); document.body.append(ta); ta.select(); try { document.execCommand("copy"); toast(done); } catch (e) { toast(t("Copy is not available here")); } ta.remove(); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => toast(done), fallback); else fallback();
  }

  /* ------------------------------------------------------------ coverage */

  function renderCoverage(host, result) {
    const wrap = h("div", { class: "coverage" });
    const counts = META.counts || {};
    wrap.append(h("div", { class: "stat-row" },
      h("div", { class: "stat" }, h("div", { class: "stat-label", text: t("In selection") }), h("div", { class: "stat-value", text: fmtInt(result.total) })),
      (META.record_types || ["data", "model", "platform", "case_study"]).map(ty => { const n = result.indices.filter(i => RECORDS[i].type === ty).length; return h("div", { class: "stat" }, h("div", { class: "stat-label", text: t("{type} records", { type: vlabel("type", ty) }) }), h("div", { class: "stat-value", text: fmtInt(n) + (isActive(state) ? " / " + fmtInt((counts.by_type || {})[ty] || 0) : "") })); })));
    wrap.append(h("p", { class: "coverage-note", text: t("coverage.intro") }));


    const tally = fid => { const m = new Map(); for (const i of result.indices) for (const v of new Set(ENGINE.valuesOf(i, fid))) m.set(v, (m.get(v) || 0) + 1); return m; };
    const grid = h("div", { class: "coverage-grid" });
    grid.append(barChart(t("Records per sector"), t("Grouped by sector group; a record can count in several sectors."), "sectors", tally("sectors"), META.sector_groups || {}));
    grid.append(barChart(t("Data records per family"), t("Grouped by family group; only data records carry a family."), "data_family", tally("data_family"), META.family_groups || {}));
    wrap.append(grid);
    host.append(wrap);
  }

  function barChart(title, sub, fid, tally, groupLabels) {
    const facet = ENGINE.facetById.get(fid);
    const values = facet ? facet.values : [];
    const max = Math.max(1, ...values.filter(v => v.parent).map(v => tally.get(v.value) || 0));
    const list = h("ul", { class: "bars", role: "list" });
    for (const parent of values.filter(v => !v.parent)) {
      const kids = values.filter(v => v.parent === parent.value);
      if (!kids.length) continue;
      list.append(h("li", { class: "group-title", text: (groupLabels[parent.value] || parent.label) + " · " + fmtInt(tally.get(parent.value) || 0) }));
      for (const kid of kids) {
        const n = tally.get(kid.value) || 0;
        const s = cloneState(); s.view = "list"; s.record = null; s.page = 1; s.facets = Object.assign({}, s.facets, { [fid]: { values: [kid.value], all: false } }); if (!s.order.includes(fid)) s.order.push(fid);
        list.append(h("li", { class: "bar-row" },
          h("span", { class: "bar-label" }, h("a", { href: toQuery(s), text: kid.label, title: kid.note || null, onclick: e => { e.preventDefault(); writeState(s); } })),
          h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: "width:" + (100 * n / max).toFixed(1) + "%" })),
          h("span", { class: "bar-value", text: fmtInt(n) })));
      }
    }
    return h("section", { class: "viz" }, h("h2", { text: title }), h("p", { class: "viz-sub", text: sub }), list);
  }

  /* -------------------------------------------------------------- export */

  function describeFilters() {
    const out = [];
    if (state.text) out.push({ facet: "q", label: "Search", values: [state.text] });
    for (const fid of state.order) {
      const facet = ENGINE.facetById.get(fid); const sel = state.facets[fid];
      if (!facet || !sel) continue;
      if (facet.kind === "range") out.push({ facet: fid, label: facet.label, min: sel.min, max: sel.max });
      else out.push({ facet: fid, label: facet.label, values: sel.values, match: sel.all ? "all" : "any" });
    }
    return out;
  }

  function download(name, text, type) {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: name, style: "display:none" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function exportJSON() {
    if (!lastResult) return;
    const payload = { exported: new Date().toISOString(), catalogue_built: META.built, url: location.href, filters: describeFilters(), sort: lastResult.sort, dir: lastResult.dir, total: lastResult.total, records: lastResult.indices.map(i => RECORDS[i]) };
    download("catalogue-export.json", JSON.stringify(payload, null, 2), "application/json");
    toast(t("JSON export of {n} started", { n: fmtInt(lastResult.total) + " " + tn(lastResult.total, "record", "records") }));
  }

  function exportCSV() {
    if (!lastResult) return;
    const cols = ["id", "type", "title_en", "name", "provider", "homepage", "licence", "cost", "access_restrictions", "geographic_scope", "maturity", "date_catalogued", "date_verified", "last_updated"];
    for (const f of FACETS) if (f.kind !== "text" && f.kind !== "range" && !f.empty && f.path && !f.path.includes("[]") && !cols.includes(f.path)) cols.push(f.path);
    const esc = v => { const s = v == null ? "" : Array.isArray(v) ? v.join("; ") : typeof v === "object" ? JSON.stringify(v) : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const lines = ["# Data catalogue for critical infrastructure research export, " + new Date().toISOString() + ", catalogue build " + META.built,
      "# filters: " + (describeFilters().length ? JSON.stringify(describeFilters()) : "none") + "; sort: " + lastResult.sort + " " + lastResult.dir + "; url: " + location.href,
      cols.map(esc).join(",")];
    for (const i of lastResult.indices) lines.push(cols.map(c => esc(RECORDS[i][c])).join(","));
    download("catalogue-export.csv", lines.join("\r\n") + "\r\n", "text/csv");
    toast(t("CSV export of {n} started", { n: fmtInt(lastResult.total) + " " + tn(lastResult.total, "record", "records") }));
  }

  /* --------------------------------------------------------------- theme */

  function applyTheme(mode) {
    const root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode); else root.removeAttribute("data-theme");
    const btn = $("#theme-toggle");
    btn.setAttribute("aria-label", t("Appearance: {mode}", { mode: t(mode || "system") }));
    btn.dataset.mode = mode || "system";
  }
  function cycleTheme() {
    const order = ["system", "light", "dark"];
    const cur = load(STORAGE.theme, "system");
    const next = order[(order.indexOf(cur) + 1) % order.length];
    store(STORAGE.theme, next === "system" ? null : next);
    applyTheme(next === "system" ? null : next);
    toast(t("Appearance: {mode}", { mode: t(next) }));
  }

  /* ------------------------------------------------------- toast and error */

  let toastTimer = null;
  function toast(message, undo) {
    const el = $("#toast");
    el.textContent = "";
    el.append(message);
    if (undo) el.append(h("button", { type: "button", class: "link-button", text: undo.label, onclick: () => { el.hidden = true; undo.action(); } }));
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, undo ? 6000 : 2500);
  }

  function showError(err, loading) {
    console.error(err);
    const host = $("#results");
    host.textContent = "";
    host.append(h("div", { class: "state error" }, h("h2", { text: t("Something went wrong") }),
      h("p", { text: loading ? t("The catalogue could not be loaded completely. Check the connection and reload the page to see all records.") : t("The dashboard hit an error while filtering. Reloading the page restores it; if the problem stays, the address may hold an unsupported filter.") }),
      h("p", { class: "summary", text: String(err && err.message || err) }),
      h("div", { class: "actions" }, h("button", { type: "button", class: "button primary", text: t("Reload"), onclick: () => location.reload() }), h("button", { type: "button", class: "button", text: t("Clear filters"), onclick: () => { location.search = ""; } }))));
    document.getElementById("app").dataset.state = "error";
  }

  /* ------------------------------------------------------------ keyboard */

  let lastFocusedResult = null;
  let cameFromApp = false;

  function resultLinks() { return $$("#results [data-id]"); }

  function onKey(e) {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable;
    if (e.key === "/" && !typing) { e.preventDefault(); $("#q").focus(); $("#q").select(); return; }
    // the export menu follows the menu pattern: arrows move between its items, Esc closes it and returns to its button
    const exportList = $("#export-menu .menu-list");
    if (exportList && !exportList.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Home" || e.key === "End" || e.key === "Escape")) {
      const items = $$("[role=menuitem]", exportList);
      const cur = items.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); toggleMenu("#export-menu", false); $("#export-toggle").focus(); return; }
      e.preventDefault();
      const next = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : cur < 0 ? (e.key === "ArrowDown" ? 0 : items.length - 1) : (cur + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next].focus();
      return;
    }
    if (e.key === "Escape") {
      if (e.target.id === "q" && $("#q").value) { setText(""); return; }
      const help = $("#help-panel");
      if (help && !help.hidden && (help.contains(e.target) || e.target.id === "help-toggle")) { help.hidden = true; $("#help-toggle").setAttribute("aria-expanded", "false"); $("#help-toggle").focus(); return; }
      if (tag === "input" && e.target.type === "search" && e.target.value && e.target.closest("#rail")) { e.target.value = ""; e.target.dispatchEvent(new Event("input")); return; } // first Esc clears a filter search, the next leaves it
      if (typing && !(SHEET_WIDTH.matches && $("#rail").classList.contains("open") && e.target.closest("#rail"))) { e.target.blur(); return; }
      if ($("#rail").classList.contains("open")) { toggleRail(false); return; }
      if (state.record) { const s = cloneState(); s.record = null; writeState(s); restoreResultFocus(); return; }
      if (!$("#export-menu .menu-list").hidden) { toggleMenu("#export-menu", false); return; }
      return;
    }
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !typing) {
      const links = resultLinks();
      if (!links.length) return;
      const cur = links.indexOf(document.activeElement);
      let next = cur < 0 ? 0 : cur + (e.key === "ArrowDown" ? 1 : -1);
      if (next < 0 || next >= links.length) return;
      e.preventDefault();
      links.forEach((l, k) => l.tabIndex = k === next ? 0 : -1);
      links[next].focus();
      links[next].scrollIntoView({ block: "nearest" });
    }
  }

  function restoreResultFocus() {
    const id = lastFocusedResult && lastFocusedResult.dataset ? lastFocusedResult.dataset.id : null;
    const target = id ? $('#results [data-id="' + CSS.escape(id) + '"]') : resultLinks()[0];
    if (target) target.focus();
  }

  // while the filter sheet covers the page (900 px and below) the content behind it must not take keyboard focus or be read out
  const SHEET_WIDTH = window.matchMedia("(max-width: 900px)");
  function setBehindSheet(inert) { for (const el of $$(".skip-link, .topbar, .main, .foot")) el.inert = inert; }
  SHEET_WIDTH.addEventListener("change", () => { if (!SHEET_WIDTH.matches) setBehindSheet(false); else if ($("#rail").classList.contains("open")) setBehindSheet(true); });

  function toggleRail(open) {
    const rail = $("#rail");
    rail.classList.toggle("open", open);
    setBehindSheet(open && SHEET_WIDTH.matches);
    $("#rail-open").setAttribute("aria-expanded", String(open));
    // the sheet becomes visible on the next frame (its visibility is transitioned), and an element cannot take focus before that
    if (open) { const first = $("#filter-search") || $("#facets input, #facets button, #facets summary"); setTimeout(() => { if (first) first.focus(); }, 40); } else $("#rail-open").focus();
  }

  function toggleMenu(sel, open) {
    const menu = $(sel); const list = $(".menu-list", menu); const btn = $("[aria-haspopup]", menu);
    const next = open == null ? list.hidden : open;
    list.hidden = !next; btn.setAttribute("aria-expanded", String(next));
  }

  /* ---------------------------------------------------------------- boot */

  let ENGINE_NORMALISE = s => String(s).toLowerCase();

  /* Vocabulary value names follow the interface language (the language is chosen before load; a change reloads). The search index
     is built first, so English names still match. Countries and languages take the browser's own names for them. */
  function translateVocabulary() {
    if (I18N.lang === "en") return;
    const display = type => { try { return new Intl.DisplayNames([I18N.lang], { type, fallback: "none" }); } catch (e) { return null; } };
    const own = { countries: display("region"), languages: display("language") };
    for (const f of FACETS) {
      for (const v of f.values || []) {
        let name = null;
        if (own[f.id]) { try { name = own[f.id].of(f.id === "countries" ? String(v.value).toUpperCase() : String(v.value)); } catch (e) { name = null; } }
        v.label = name && name !== v.value ? name : t(v.label);
      }
    }
    for (const key of ["sector_groups", "family_groups"]) for (const g of Object.keys(META[key] || {})) META[key][g] = t(META[key][g]);
  }

  function boot(raw) {
    DATA = JSON.parse(raw);
    FACETS = DATA.facets; RECORDS = DATA.records; META = DATA.meta || {};
    for (const r of RECORDS) byId.set(r.id, r);
    ENGINE = CatalogueEngine.createEngine(RECORDS, FACETS, { textFields: META.text_fields });
    ENGINE_NORMALISE = CatalogueEngine.normalise;
    translateVocabulary();
    I18N.apply();
    document.title = t("Data catalogue for critical infrastructure research");
    setupLanguage();
    renderStatus();
    applyTheme(load(STORAGE.theme, null));
    buildFacetPanel();
    const filterSearch = $("#filter-search");
    if (filterSearch) filterSearch.addEventListener("input", panel.totalValues > DEBOUNCE_ABOVE ? debounced(applyGlobalSearch, 80) : applyGlobalSearch);
    state = readState();
    try { history.replaceState({ s: state }, "", toQuery(state)); } catch (e) { /* ignore */ }

    // controls
    const q = $("#q");
    let debounce = null;
    q.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => { if (q.value !== state.text) setText(q.value); }, 120); });
    $("#search-form").addEventListener("submit", e => { e.preventDefault(); clearTimeout(debounce); setText(q.value); });
    $("#sort").addEventListener("change", e => { const s = cloneState(); s.sort = e.target.value; s.dir = null; s.page = 1; writeState(s); });
    $("#dir").addEventListener("click", () => { const s = cloneState(); s.dir = (lastResult && lastResult.dir) === "asc" ? "desc" : "asc"; s.page = 1; writeState(s); });
    for (const b of $$("#view-switch .seg")) b.addEventListener("click", () => { const s = cloneState(); s.view = b.dataset.view; s.record = null; s.page = 1; writeState(s); });
    $("#theme-toggle").addEventListener("click", cycleTheme);
    $("#help-toggle").addEventListener("click", () => { const p = $("#help-panel"); p.hidden = !p.hidden; $("#help-toggle").setAttribute("aria-expanded", String(!p.hidden)); });
    $("#help-dismiss").addEventListener("click", () => { $("#help-panel").hidden = true; $("#help-toggle").setAttribute("aria-expanded", "false"); store(STORAGE.help, true); });
    $("#clear-all-rail").addEventListener("click", clearAll);
    $("#rail-open").addEventListener("click", () => toggleRail(true));
    $("#rail-close").addEventListener("click", () => toggleRail(false));
    $("#export-toggle").addEventListener("click", () => toggleMenu("#export-menu"));
    $("#export-csv").addEventListener("click", () => { toggleMenu("#export-menu", false); exportCSV(); });
    $("#export-json").addEventListener("click", () => { toggleMenu("#export-menu", false); exportJSON(); });
    $("#columns-toggle").addEventListener("click", () => toggleMenu("#columns-menu"));
    document.addEventListener("click", e => { for (const sel of ["#export-menu", "#columns-menu"]) { const m = $(sel); if (m && !m.contains(e.target)) toggleMenu(sel, false); } });
    $("#brand").addEventListener("click", e => { e.preventDefault(); writeState(emptyState()); });
    document.addEventListener("keydown", onKey);
    window.addEventListener("popstate", () => { state = readState(); update(); if (!state.record) restoreResultFocus(); else { const t = $(".detail-title"); if (t) t.focus(); } });
    document.addEventListener("click", () => { cameFromApp = true; }, { capture: true, once: true });

    // first-visit orientation is decided by the inline script in the template before first paint; nothing to do here
    update();
    scheduleTextIndex();
    window.__catalogue = { engine: ENGINE, state: () => state, result: () => lastResult };
  }

  /** Interface language: the page is rebuilt from the same address, so filters, view and scroll target survive. */
  function setupLanguage() {
    const sel = $("#lang");
    if (!sel) return;
    for (const [code, name] of Object.entries(I18N.LANGUAGES)) sel.append(h("option", { value: code, text: name, lang: code }));
    sel.value = I18N.lang;
    sel.addEventListener("change", () => { I18N.set(sel.value, true); location.reload(); });
  }

  /** Show the number of records in the current dashboard. */
  function renderStatus() {
    const el = $("#foot-status");
    if (!el) return;
    const n = RECORDS.length;
    if (!n) { el.textContent = ""; return; }
    el.textContent = t("catalogue.status", { n: fmtInt(n) });
  }

  /** Build the search index in small slices after the first paint (audit 2026-09-26: building it before the
   *  first render held the page for about 3 s at 20,000 records). A search typed before it is complete
   *  finishes it at once, inside the engine, so results never depend on timing. */
  function scheduleTextIndex() {
    const app = document.getElementById("app");
    const step = () => {
      if (ENGINE.buildTextIndex(12)) { app.dataset.textIndex = "ready"; return; }
      app.dataset.textIndex = "building";
      setTimeout(step, 0);
    };
    step();
  }

  // The data sits inline, or in parts next to the page (build.py --data-file) for hosts with a size limit.
  const dataEl = document.getElementById("catalog-data");
  const dataSrc = (dataEl.getAttribute("data-src") || "").split(" ").filter(Boolean);
  if (dataSrc.length && !dataEl.textContent.trim()) {
    // the real catalogue is 29 parts and over 200 MB: say how far the load has got instead of one unchanging line
    const wait = document.querySelector("#loading-state p");
    let fetched = 0;
    const progress = () => { if (wait) wait.textContent = I18N.t("Loading the catalogue… part {done} of {n}", { done: fetched, n: dataSrc.length }); };
    progress();
    Promise.all(dataSrc.map(src => fetch(src).then(r => { if (!r.ok) throw new Error("could not load " + src + " (" + r.status + ")"); return r.text(); }).then(text => { fetched++; progress(); return text; })))
      .then(parts => { if (wait) wait.textContent = I18N.t("Loading the catalogue…"); boot(parts.join("")); }).catch(err => showError(err, true));
  } else {
    try { boot(dataEl.textContent); } catch (err) { showError(err); }
  }
})();
