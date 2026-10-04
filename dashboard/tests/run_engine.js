#!/usr/bin/env node
/*
 * Node harness for the property-based test.
 *
 * Reads one JSON document from stdin: {"bundle": "<path to bundle.json>",
 * "queries": [state, ...]} where each state is {text, facets, sort, dir} as
 * the dashboard passes it to the engine. Prints one JSON array with, per
 * query, {"ids": [...ordered ids], "counts": {...}, "ranges": {...}}.
 *
 * The engine is loaded from ../src/engine.js, the same file build.py inlines
 * into the page, so the test exercises the production code path.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { createEngine } = require(path.join(__dirname, "..", "src", "engine.js"));

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const bundle = JSON.parse(fs.readFileSync(input.bundle, "utf8"));
const engine = createEngine(bundle.records, bundle.facets, { textFields: bundle.meta.text_fields });
const out = input.queries.map(q => {
  const r = engine.query(q);
  return { ids: r.ids, counts: r.counts, ranges: r.ranges, sort: r.sort, dir: r.dir, scores: r.scores, ms: r.ms };
});
process.stdout.write(JSON.stringify(out));
if (process.env.ENGINE_TIMING) {
  const ms = out.map(o => o.ms).sort((a, b) => a - b);
  process.stderr.write(`engine: ${engine.size} records, ${ms.length} queries, median ${ms[Math.floor(ms.length / 2)].toFixed(1)} ms, p95 ${ms[Math.floor(ms.length * 0.95)].toFixed(1)} ms, max ${ms[ms.length - 1].toFixed(1)} ms\n`);
}
