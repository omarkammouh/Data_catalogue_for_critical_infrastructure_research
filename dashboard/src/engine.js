/*
 * Catalogue filter engine.
 *
 * Pure data code, no DOM: the same file runs in the browser (as the global
 * `CatalogueEngine`) and under Node (as a CommonJS module) so the property test
 * can compare it with the Python reference over identical inputs.
 *
 * Semantics, stated once so that the reference implementation and the paper
 * can cite them:
 *
 *  - A record's values for a facet are read with the facet's `path`
 *    (`a.b` nests, `a[]` iterates) and `transform` (`year`, `bool`,
 *    `link_status`; since 2026-09-26 also `year_span`, every year of a
 *    `{start, end}` period with an open end closed at the facet's `open_end`;
 *    `number`, a finite number as it is; `presence`, "checked" when the field
 *    holds a value, else "not checked"), exactly as build.py does when it
 *    counts them.
 *  - Hierarchy facets expand each value to its parent, and a bare parent value
 *    to all of its children, before indexing.
 *  - Within one facet, selected values combine with OR ("any"); when the facet's
 *    `all` flag is set they combine with AND ("match all").
 *  - Across facets the selections combine with AND; the free-text query is one
 *    more AND term.
 *  - A range facet selects records with at least one value in the inclusive
 *    interval [min, max]; a record with no value never matches an active range.
 *  - Live counts: for a facet in "any" mode, the count of a value is the number
 *    of records that match every OTHER active constraint and carry the value
 *    (what selecting it would yield). In "match all" mode the facet's own
 *    selection is included, so the count is what adding the value would leave.
 *  - Free text: the query is normalised (NFKD, accents stripped, lower case,
 *    punctuation to spaces) and split into tokens. Every token must match. A
 *    token matches a record when the record's text contains it as a substring,
 *    or when at least 60 % of the token's padded trigrams occur in the record.
 *    The token score is that fraction (1 for a substring hit); the record score
 *    is the mean token score, plus 0.5 when the record name contains the whole
 *    query (plus 0.25 when it contains it as whole words and a further 0.5 when
 *    the name is the query), plus 0.25 times the share of query tokens that match the record's
 *    name by the same substring-or-60 %-trigram rule (so a misspelt name word
 *    outranks the same word in another record's description; audit
 *    2026-09-24). Relevance sort is by score, then name, then id.
 *  - Sorting compares normalised strings by code point (never locale
 *    collation), so results are identical in every browser and in Python.
 *    Records without a sort value come last in either direction; ties break
 *    by id.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.CatalogueEngine = factory(); }
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const TEXT_THRESHOLD = 0.6;
  const NAME_BONUS = 0.5;
  const NAME_TOKEN_BONUS = 0.25;
  const NAME_WORD_BONUS = 0.25;  // the query is a whole word (or run of words) of the name, not a piece of a longer word ("tops" in "Stops")
  const NAME_EXACT_BONUS = 0.5;  // the name is the query (round 2 check: a record searched by its own name ranked 117th behind names that merely contain the letters)
  const ID_EXACT_BONUS = 1;      // the query is the record's id (siblings of one dataset share every other token: a record searched by its own id ranked 9th)
  const MAX_SPAN = 1000; // a year_span longer than this is treated as a data error and ignored (historical catalogues reach back to about 1100)

  /* ---------------------------------------------------------------- text */

  const ASCII_ONLY = /^[\x00-\x7f]*$/;
  function normalise(text) {
    const str = String(text == null ? "" : text);
    // plain ASCII (most of the catalogue): same result as the full path below, several times faster (round 2 check: the text index took 21 s)
    if (ASCII_ONLY.test(str)) return str.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    return str
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function tokens(text) {
    const n = normalise(text);
    return n ? n.split(" ") : [];
  }

  function trigrams(token) {
    const padded = " " + token + " ";
    const out = [];
    for (let i = 0; i + 3 <= padded.length; i++) out.push(padded.slice(i, i + 3));
    return out;
  }

  /* ---------------------------------------------------------- extraction */

  function walkPath(obj, path) {
    let current = [obj];
    if (!path) return current;
    for (const part of path.split(".")) {
      const iterate = part.endsWith("[]");
      const key = iterate ? part.slice(0, -2) : part;
      const next = [];
      for (const item of current) {
        if (item == null || typeof item !== "object" || Array.isArray(item) || !(key in item)) continue;
        const value = item[key];
        if (iterate) { if (Array.isArray(value)) next.push(...value); }
        else next.push(value);
      }
      current = next;
    }
    return current;
  }

  /** Link-health class of a record (same rule in build.py and the property test): dead links first, then unverified, then all alive. */
  function linkStatus(health) {
    if (!health || !health.checked) return "not checked";
    if ((health.dead || []).length) return "dead links";
    if ((health.unverified || []).length) return "some links unverified";
    return "all links alive";
  }

  function yearOf(v) {
    if (typeof v === "number" && Number.isInteger(v)) return v;
    const m = /^\s*(\d{4})/.exec(v == null ? "" : String(v));
    return m ? parseInt(m[1], 10) : null;
  }

  function applyTransform(values, transform, facet) {
    const out = [];
    for (const value of values) {
      if (transform === "year_span") {
        // {start, end}: every year from start to end; end null means "still running" and closes at the facet's open_end (the build year)
        if (!value || typeof value !== "object" || Array.isArray(value)) continue;
        const a = yearOf(value.start);
        const b = value.end == null ? (facet && facet.open_end != null ? facet.open_end : a) : yearOf(value.end);
        if (a == null || b == null || b < a || b - a > MAX_SPAN) continue;
        for (let y = a; y <= b; y++) out.push(y);
      } else if (transform === "number") {
        if (typeof value === "number" && Number.isFinite(value)) out.push(value);
      } else if (transform === "presence") {
        if (value != null && value !== "") out.push("checked");
      } else if (transform === "year") {
        if (value == null || value === "") continue;
        const m = /^\s*(\d{4})/.exec(String(value));
        if (m) out.push(parseInt(m[1], 10));
      } else if (transform === "bool") {
        if (typeof value === "boolean") out.push(value ? "yes" : "no");
      } else if (transform === "link_status") {
        if (value && typeof value === "object" && !Array.isArray(value)) out.push(linkStatus(value));
      } else {
        const items = Array.isArray(value) ? value : [value];
        for (const item of items) {
          if (typeof item === "boolean") out.push(item ? "yes" : "no");
          else if ((typeof item === "string" || typeof item === "number") && String(item) !== "") out.push(String(item));
        }
      }
    }
    if (transform === "link_status" && !out.length) out.push("not checked"); // a record without link_health was never checked
    if (transform === "presence" && !out.length) out.push("not checked");
    return out;
  }

  function extract(record, facet) {
    return applyTransform(walkPath(record, facet.path), facet.transform, facet);
  }

  function expandHierarchy(values, facet) {
    const parents = facet._parents, children = facet._children;
    const set = new Set();
    for (const v of values) {
      set.add(v);
      if (parents.has(v)) set.add(parents.get(v));
      if (children.has(v)) for (const c of children.get(v)) set.add(c);
    }
    return Array.from(set);
  }

  function recordText(record, fields) {
    const parts = [];
    for (const f of fields) {
      const v = record[f];
      if (Array.isArray(v)) parts.push(v.join(" "));
      else if (v != null) parts.push(String(v));
    }
    return normalise(parts.join(" "));
  }

  /* ------------------------------------------------------------- sorting */

  function sortKey(record, field) {
    if (field === "name") return normalise(record.title_en || record.name);
    if (field === "provider") return normalise(record.provider);
    const v = record[field];
    return v == null || v === "" ? null : String(v);
  }

  const SORTS = {
    relevance: { defaultDir: "desc" },
    name: { field: "name", defaultDir: "asc" },
    provider: { field: "provider", defaultDir: "asc" },
    date_catalogued: { field: "date_catalogued", defaultDir: "desc" },
    date_verified: { field: "date_verified", defaultDir: "desc" },
    last_updated: { field: "last_updated", defaultDir: "desc" },
  };

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  /* -------------------------------------------------------------- engine */

  function createEngine(records, facets, options) {
    const opts = options || {};
    const n = records.length;
    const textFields = opts.textFields || ["title_en", "name", "provider", "description", "tags", "id", "notes", "regions"];
    const facetById = new Map();
    const index = new Map();      // facetId -> Map(value -> Int32Array postings)
    const rangeValues = new Map(); // facetId -> Array<number[]> per record
    const texts = new Array(n);
    const names = new Array(n);
    const titles = new Array(n);
    const ids = new Array(n);
    const sortKeyCache = new Map(); // field -> Array(n) of key or null

    for (const facet of facets) {
      facetById.set(facet.id, facet);
      if (facet.kind === "hierarchy") {
        facet._parents = new Map();
        facet._children = new Map();
        for (const v of facet.values || []) {
          if (v.parent) {
            facet._parents.set(v.value, v.parent);
            if (!facet._children.has(v.parent)) facet._children.set(v.parent, []);
            facet._children.get(v.parent).push(v.value);
          }
        }
      }
    }

    // build postings
    const tmp = new Map(); // facetId -> Map(value -> number[])
    for (const facet of facets) {
      if (facet.kind === "text") continue;
      if (facet.kind === "range") { rangeValues.set(facet.id, new Array(n)); continue; }
      tmp.set(facet.id, new Map());
    }
    for (let i = 0; i < n; i++) {
      const r = records[i];
      ids[i] = String(r.id);
      names[i] = normalise(r.name);
      titles[i] = normalise(r.title_en || r.name);
      for (const facet of facets) {
        if (facet.kind === "text") continue;
        let values = extract(r, facet);
        if (facet.kind === "range") { rangeValues.get(facet.id)[i] = values; continue; }
        if (facet.kind === "hierarchy") values = expandHierarchy(values, facet);
        const m = tmp.get(facet.id);
        for (const v of new Set(values)) {
          if (!m.has(v)) m.set(v, []);
          m.get(v).push(i);
        }
      }
    }
    for (const [fid, m] of tmp) {
      const packed = new Map();
      for (const [v, list] of m) packed.set(v, Int32Array.from(list));
      index.set(fid, packed);
    }

    /* The text index (record texts, name trigrams, trigram postings) is built
     * separately and incrementally (audit 2026-09-26): at 20,000 records it took
     * about 3 s and held the first paint of the page. The page now renders from
     * the facet index at once and builds the text index in slices while idle
     * (`buildTextIndex(budgetMs)`); a text query before it is complete finishes
     * it synchronously (`ensureTextIndex`), so results never depend on timing.
     * Trigrams are interned to integer ids and de-duplicated per record with a
     * last-seen array instead of a Set per record. */
    /* Trigram table (round 2 check, 2026-10-01): at 64,000 records the text index took 21 s in the browser, most of it
     * slicing a string per trigram and growing one array per trigram. Trigrams are now read straight from the character
     * codes (a window of three UTF-16 units of the text; a window whose middle unit is a space spans two words and is
     * skipped, which gives exactly the per-word padded trigrams of the earlier version), interned in an open-addressing
     * table, collected as (trigram, record) pairs and packed into one Int32Array per index at the end. */
    let tCap = 1 << 18, tK1 = new Int32Array(tCap), tK2 = new Int32Array(tCap), tId = new Int32Array(tCap).fill(-1);
    let triCount = 0;
    const triLast = [];            // id -> last record added (de-duplication)
    let pT = new Int32Array(1 << 20), pR = new Int32Array(1 << 20), pN = 0; // (trigram id, record) pairs in record order
    let postStart = null, postData = null; // CSR postings once the index is complete
    let textBuilt = 0;             // records indexed so far
    let textDone = n === 0;

    function triSlot(k1, k2) {
      let h = Math.imul(k1, -1640531535) ^ Math.imul(k2 + 0x2545F491, 0x85ebca6b);
      h ^= h >>> 15;
      return h & (tCap - 1);
    }
    function triGrow() {
      const oK1 = tK1, oK2 = tK2, oId = tId, oCap = tCap;
      tCap *= 2; tK1 = new Int32Array(tCap); tK2 = new Int32Array(tCap); tId = new Int32Array(tCap).fill(-1);
      for (let j = 0; j < oCap; j++) {
        if (oId[j] < 0) continue;
        let s = triSlot(oK1[j], oK2[j]);
        while (tId[s] >= 0) s = (s + 1) & (tCap - 1);
        tK1[s] = oK1[j]; tK2[s] = oK2[j]; tId[s] = oId[j];
      }
    }
    /** Id of the trigram (c0 c1 c2), creating it when `create`; -1 when absent. */
    function triFind(c0, c1, c2, create) {
      const k1 = (c0 << 16) | c1;
      let s = triSlot(k1, c2);
      for (;;) {
        const id = tId[s];
        if (id < 0) {
          if (!create) return -1;
          if ((triCount + 1) * 2 > tCap) { triGrow(); return triFind(c0, c1, c2, true); }
          tK1[s] = k1; tK2[s] = c2; tId[s] = triCount; triLast.push(-1);
          return triCount++;
        }
        if (tK1[s] === k1 && tK2[s] === c2) return id;
        s = (s + 1) & (tCap - 1);
      }
    }
    function pushPair(t, r) {
      if (pN === pT.length) { const a = new Int32Array(pN * 2); a.set(pT); pT = a; const b2 = new Int32Array(pN * 2); b2.set(pR); pR = b2; }
      pT[pN] = t; pR[pN] = r; pN++;
    }

    function indexText(i) {
      const r = records[i];
      const text = recordText(r, textFields);
      texts[i] = text;
      const len = text.length;
      if (!len) return;
      let c0 = 32, c1 = text.charCodeAt(0);
      for (let p = 0; p < len; p++) {
        const c2 = p + 1 < len ? text.charCodeAt(p + 1) : 32;
        if (c1 !== 32) {
          const id = triFind(c0, c1, c2, true);
          if (triLast[id] !== i) { triLast[id] = i; pushPair(id, i); }
        }
        c0 = c1; c1 = c2;
      }
    }

    function finishText() {
      postStart = new Int32Array(triCount + 1);
      for (let k = 0; k < pN; k++) postStart[pT[k] + 1]++;
      for (let t = 0; t < triCount; t++) postStart[t + 1] += postStart[t];
      const fill = postStart.slice(0, triCount);
      postData = new Int32Array(pN);
      for (let k = 0; k < pN; k++) postData[fill[pT[k]]++] = pR[k];
      pT = pR = null; triLast.length = 0;
      textDone = true;
    }

    /** Records whose text holds the trigram `g` (three characters), ascending; empty when none. */
    function postingsFor(g) {
      const id = triFind(g.charCodeAt(0), g.charCodeAt(1), g.charCodeAt(2), false);
      return id < 0 ? null : postData.subarray(postStart[id], postStart[id + 1]);
    }

    /** Index up to `budgetMs` of records (all when omitted); returns true when the text index is complete. */
    function buildTextIndex(budgetMs) {
      if (textDone) return true;
      const clock = typeof performance !== "undefined" ? () => performance.now() : () => Date.now();
      const stop = budgetMs == null ? Infinity : clock() + budgetMs;
      while (textBuilt < n) {
        indexText(textBuilt++);
        if ((textBuilt & 63) === 0 && clock() >= stop) break;
      }
      if (textBuilt >= n) finishText();
      return textDone;
    }

    function ensureTextIndex() { if (!textDone) buildTextIndex(); }

    /* masks: Uint8Array(n), 1 = record passes */

    function fullMask() { const m = new Uint8Array(n); m.fill(1); return m; }

    function facetMask(facet, sel) {
      const m = new Uint8Array(n);
      if (facet.kind === "range") {
        const lo = sel.min == null ? -Infinity : sel.min, hi = sel.max == null ? Infinity : sel.max;
        const rv = rangeValues.get(facet.id);
        for (let i = 0; i < n; i++) {
          for (const v of rv[i]) if (v >= lo && v <= hi) { m[i] = 1; break; }
        }
        return m;
      }
      const postings = index.get(facet.id);
      const values = sel.values || [];
      if (sel.all) {
        m.fill(1);
        for (const v of values) {
          const p = postings.get(v);
          const hit = new Uint8Array(n);
          if (p) for (let k = 0; k < p.length; k++) hit[p[k]] = 1;
          for (let i = 0; i < n; i++) m[i] &= hit[i];
        }
      } else {
        for (const v of values) {
          const p = postings.get(v);
          if (p) for (let k = 0; k < p.length; k++) m[p[k]] = 1;
        }
      }
      return m;
    }

    /* text */

    function textMatch(query) {
      // returns {mask, scores} or null when the query is empty
      const toks = tokens(query);
      if (!toks.length) return null;
      ensureTextIndex();
      const mask = fullMask();
      const scores = new Float64Array(n);
      const hits = new Int32Array(n);
      for (const tok of toks) {
        hits.fill(0);
        const grams = trigrams(tok);
        for (const g of grams) {
          const p = postingsFor(g);
          if (p) for (let k = 0; k < p.length; k++) hits[p[k]]++;
        }
        // A substring occurrence of a token of three or more characters
        // carries every inner trigram, so it can miss at most the two
        // space-padded edge trigrams; the substring scan is therefore only
        // needed when hits >= grams - 2 (and changes nothing when every
        // trigram hit, where the fraction is already 1). Tokens shorter than
        // three characters have no inner trigram and are scanned in full.
        const short = tok.length < 3;
        const g = grams.length;
        for (let i = 0; i < n; i++) {
          if (!mask[i]) continue;
          let score = 0;
          if (short) {
            score = texts[i].includes(tok) ? 1 : (hits[i] > 0 ? hits[i] / g : 0);
          } else if (hits[i] >= g) {
            score = 1;
          } else if (hits[i] > 0) {
            score = (hits[i] >= g - 2 && texts[i].includes(tok)) ? 1 : hits[i] / g;
          }
          if (score >= TEXT_THRESHOLD) scores[i] += score; else mask[i] = 0;
        }
      }
      const q = normalise(query);
      const tokGrams = toks.map(trigrams);
      for (let i = 0; i < n; i++) {
        if (!mask[i]) continue;
        let inName = 0, padded = null;
        for (let t = 0; t < toks.length; t++) {
          if (names[i].includes(toks[t]) || titles[i].includes(toks[t])) { inName++; continue; }
          if (padded === null) padded = " " + names[i] + " " + titles[i] + " ";
          let hit = 0;
          for (const gram of tokGrams[t]) if (padded.includes(gram)) hit++;
          if (hit / tokGrams[t].length >= TEXT_THRESHOLD) inName++;
        }
        const nameHit = names[i].includes(q) || titles[i].includes(q);
        const wordHit = (" " + names[i] + " ").includes(" " + q + " ") || (" " + titles[i] + " ").includes(" " + q + " ");
        scores[i] = scores[i] / toks.length + (nameHit ? NAME_BONUS : 0) + (nameHit && wordHit ? NAME_WORD_BONUS : 0) + (names[i] === q || titles[i] === q ? NAME_EXACT_BONUS : 0) + (ids[i].length >= q.length && normalise(ids[i]) === q ? ID_EXACT_BONUS : 0) + NAME_TOKEN_BONUS * inName / toks.length;
      }
      return { mask, scores };
    }

    /* query */

    function activeSelections(state) {
      const out = [];
      for (const fid of Object.keys(state.facets || {})) {
        const facet = facetById.get(fid);
        const sel = state.facets[fid];
        if (!facet || !sel) continue;
        if (facet.kind === "range") { if (sel.min != null || sel.max != null) out.push({ facet, sel }); }
        else if (sel.values && sel.values.length) out.push({ facet, sel });
      }
      return out;
    }

    function combine(masks, skipIndex) {
      const m = fullMask();
      for (let k = 0; k < masks.length; k++) {
        if (k === skipIndex) continue;
        const x = masks[k];
        for (let i = 0; i < n; i++) m[i] &= x[i];
      }
      return m;
    }

    function countUnder(facet, base) {
      const postings = index.get(facet.id);
      const out = {};
      for (const [v, p] of postings) {
        let c = 0;
        for (let k = 0; k < p.length; k++) c += base[p[k]];
        out[v] = c;
      }
      return out;
    }

    function rangeUnder(facet, base) {
      const rv = rangeValues.get(facet.id);
      const hist = {};
      for (let i = 0; i < n; i++) {
        if (!base[i]) continue;
        for (const v of new Set(rv[i])) hist[v] = (hist[v] || 0) + 1;
      }
      return hist;
    }

    function query(state) {
      const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      const active = activeSelections(state);
      const masks = active.map(a => facetMask(a.facet, a.sel));
      const text = textMatch(state.text || "");
      if (text) masks.push(text.mask);
      const result = combine(masks, -1);

      // live counts per facet
      const counts = {};
      const ranges = {};
      for (const facet of facets) {
        if (facet.kind === "text") continue;
        const k = active.findIndex(a => a.facet === facet);
        const includeOwn = k >= 0 && active[k].sel.all && facet.kind !== "range";
        const base = k >= 0 && !includeOwn ? combine(masks, k) : result;
        if (facet.kind === "range") ranges[facet.id] = rangeUnder(facet, base);
        else counts[facet.id] = countUnder(facet, base);
      }

      // ordering
      const idx = [];
      for (let i = 0; i < n; i++) if (result[i]) idx.push(i);
      const sortName = SORTS[state.sort] ? state.sort : "relevance";
      const spec = SORTS[sortName];
      const dir = state.dir === "asc" || state.dir === "desc" ? state.dir : spec.defaultDir;
      const sign = dir === "asc" ? 1 : -1;
      if (sortName === "relevance") {
        const scores = text ? text.scores : null;
        idx.sort((a, b) => {
          if (scores) { const d = scores[b] - scores[a]; if (d) return d * (dir === "desc" ? 1 : -1); }
          return cmp(names[a], names[b]) || cmp(ids[a], ids[b]);
        });
      } else {
        if (!sortKeyCache.has(spec.field)) sortKeyCache.set(spec.field, records.map(r => sortKey(r, spec.field)));
        const keys = sortKeyCache.get(spec.field);
        idx.sort((a, b) => {
          const ka = keys[a], kb = keys[b];
          if (ka == null && kb == null) return cmp(ids[a], ids[b]);
          if (ka == null) return 1;
          if (kb == null) return -1;
          return sign * cmp(ka, kb) || (spec.field === "provider" ? cmp(names[a], names[b]) : 0) || cmp(ids[a], ids[b]);
        });
      }
      const t1 = typeof performance !== "undefined" ? performance.now() : Date.now();
      return {
        indices: idx,
        ids: idx.map(i => ids[i]),
        total: idx.length,
        counts, ranges,
        scores: text ? idx.map(i => text.scores[i]) : null,
        sort: sortName, dir,
        ms: t1 - t0,
      };
    }

    return {
      size: n, records, facets, facetById, query, buildTextIndex, textIndexReady: () => textDone,
      valuesOf: (i, fid) => {
        const facet = facetById.get(fid);
        if (!facet || facet.kind === "text") return [];
        let v = extract(records[i], facet);
        if (facet.kind === "hierarchy") v = expandHierarchy(v, facet);
        return v;
      },
    };
  }

  return { createEngine, normalise, tokens, trigrams, extract, walkPath, applyTransform, SORTS, TEXT_THRESHOLD, NAME_BONUS };
}));
