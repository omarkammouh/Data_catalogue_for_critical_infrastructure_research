// Every interface string the page looks up has a French, German and Spanish entry (audit E10, 2026-09-26).
// Run: node tests/check_i18n.js [bundle.json]   Exit 1 lists the missing keys per language.
const fs = require("fs");
const path = require("path");
global.self = global;
require(path.join(__dirname, "..", "src", "i18n.js"));
const src = p => fs.readFileSync(path.join(__dirname, "..", "src", p), "utf8");
const keys = new Set();
const unq = s => JSON.parse('"' + s + '"');
for (const m of src("app.js").matchAll(/\bt\("((?:[^"\\]|\\.)*)"/g)) keys.add(unq(m[1]));
for (const m of src("app.js").matchAll(/\btn\([^,]+,\s*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"/g)) { keys.add(unq(m[1])); keys.add(unq(m[2])); }
const html = src("template.html");
for (const m of html.matchAll(/data-i18n(?:-html)?="([^"]*)"/g)) keys.add(m[1]);
for (const m of html.matchAll(/data-i18n-attr="([^"]*)"/g)) for (const pair of m[1].split("|")) keys.add(pair.slice(pair.indexOf(":") + 1));
const bundle = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], "utf8")) : null;
if (bundle) for (const f of bundle.facets) { keys.add(f.label); if (f.group) keys.add(f.group); }
// Vocabulary value names (not content like providers or places): a value added to the vocabulary shows in English until VOCAB has it. Warns, never fails.
const OWN_NAMES = new Set(["countries", "languages", "regions", "provider"]);
const vocabLabels = new Set();
if (bundle) {
  for (const f of bundle.facets) if (!OWN_NAMES.has(f.id)) for (const v of f.values || []) vocabLabels.add(v.label);
  for (const g of Object.values(bundle.meta.sector_groups || {})) vocabLabels.add(g);
  for (const g of Object.values(bundle.meta.family_groups || {})) vocabLabels.add(g);
}
const untranslated = [...vocabLabels].filter(l => !(l in I18N.VOCAB) && !(l in I18N.MESSAGES.fr) && !I18N.VOCAB_SAME.includes(l));
if (untranslated.length) console.log("warning: " + untranslated.length + " vocabulary names have no entry in VOCAB (shown in English):\n  " + untranslated.join("\n  "));
let bad = 0;
for (const lang of Object.keys(I18N.LANGUAGES).filter(l => l !== "en")) {
  const missing = [...keys].filter(k => !(k in I18N.MESSAGES[lang]));
  if (missing.length) { bad++; console.log(lang + ": " + missing.length + " missing\n  " + missing.join("\n  ")); }
}
const noEnglish = [...keys].filter(k => /^[a-z]+\.[a-z]+$/.test(k) && !(k in I18N.ENGLISH));
if (noEnglish.length) { bad++; console.log("keys without English text: " + noEnglish.join(", ")); }
console.log(bad ? "i18n: missing entries" : `i18n: ${keys.size} strings translated in ${Object.keys(I18N.LANGUAGES).length - 1} languages`);
process.exit(bad ? 1 : 0);
