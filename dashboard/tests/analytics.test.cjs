const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../src/analytics.js"), "utf8");
const token = "1234567890abcdef1234567890abcdef";

function run({ enabled = true, protocol = "https:", hostname = "omarkammouh.github.io",
  pathname = "/Data_catalogue_for_critical_infrastructure_research/", navigator = {}, existing = false } = {}) {
  const scripts = [], links = [];
  const document = {
    getElementById: () => existing,
    createElement: () => ({ setAttribute(name, value) { this[name] = value; } }),
    head: { appendChild: el => scripts.push(el) },
    querySelector: () => ({ appendChild: el => links.push(el) }),
  };
  vm.runInNewContext(source.replace(/const SITE_TOKEN = "[^"]*";/,
    `const SITE_TOKEN = "${enabled ? token : ""}";`), { document, navigator, location: { protocol, hostname, pathname } });
  return { scripts, links };
}

test("only the configured public site loads one nonblocking beacon", () => {
  const { scripts, links } = run();
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].src, "https://static.cloudflareinsights.com/beacon.min.js");
  assert.equal(scripts[0].async, true);
  assert.deepEqual(JSON.parse(scripts[0]["data-cf-beacon"]), { token, spa: false });
  assert.equal(links.length, 1);
});

for (const [name, options] of Object.entries({
  unconfigured: { enabled: false }, offline: { protocol: "file:" },
  localhost: { hostname: "localhost" }, mirror: { hostname: "example.org" },
  otherProject: { pathname: "/another-project/" },
  doNotTrack: { navigator: { doNotTrack: "1" } },
  globalPrivacyControl: { navigator: { globalPrivacyControl: true } },
  duplicate: { existing: true },
})) test(`${name}: no analytics request or notice`, () => {
  const { scripts, links } = run(options);
  assert.equal(scripts.length, 0);
  assert.equal(links.length, 0);
});
