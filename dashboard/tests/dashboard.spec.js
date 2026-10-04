// Browser tests for the built dashboard (dist/index.html opened from file://).
// Run: cd dashboard && npx playwright test -c tests/playwright.config.js
// Set DASHBOARD_HTML to test another build (the property fixtures build, for example).
const { test, expect } = require("@playwright/test");
const path = require("path");
const fs = require("fs");

const TEST_BUILD = path.resolve(__dirname, "..", "dist-test", "index.html");
const HTML = process.env.DASHBOARD_HTML || (fs.existsSync(TEST_BUILD) ? TEST_BUILD : path.resolve(__dirname, "..", "dist", "index.html"));
const URL = "file://" + HTML;
const BUNDLE = JSON.parse(fs.readFileSync(path.join(path.dirname(HTML), "bundle.json"), "utf8"));
const N = BUNDLE.records.length;
const fmt = n => Number(n).toLocaleString("en-US");
const FIRST_TYPE_COUNT = BUNDLE.records.filter(r => r.type === "data").length;

async function openFacet(page, id) {
  const details = page.locator(`details[data-facet="${id}"]`);
  if (!(await details.evaluate(el => el.open))) await details.locator("summary").click();
}

async function open(page, query = "") {
  const errors = [];
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", e => errors.push(e.message));
  await page.goto(URL + query);
  await page.waitForSelector('#app[data-state="ready"]');
  return errors;
}

test.describe("dashboard skeleton", () => {
  test("empty catalogue state is designed", async ({ page }) => {
    test.skip(N > 0, "only for a build from an empty catalogue");
    const errors = await open(page);
    await expect(page.locator(".state.empty h2")).toHaveText("The catalogue is empty");
    await expect(page.locator("#summary")).toContainText("0 of 0 records");
    expect(await page.locator('details[data-facet="sectors"] input[data-value]').count()).toBeGreaterThan(40);
    for (const box of await page.locator('details[data-facet="type"] input[data-value]').all()) await expect(box).toBeDisabled();
    expect(errors).toEqual([]);
  });

  test("loads from file:// with zero console errors and no layout shift", async ({ page }) => {
    await page.addInitScript(() => {
      window.__cls = 0;
      new PerformanceObserver(list => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: "layout-shift", buffered: true });
    });
    const errors = await open(page);
    await expect(page.locator("#summary")).toContainText(`${fmt(N)} of ${fmt(N)} record`);
    if (N) await expect(page.locator(".card")).toHaveCount(Math.min(N, 50));
    await page.waitForTimeout(300);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => window.__cls)).toBeLessThan(0.05);
    await expect(page).toHaveTitle("Data catalogue for critical infrastructure research");
    // self-contained: no external resource
    const external = await page.evaluate(() => performance.getEntriesByType("resource").map(e => e.name).filter(n => !n.startsWith("file:")));
    expect(external).toEqual([]);
  });

  test.describe("with records", () => {
  test.beforeEach(() => { test.skip(N === 0, "needs a build with records"); });

  test("facet selection filters, updates live counts and disables (never hides) zero values", async ({ page }) => {
    const errors = await open(page);
    await page.click('label[for="fv-type-data"]');
    await expect(page.locator("#summary")).toContainText(`${fmt(FIRST_TYPE_COUNT)} of ${fmt(N)}`);
    await expect(page).toHaveURL(/\?type=data$/);
    // model kinds cannot co-occur with type=data: all disabled, still present
    const modelKind = page.locator('details[data-facet="model_kind"] input[type="checkbox"][data-value]');
    expect(await modelKind.count()).toBeGreaterThan(0);
    for (const box of await modelKind.all()) await expect(box).toBeDisabled();
    // the type facet itself keeps its counts (OR semantics: the facet's own selection is excluded)
    await expect(page.locator('label[for="fv-type-model"] .count')).toHaveText(String(BUNDLE.records.filter(r => r.type === "model").length));
    // OR within a facet
    await page.click('label[for="fv-type-model"]');
    await expect(page.locator("#summary")).toContainText(`${fmt(BUNDLE.records.filter(r => r.type === "data" || r.type === "model").length)} of ${fmt(N)}`);
    await expect(page).toHaveURL(/type=data%2Cmodel/);
    expect(errors).toEqual([]);
  });

  test("search inside one filter: any case, accents ignored, counts kept, ticked values stay visible", async ({ page }) => {
    test.skip(!BUNDLE.records.some(r => r.provider === "Example Grid Lab") || !BUNDLE.records.some(r => r.provider === "Beispielamt für Gewässerkunde"), "written for the fixture providers");
    const errors = await open(page);
    const facet = page.locator('details[data-facet="provider"]');
    await facet.locator("summary").click();
    const search = facet.locator('input[type="search"]');
    await expect(search).toBeVisible();
    const grid = facet.locator('li[data-value="Example Grid Lab"]');
    const countBefore = await grid.locator(".count").textContent();
    await grid.locator("label").click();
    await search.fill("GEWASSERKUNDE");
    const shown = facet.locator("ul.facet-values > li:not([hidden])");
    await expect(shown).toHaveCount(2);
    await expect(shown.filter({ hasText: "Beispielamt für Gewässerkunde" })).toHaveCount(1);
    await expect(grid).toBeVisible();                                   // ticked, although it does not match
    await expect(grid.locator(".count")).toHaveText(countBefore);       // counts stay
    await search.fill("zzz-no-such-provider");
    await expect(facet.locator(".facet-empty")).toBeVisible();
    await expect(grid).toBeVisible();
    await search.press("Escape");                                       // first Escape clears the search and stays in the box
    await expect(search).toHaveValue("");
    await expect(search).toBeFocused();
    await expect(facet.locator(".facet-empty")).toBeHidden();
    expect(await shown.count()).toBeGreaterThan(2);
    expect(errors).toEqual([]);
  });

  test("search all filters finds a value or a filter by name, opens it, hides the rest and restores the panel", async ({ page }) => {
    const errors = await open(page);
    const box = page.locator("#filter-search");
    const open0 = await page.locator("details.facet[open]").evaluateAll(els => els.map(e => e.dataset.facet));
    await box.fill("flood");
    const hazards = page.locator('details[data-facet="hazards"]');
    await expect(hazards).toBeVisible();
    await expect(hazards).toHaveJSProperty("open", true);
    await expect(hazards.locator("ul.facet-values > li:not([hidden])").first()).toContainText(/flood/i);
    await expect(page.locator('details[data-facet="cost"]')).toBeHidden();
    await expect(page.locator("#filter-search-status")).toContainText("Filters matching");
    // a filter name shows the whole filter
    await box.fill("licence");
    await expect(page.locator('details[data-facet="licence"]')).toBeVisible();
    expect(await page.locator('details[data-facet="licence"] ul.facet-values > li:not([hidden])').count()).toBeGreaterThan(3);
    // a value found through the search can be ticked like any other
    await box.fill("flood");
    await hazards.locator('li:not([hidden]) label').first().click();
    await expect(page).toHaveURL(/hazards=/);
    // clearing restores the panel
    await box.press("Escape");
    await expect(box).toHaveValue("");
    await expect(page.locator('details[data-facet="cost"]')).toBeVisible();
    await expect(page.locator("#filter-search-status")).toHaveText("");
    for (const id of open0) await expect(page.locator(`details[data-facet="${id}"]`)).toHaveJSProperty("open", true);
    expect(errors).toEqual([]);
  });

  test("search all filters keeps a facet with ticked values and shows a hint when nothing matches", async ({ page }) => {
    await open(page, "?type=data");
    const box = page.locator("#filter-search");
    await box.fill("zzzzqqq");
    await expect(page.locator('details[data-facet="type"]')).toBeVisible();       // active filters never vanish
    await expect(page.locator('details[data-facet="cost"]')).toBeHidden();
    await expect(page.locator("#filter-search-status")).toContainText("1 of");
  });

  test("match-all switch changes within-facet semantics", async ({ page }) => {
    await open(page);
    const facet = page.locator('details[data-facet="simulation_uses"]');
    await facet.locator("summary").click();
    await facet.locator('label[for="fv-simulation_uses-network_flow"]').click();
    await facet.locator('label[for="fv-simulation_uses-resilience"]').click();
    const anyCount = BUNDLE.records.filter(r => (r.simulation_uses || []).some(u => ["network_flow", "resilience"].includes(u))).length;
    const allCount = BUNDLE.records.filter(r => ["network_flow", "resilience"].every(u => (r.simulation_uses || []).includes(u))).length;
    await expect(page.locator("#summary")).toContainText(`${fmt(anyCount)} of ${fmt(N)}`);
    await facet.locator("#facet-all-simulation_uses").check();
    await expect(page.locator("#summary")).toContainText(`${fmt(allCount)} of ${fmt(N)}`);
    await expect(page).toHaveURL(/simulation_uses\.all=1/);
  });

  test("hierarchy facet: selecting a group matches every sector in it", async ({ page }) => {
    await open(page);
    await page.click('label[for="fv-sectors-energy"]');
    const n = BUNDLE.records.filter(r => (r.sectors || []).some(s => s === "energy" || s.startsWith("energy."))).length;
    await expect(page.locator("#summary")).toContainText(`${fmt(n)} of ${fmt(N)}`);
    await page.click('details[data-facet="sectors"] .tree-toggle >> nth=0');
    await expect(page.locator('details[data-facet="sectors"] li.child:visible').first()).toBeVisible();
  });

  test("chips show every applied filter, remove one, clear all", async ({ page }) => {
    await open(page, "?type=data&cost=free&q=flood");
    const chips = page.locator("#chips .chip");
    await expect(chips).toHaveCount(3);
    await expect(chips.nth(0)).toContainText("Search");
    await expect(chips.nth(1)).toContainText("Type");
    await page.click('#chips .chip-remove[aria-label="Remove filter Type Data"]');
    await expect(chips).toHaveCount(2);
    await expect(page).not.toHaveURL(/type=/);
    await page.click("#clear-all");
    await expect(chips).toHaveCount(0);
    await expect(page.locator("#summary")).toContainText(`${fmt(N)} of ${fmt(N)}`);
    await expect(page.locator("#toast")).toContainText("Filters cleared");
    await page.click("#toast .link-button");
    await expect(chips).toHaveCount(2);
  });

  test("URL round trip: state is restored from the address, back and forward undo and redo", async ({ page }) => {
    await open(page, "?type=data&sectors=water&sort=name&dir=asc&view=table");
    await expect(page.locator("#chips .chip")).toHaveCount(2);
    await expect(page.locator("#sort")).toHaveValue("name");
    await expect(page.locator('#view-switch [data-view="table"]')).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("table.grid")).toBeVisible();
    await expect(page.locator('label[for="fv-type-data"] input')).toBeChecked();
    await openFacet(page, "cost");
    await page.click('label[for="fv-cost-free"]');
    await expect(page).toHaveURL(/cost=free/);
    await page.goBack();
    await expect(page).not.toHaveURL(/cost=free/);
    await expect(page.locator('label[for="fv-cost-free"] input')).not.toBeChecked();
    await page.goForward();
    await expect(page).toHaveURL(/cost=free/);
    await expect(page.locator('label[for="fv-cost-free"] input')).toBeChecked();
    await page.reload();
    await page.waitForSelector('#app[data-state="ready"]');
    await expect(page.locator("#chips .chip")).toHaveCount(3);
  });

  test("range facet filters by year and shows in the URL", async ({ page }) => {
    await open(page);
    const facet = page.locator('details[data-facet="year_catalogued"]');
    await facet.locator("summary").click();
    await facet.locator("#range-min-year_catalogued").fill("2030");
    await facet.locator("#range-min-year_catalogued").press("Enter");
    await expect(page).toHaveURL(/year_catalogued=2030\.\./);
    await expect(page.locator(".state.no-results")).toBeVisible();
    await page.click(".state.no-results >> text=Remove last filter");
    await expect(page.locator("#summary")).toContainText(`${fmt(N)} of ${fmt(N)}`);
  });

  test("free text search is fuzzy and drives relevance", async ({ page }) => {
    await open(page);
    // take the longest word of a record name and drop one inner character
    const target = BUNDLE.records.map(r => ({ r, w: r.name.split(/\s+/).filter(w => /^[\p{L}]+$/u.test(w)).sort((a, b) => b.length - a.length)[0] || "" })).sort((a, b) => b.w.length - a.w.length)[0];
    const typo = target.w.slice(0, 2) + target.w.slice(3);
    await page.fill("#q", typo.toLowerCase());
    await expect(page).toHaveURL(new RegExp("q=" + encodeURIComponent(typo.toLowerCase())));
    await expect(page.locator(".card").first()).toContainText(target.w);
    await page.press("#q", "Escape");
    await expect(page).not.toHaveURL(/q=/);
  });

  test("sorting by name and provider, direction toggle", async ({ page }) => {
    await open(page);
    await page.selectOption("#sort", "name");
    const names = await page.locator(".card-title").allTextContents();
    const sorted = [...names].sort((a, b) => a.toLowerCase() < b.toLowerCase() ? -1 : 1);
    expect(names).toEqual(sorted);
    await page.click("#dir");
    await expect(page).toHaveURL(/dir=desc/);
    expect(await page.locator(".card-title").allTextContents()).toEqual([...sorted].reverse());
  });

  test("detail view: description, link buttons, provenance, cross-links that navigate, copy", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const errors = await open(page);
    const first = BUNDLE.records.find(r => (r.related_ids || []).some(id => BUNDLE.records.some(x => x.id === id)));
    await page.click(`.card[data-id="${first.id}"]`);
    await expect(page).toHaveURL(new RegExp("r=" + first.id));
    await expect(page.locator(".detail-title")).toHaveText(first.title_en || first.name);
    await expect(page.locator(".detail-title")).toBeFocused();
    await expect(page.locator(".detail p.prose")).toHaveText(first.description);
    const buttons = page.locator(".link-buttons a.button");
    await expect(buttons).toHaveCount(first.access_links.length);
    await expect(buttons.first()).toHaveAttribute("target", "_blank");
    await expect(buttons.first()).toHaveAttribute("href", first.access_links[0].url);
    await expect(page.locator(".detail")).toContainText("Links checked");
    await expect(page.locator(".detail")).toContainText(first.date_verified);
    await expect(page.locator(".provenance").first()).toContainText(first.sources[0].url);
    const related = first.related_ids.find(id => BUNDLE.records.some(x => x.id === id));
    await page.click(`.related a.pill[href*="r=${related}"]`);
    await expect(page).toHaveURL(new RegExp("r=" + related));
    const relatedRecord = BUNDLE.records.find(x => x.id === related);
    await expect(page.locator(".detail-title")).toHaveText(relatedRecord.title_en || relatedRecord.name);
    await page.click("text=Copy citation");
    await expect(page.locator("#toast")).toContainText("Citation copied");
    await page.click("text=Back to results");
    await expect(page).toHaveURL(new RegExp("r=" + first.id));
    await page.keyboard.press("Escape");
    await expect(page).not.toHaveURL(/r=/);
    await expect(page.locator(".card").first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("table view with column choice remembered per viewer", async ({ page }) => {
    await open(page, "?view=table");
    await expect(page.locator("table.grid th")).toHaveCount(7);
    await page.click("#columns-toggle");
    await page.click('#columns-menu label:has-text("Licence")');
    await expect(page.locator("table.grid th")).toHaveCount(6);
    await page.reload();
    await page.waitForSelector('#app[data-state="ready"]');
    await expect(page.locator("table.grid th")).toHaveCount(6);
    expect(await page.evaluate(() => localStorage.getItem("catalogue.columns"))).toContain("name");
  });

  test("coverage view shows counts per sector and family and links into the list", async ({ page }) => {
    await open(page, "?view=coverage");
    await expect(page.locator(".coverage-grid .viz")).toHaveCount(2);
    await expect(page.locator(".coverage-grid .viz").first()).toContainText("Electricity");
    // a record tagged only with the parent sector "energy" counts under every energy sector (engine.js header)
    const n = BUNDLE.records.filter(r => (r.sectors || []).includes("energy.electricity") || ((r.sectors || []).includes("energy") && !(r.sectors || []).some(s => s.startsWith("energy.")))).length;
    const row = page.locator(".bar-row", { hasText: "Electricity" }).first();
    await expect(row.locator(".bar-value")).toHaveText(String(n));
    await row.locator("a").click();
    await expect(page).toHaveURL(/sectors=energy\.electricity/);
    await expect(page.locator("#summary")).toContainText(`${fmt(n)} of ${fmt(N)}`);
  });

  test("export CSV and JSON of the current set record the applied filters", async ({ page }) => {
    await open(page, "?type=data&cost=free");
    await page.click("#export-toggle");
    const [csv] = await Promise.all([page.waitForEvent("download"), page.click("#export-csv")]);
    expect(csv.suggestedFilename()).toBe("catalogue-export.csv");
    const csvText = fs.readFileSync(await csv.path(), "utf8");
    expect(csvText).toContain("# filters:");
    expect(csvText).toContain('"facet":"type"');
    expect(csvText.split("\r\n").filter(l => l && !l.startsWith("#")).length).toBe(1 + BUNDLE.records.filter(r => r.type === "data" && r.cost === "free").length);
    await page.click("#export-toggle");
    const [json] = await Promise.all([page.waitForEvent("download"), page.click("#export-json")]);
    const payload = JSON.parse(fs.readFileSync(await json.path(), "utf8"));
    expect(payload.filters.map(f => f.facet)).toEqual(["type", "cost"]);
    expect(payload.records.every(r => r.type === "data" && r.cost === "free")).toBe(true);
  });

  test("dark mode: system preference, manual toggle overrides both ways", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await open(page);
    const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const darkBg = await bg();
    await page.click("#theme-toggle"); // system -> light
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    const lightBg = await bg();
    expect(lightBg).not.toBe(darkBg);
    await page.click("#theme-toggle"); // light -> dark
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    expect(await bg()).toBe(darkBg);
    await page.emulateMedia({ colorScheme: "light" });
    expect(await bg()).toBe(darkBg); // manual choice wins over the OS
    await page.reload();
    await page.waitForSelector('#app[data-state="ready"]');
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark"); // remembered
  });

  test("reduced motion disables transitions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    const dur = await page.evaluate(() => getComputedStyle(document.querySelector(".card")).transitionDuration);
    expect(dur.split(",").every(d => d.trim() === "0s")).toBe(true);
  });

  test("phone width: no horizontal scroll, filters open as a sheet", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    const errors = await open(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
    await expect(page.locator("#rail")).not.toBeInViewport();
    await page.click("#rail-open");
    await expect(page.locator("#rail")).toHaveClass(/open/);
    await page.click('label[for="fv-type-platform"]');
    await page.click("#rail-close");
    await expect(page.locator("#rail")).not.toHaveClass(/open/);
    await expect(page.locator("#rail-badge")).toHaveText("1");
    await expect(page.locator("#summary")).toContainText(`${fmt(BUNDLE.records.filter(r => r.type === "platform").length)} of ${fmt(N)}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
    expect(errors).toEqual([]);
  });

  test("keyboard: / focuses search, arrows move through results, Enter opens, Esc returns with focus restored", async ({ page }) => {
    await open(page);
    await page.keyboard.press("/");
    await expect(page.locator("#q")).toBeFocused();
    await page.keyboard.press("Escape");
    await page.keyboard.press("Tab");
    await page.locator("#results").focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator(".card").first()).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator(".card").nth(1)).toBeFocused();
    const id = await page.locator(".card").nth(1).getAttribute("data-id");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp("r=" + id));
    await expect(page.locator(".detail-title")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator(`.card[data-id="${id}"]`)).toBeFocused();
  });

  test("no-results and error states are designed", async ({ page }) => {
    await open(page, "?q=zzzzqqqq");
    await expect(page.locator(".state.no-results h2")).toHaveText("No records match");
    await page.click(".state.no-results >> text=Clear all filters");
    await expect(page.locator(".card").first()).toBeVisible();
    await page.evaluate(() => { window.__catalogue.engine.query = () => { throw new Error("synthetic failure"); }; });
    await page.click('label[for="fv-type-data"]');
    await expect(page.locator(".state.error")).toContainText("synthetic failure");
    await expect(page.locator("#app")).toHaveAttribute("data-state", "error");
  });

  test("filter latency stays inside the budget", async ({ page }) => {
    await open(page, "?type=data&sectors=energy&q=grid");
    const ms = parseFloat(await page.locator("#summary").getAttribute("data-ms"));
    expect(ms).toBeLessThan(50);
  });
  });

  test("a stray % in the address keeps the page working (audit 2026-09-24)", async ({ page }) => {
    const errors = await open(page, "?licence=100%");
    await expect(page.locator("#app")).toHaveAttribute("data-state", "ready");
    await expect(page.locator(".state.error")).toHaveCount(0);
    await expect(page.locator("#chips")).toContainText("100%");
    expect(errors).toEqual([]);
  });

  test("link health names dead, unverified and unchecked records; the detail view says which (audit 2026-09-24)", async ({ page }) => {
    test.skip(!BUNDLE.records.some(r => r.id === "model-synth-power-flow"), "needs the fixture build, whose records carry the four link_health cases");
    const errors = await open(page);
    await openFacet(page, "link_health");
    const values = await page.locator('details[data-facet="link_health"] input[data-value]').evaluateAll(els => els.map(e => e.dataset.value));
    expect(values.sort()).toEqual(["all links alive", "dead links", "not checked", "some links unverified"]);
    await page.locator('details[data-facet="link_health"] input[data-value="some links unverified"]').check();
    await expect(page.locator("#summary")).toContainText("1 of " + fmt(N));
    await page.goto(URL + "?r=model-synth-power-flow");
    await page.waitForSelector('#app[data-state="ready"]');
    await expect(page.locator(".detail")).toContainText("1 link not confirmed at the check of 2026-09-20");
    await expect(page.locator(".detail")).not.toContainText("All links checked");
    await page.goto(URL + "?r=data-synth-transit-feeds");
    await page.waitForSelector('#app[data-state="ready"]');
    await expect(page.locator(".detail")).toContainText("Links not checked yet");
    expect(errors).toEqual([]);
  });

  test("accessibility scan (axe-core) finds no violations in light, dark and phone widths (audit 2026-09-24)", async ({ browser }) => {
    const AXE = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
    for (const [viewport, colorScheme, query] of [[{ width: 1440, height: 900 }, "light", ""], [{ width: 1440, height: 900 }, "dark", ""], [{ width: 390, height: 844 }, "light", ""], [{ width: 1440, height: 900 }, "light", "?view=coverage"], [{ width: 1440, height: 900 }, "light", "?r=" + (BUNDLE.records[0] || {}).id]]) {
      if (query.startsWith("?r=") && !N) continue;
      const ctx = await browser.newContext({ viewport, colorScheme });
      const page = await ctx.newPage();
      await page.goto(URL + query);
      await page.waitForSelector('#app[data-state="ready"]');
      await page.addScriptTag({ content: AXE });
      const violations = await page.evaluate(async () => (await axe.run(document, { resultTypes: ["violations"] })).violations.map(v => v.id + ": " + v.nodes.length));
      expect(violations, `${colorScheme} ${viewport.width}px ${query}`).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `no horizontal scroll at ${viewport.width}px ${query}`).toBe(true);
      await ctx.close();
    }
  });

  test.describe("round-1 audit items (2026-09-26)", () => {
    test.beforeEach(() => { test.skip(N === 0, "needs a build with records"); });
    const C = BUNDLE.meta.completeness;

    test("coverage counts describe the selected records", async ({ page }) => {
      const errors = await open(page, "?view=coverage&type=model");
      await expect(page.locator(".stat-value").first()).toHaveText(fmt(BUNDLE.records.filter(r => r.type === "model").length));
      await expect(page.locator(".completeness-table")).toHaveCount(0);
      expect(errors).toEqual([]);
    });

    test("the page says how many records had their content checked, and marks the ones that were not", async ({ page }) => {
      const checked = BUNDLE.records.filter(r => r.description_checked).length;
      await open(page);
      await expect(page.locator("#foot-status")).toHaveText(`${fmt(N)} records in this catalogue.`);
      const unchecked = BUNDLE.records.filter(r => !r.description_checked);
      await expect(page.locator(".pill.attention")).toHaveCount(Math.min(unchecked.length, 50));
      if (!unchecked.length) return; // every record checked: the facet then has no "not checked" value to pick
      await openFacet(page, "content_check");
      await page.locator('details[data-facet="content_check"] input[data-value="not checked"]').check();
      await expect(page.locator("#summary")).toContainText(`${fmt(unchecked.length)} of ${fmt(N)}`);
      if (unchecked.length) {
        await page.goto(URL + "?r=" + unchecked[0].id);
        await page.waitForSelector('#app[data-state="ready"]');
        await expect(page.locator(".detail")).toContainText("Not checked yet");
      }
    });

    test("range facets for years covered, size and resolution filter the records", async ({ page }) => {
      test.skip(["coverage_years", "size_bytes", "resolution_m"].some(id => BUNDLE.facets.find(f => f.id === id).empty), "needs records carrying the three fields");
      const has = (r, lo, hi) => r.temporal_coverage_years && r.temporal_coverage_years.start <= hi && (r.temporal_coverage_years.end == null || r.temporal_coverage_years.end >= lo);
      await open(page, "?coverage_years=2020..2021");
      await expect(page.locator("#summary")).toContainText(`${fmt(BUNDLE.records.filter(r => has(r, 2020, 2021)).length)} of ${fmt(N)}`);
      await page.goto(URL + "?size_bytes=1000000000..");
      await page.waitForSelector('#app[data-state="ready"]');
      await expect(page.locator("#summary")).toContainText(`${fmt(BUNDLE.records.filter(r => r.size_bytes >= 1e9).length)} of ${fmt(N)}`);
      await openFacet(page, "size_bytes");
      await expect(page.locator("#range-min-size_bytes option:checked")).toHaveText("1 GB");
      await openFacet(page, "resolution_m");
      await page.selectOption("#range-max-resolution_m", "1");
      await expect(page).toHaveURL(/resolution_m=\.\.1(&|$)/);
      await expect(page.locator("#summary")).toContainText(`${fmt(BUNDLE.records.filter(r => r.size_bytes >= 1e9 && r.spatial_resolution_m <= 1).length)} of ${fmt(N)}`);
      await page.goto(URL + "?resolution_m=0.1..10");
      await page.waitForSelector('#app[data-state="ready"]');
      await expect(page.locator(".chip")).toHaveCount(1);
    });

    test("every vocabulary value has a written label", async () => {
      expect(BUNDLE.meta.missing_labels).toEqual([]);
    });

    test("the interface follows the chosen language and the browser's, and remembers the choice", async ({ browser }) => {
      const ctx = await browser.newContext({ locale: "de-DE" });
      const page = await ctx.newPage();
      await page.goto(URL + "?view=coverage");
      await page.waitForSelector('#app[data-state="ready"]');
      await expect(page.locator("html")).toHaveAttribute("lang", "de");
      await expect(page).toHaveTitle("Data catalogue for critical infrastructure research");
      await expect(page.locator(".brand-name")).toHaveText("Data catalogue for critical infrastructure research");
      await expect(page.locator("#q")).toHaveAttribute("placeholder", "Name, Anbieter, Beschreibung, Schlagwörter suchen");
      await expect(page.locator('#view-switch [data-view="coverage"]')).toHaveText("Abdeckung");
      if (C) await expect(page.locator("#completeness-title")).toHaveText("Geschätzte Vollständigkeit");
      await page.selectOption("#lang", "fr");
      await page.waitForSelector('#app[data-state="ready"]');
      await expect(page.locator("html")).toHaveAttribute("lang", "fr");
      await expect(page).toHaveURL(/view=coverage/);
      await expect(page.locator(".rail-title")).toHaveText("Filtres");
      await page.goto(URL);
      await page.waitForSelector('#app[data-state="ready"]');
      await expect(page.locator("html")).toHaveAttribute("lang", "fr");
      await expect(page.locator("#summary")).toContainText("fiches");
      await ctx.close();
    });

    test("screen-reader pass: every control has an accessible name in English and French, and results are announced", async ({ browser }) => {
      for (const lang of ["en", "fr"]) {
        const ctx = await browser.newContext({ locale: lang });
        const page = await ctx.newPage();
        for (const query of ["", "?view=table", "?view=coverage", "?r=" + BUNDLE.records[0].id]) {
          await page.goto(URL + query);
          await page.waitForSelector('#app[data-state="ready"]');
          await page.locator('details[data-facet]').first().evaluate(d => { d.open = true; });
          const cdp = await ctx.newCDPSession(page);
          const { nodes } = await cdp.send("Accessibility.getFullAXTree");
          const ROLES = new Set(["button", "link", "textbox", "searchbox", "combobox", "checkbox", "menuitem", "slider", "spinbutton", "radio", "switch", "tab"]);
          const unnamed = nodes.filter(n => !n.ignored && ROLES.has(n.role && n.role.value) && !(n.name && String(n.name.value).trim()))
            .map(n => n.role.value + " " + (n.backendDOMNodeId || ""));
          expect(unnamed, `${lang} ${query || "list"}`).toEqual([]);
          const landmarks = nodes.filter(n => !n.ignored && ["banner", "main", "navigation", "contentinfo", "search", "complementary"].includes(n.role && n.role.value)).map(n => n.role.value);
          expect(new Set(landmarks).size, `${lang} ${query} landmarks`).toBeGreaterThanOrEqual(5);
          await cdp.detach();
        }
        await page.goto(URL);
        await page.waitForSelector('#app[data-state="ready"]');
        await expect(page.locator("#summary")).toHaveAttribute("aria-live", "polite");
        const before = await page.locator("#summary").textContent();
        await page.fill("#q", BUNDLE.records[0].name.split(" ")[1] || BUNDLE.records[0].name);
        await expect(page.locator("#summary")).not.toHaveText(before);
        await ctx.close();
      }
    });

    test("print: the page prints the results and the build line without the controls", async ({ page }) => {
      await open(page, "?type=data");
      await page.emulateMedia({ media: "print" });
      for (const sel of [".topbar", ".rail", ".toolbar", "#lang"]) await expect(page.locator(sel).first()).toBeHidden();
      await expect(page.locator(".card").first()).toBeVisible();
      await expect(page.locator(".chips")).toBeVisible();
      await expect(page.locator("#foot-meta")).toBeVisible();
      await expect(page.locator("#foot-status")).toBeVisible();
      const width = await page.evaluate(() => document.querySelector(".results").getBoundingClientRect().width);
      expect(width).toBeGreaterThan(600);
      const pdf = await page.pdf({ format: "A4" });
      expect(pdf.length).toBeGreaterThan(10000);
      await page.goto(URL + "?r=" + BUNDLE.records[0].id);
      await page.waitForSelector('#app[data-state="ready"]');
      const after = await page.evaluate(() => { const a = document.querySelector('.detail a[href^="http"]'); return a ? getComputedStyle(a, "::after").content : null; });
      if (after) expect(after).toContain("http");
    });

    test("phone width keeps the catalogue name, and nothing scrolls sideways", async ({ browser }) => {
      const ctx = await browser.newContext({ viewport: { width: 360, height: 780 } });
      const page = await ctx.newPage();
      for (const query of ["", "?view=coverage", "?view=table", "?r=" + BUNDLE.records[0].id]) {
        await page.goto(URL + query);
        await page.waitForSelector('#app[data-state="ready"]');
        await expect(page.locator(".brand-name")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), query).toBe(true);
      }
      await ctx.close();
    });

    test("a long unbroken string in a record or a card wraps instead of widening the page (round 2 check, 2026-10-01)", async ({ browser }) => {
      for (const width of [360, 1440]) {
        const ctx = await browser.newContext({ viewport: { width, height: 800 } });
        const page = await ctx.newPage();
        await page.goto(URL + "?r=" + BUNDLE.records[0].id);
        await page.waitForSelector('#app[data-state="ready"]');
        await page.evaluate(() => { const long = "https://intranet.example.org/front/publicDownload.jsp?docId=" + "A1b2C3d4".repeat(60); document.querySelector(".detail p.prose").textContent = long; });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "record at " + width).toBe(true);
        await page.goto(URL);
        await page.waitForSelector('#app[data-state="ready"]');
        await page.evaluate(() => { const d = document.querySelector(".card-desc"); d.textContent = "x".repeat(400); document.querySelector(".card-title").textContent = "y".repeat(400); });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "card at " + width).toBe(true);
        await ctx.close();
      }
    });

    test("no view scrolls sideways at 320 px, in every language, also with text at 200% (round 2 re-check, 2026-10-02)", async ({ browser }) => {
      const ctx = await browser.newContext({ viewport: { width: 320, height: 568 } });
      const page = await ctx.newPage();
      await page.addInitScript(() => { try { localStorage.setItem("catalogue.helpSeen", "true"); } catch (e) { /* storage unavailable */ } });
      await page.goto(URL);
      for (const lang of ["en", "de", "fr", "es"]) {
        await page.evaluate(l => { localStorage.setItem("catalogue.lang", JSON.stringify(l)); }, lang);
        await page.goto(URL);
        await page.waitForSelector('#app[data-state="ready"]');
        for (const size of ["", "200%"]) {
          await page.evaluate(s => { document.documentElement.style.fontSize = s; }, size);
          for (const view of ["list", "table", "coverage"]) {
            await page.evaluate(v => { history.pushState(null, "", location.pathname + "?view=" + v); window.dispatchEvent(new PopStateEvent("popstate")); }, view);
            await page.waitForTimeout(300);
            if (view === "list") await page.evaluate(() => window.scrollTo(0, 1e9)); // the pager sits at the end of the list
            const w = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: document.documentElement.clientWidth }));
            expect(w.scroll, view + " at 320 px, " + lang + ", text " + (size || "100%")).toBeLessThanOrEqual(w.view);
          }
        }
      }
      await ctx.close();
    });

    test("export menu follows the menu keys and Esc closes the help panel (round 2 check, 2026-10-01)", async ({ page }) => {
      await open(page);
      await page.locator("#help-dismiss").click(); // first visit shows the panel
      await expect(page.locator("#help-panel")).toBeHidden();
      await page.locator("#help-toggle").focus();
      await page.keyboard.press("Enter");
      await expect(page.locator("#help-panel")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.locator("#help-panel")).toBeHidden();
      await expect(page.locator("#help-toggle")).toBeFocused();
      await page.locator("#export-toggle").focus();
      await page.keyboard.press("Enter");
      await page.keyboard.press("ArrowDown");
      await expect(page.locator("#export-csv")).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await expect(page.locator("#export-json")).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await expect(page.locator("#export-csv")).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(page.locator("#export-menu .menu-list")).toBeHidden();
      await expect(page.locator("#export-toggle")).toBeFocused();
    });

    test("phone filter sheet keeps keyboard focus inside and Esc closes it (round 2 check, 2026-10-01)", async ({ browser }) => {
      const ctx = await browser.newContext({ viewport: { width: 390, height: 800 } });
      const page = await ctx.newPage();
      await page.goto(URL);
      await page.waitForSelector('#app[data-state="ready"]');
      await page.locator("#help-dismiss").click().catch(() => {});
      await page.locator("#rail-open").click();
      await page.waitForFunction(() => !!document.activeElement.closest("#rail")); // focus moves into the sheet
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab");
        expect(await page.evaluate(() => !!document.activeElement.closest("#rail")), "tab stop " + i).toBe(true);
      }
      await page.keyboard.press("Escape");
      await expect(page.locator("#rail-open")).toHaveAttribute("aria-expanded", "false");
      await expect(page.locator("#rail-open")).toBeFocused();
      await ctx.close();
    });

    test("every id in the page is unique, so a value's label ticks that value and no other (round 2 check, 2026-10-01)", async ({ page }) => {
      await open(page);
      const dup = await page.evaluate(() => { const c = {}; for (const e of document.querySelectorAll("[id]")) c[e.id] = (c[e.id] || 0) + 1; return Object.entries(c).filter(([, n]) => n > 1).map(([k]) => k); });
      expect(dup).toEqual([]);
      const boxes = page.locator("#facets input[type=checkbox][data-value]");
      const n = Math.min(await boxes.count(), 12);
      for (let i = 0; i < n; i++) {
        const box = boxes.nth(i);
        if (!(await box.isVisible()) || (await box.isDisabled())) continue;
        const value = await box.getAttribute("data-value");
        await box.locator("xpath=ancestor::label").click();
        expect(await page.evaluate(() => Array.from(document.querySelectorAll("#facets input[type=checkbox][data-value]:checked")).map(e => e.dataset.value)), "label " + value).toEqual([value]);
        await box.locator("xpath=ancestor::label").click();
      }
    });

    test("search index is built after the first paint and is ready soon after", async ({ page }) => {
      await open(page);
      await page.waitForSelector('#app[data-text-index="ready"]');
      await page.fill("#q", BUNDLE.records[0].provider);
      await expect(page.locator("#summary")).not.toContainText(`${fmt(N)} of ${fmt(N)}`);
    });
  });
  test.describe("content check items (2026-10-01)", () => {
    const facts = page => page.locator(".detail .kv").first().locator("dt").allTextContents();

    test("the detail view shows the record's last update date", async ({ page }) => {
      const r = BUNDLE.records.find(x => x.last_updated);
      test.skip(!r, "needs a record with last_updated");
      await page.goto(URL + "?r=" + r.id);
      await page.waitForSelector('#app[data-state="ready"]');
      const dt = page.locator(".detail .kv").first().locator("dt", { hasText: /^Last updated$/ });
      await expect(dt).toHaveCount(1);
      await expect(dt.locator("xpath=following-sibling::dd[1]")).toHaveText(String(r.last_updated));
    });

    test("no two facts of a record share a label, and 'Description checked' appears once", async ({ page }) => {
      const sample = BUNDLE.records.filter(r => r.spatial_resolution || r.size || r.size_bytes || r.last_updated).slice(0, 20);
      for (const r of sample.length ? sample : BUNDLE.records.slice(0, 5)) {
        await page.goto(URL + "?r=" + r.id);
        await page.waitForSelector('#app[data-state="ready"]');
        const labels = await facts(page);
        expect(labels.filter((l, i) => labels.indexOf(l) !== i), r.id).toEqual([]);
        expect(labels, r.id).not.toContain("Description checked");
        await expect(page.locator(".detail dt", { hasText: /^Description checked$/ })).toHaveCount(1);
      }
    });

    test("a link the catalogue records as dead carries a marker on its button", async ({ page }) => {
      const r = BUNDLE.records.find(x => ((x.link_health || {}).dead || []).some(u => (x.access_links || []).some(l => l.url === u)));
      test.skip(!r, "needs a record with a dead access link");
      await page.goto(URL + "?r=" + r.id);
      await page.waitForSelector('#app[data-state="ready"]');
      const dead = r.link_health.dead;
      for (const l of r.access_links) {
        const button = page.locator(`.link-buttons a[href="${l.url}"]`);
        await expect(button.locator(".pill.attention")).toHaveCount(dead.includes(l.url) ? 1 : 0);
      }
    });

    test("counts in the filter panel are formatted like the summary", async ({ page }) => {
      await open(page);
      const counts = await page.locator("#facets .count").allTextContents();
      expect(counts.length).toBeGreaterThan(0);
      for (const c of counts) expect(c).toBe(Number(c.replace(/[^0-9]/g, "")).toLocaleString("en"));
    });

    test("free-text labels of the detail view are translated", async ({ browser }) => {
      const r = BUNDLE.records.find(x => x.licence);
      test.skip(!r, "needs a record with a licence text");
      const ctx = await browser.newContext({ locale: "de" });
      const page = await ctx.newPage();
      await page.goto(URL + "?r=" + r.id);
      await page.waitForSelector('#app[data-state="ready"]');
      const labels = await facts(page);
      expect(labels).toContain("Lizenz");
      expect(labels).not.toContain("Licence");
      await ctx.close();
    });

    test("a licence stored as an identifier shows in words on the card, not as the bare 'Other'", async ({ page }) => {
      const base = fs.readFileSync(HTML, "utf8");
      test.skip(!base.includes('"licence":"MIT"') || !base.includes('"licence":"GPL-3.0-only"'), "needs the property fixtures");
      const tmp = path.join(require("os").tmpdir(), "slug-licence-" + process.pid + ".html");
      fs.writeFileSync(tmp, base.replace('"licence":"MIT"', '"licence":"custom_active_acceptance"').replace('"licence":"GPL-3.0-only"', '"licence":"cc_zero_1"'));
      try {
        await page.goto("file://" + tmp);
        await page.waitForSelector('#app[data-state="ready"]');
        await page.fill("#q", "model-synth-power-flow");
        await expect(page.locator('.card[data-id="model-synth-power-flow"] .pill.muted').first()).toHaveText("Custom active acceptance");
        await page.fill("#q", "model-synth-traffic-abm");
        await expect(page.locator('.card[data-id="model-synth-traffic-abm"] .pill.muted').first()).toHaveText("CC0");
      } finally { fs.rmSync(tmp, { force: true }); }
    });

    test("the page declares exactly one icon", async ({ page }) => {
      await open(page);
      await expect(page.locator('link[rel~="icon"]')).toHaveCount(1);
    });

    test("vocabulary value names follow the language, the filter still works on the value", async ({ browser }) => {
      const sectors = BUNDLE.facets.find(f => f.id === "sectors");
      const energy = sectors && sectors.values.find(v => v.value === "energy");
      test.skip(!energy || energy.label !== "Energy", "needs the energy sector");
      const ctx = await browser.newContext({ locale: "fr" });
      const page = await ctx.newPage();
      await page.goto(URL);
      await page.waitForSelector('#app[data-state="ready"]');
      const shown = await page.locator("#facet-sectors .value-label, .facet-values .value-label").allTextContents();
      expect(shown).toContain("Énergie");
      expect(shown).not.toContain("Energy");
      await page.goto(URL + "?sectors=energy");
      await page.waitForSelector('#app[data-state="ready"]');
      expect(await page.locator(".chip").first().textContent()).toContain("Énergie");
      await ctx.close();
    });
  });
});

test('English and original titles in list, table, detail and exports',async({page})=>{
 const item=BUNDLE.records.find(r=>r.title_en && r.title_en !== r.name);
 test.skip(!item, 'This build contains only legacy records without English titles');
 await page.goto(URL+'?q='+encodeURIComponent(item.title_en));
 const card=page.locator('.card[data-id="'+item.id+'"]');
 await expect(card.locator('.card-title')).toHaveText(item.title_en);
 await expect(card.locator('.original-title')).toHaveText('Original title: '+item.name);
 await card.click();
 await expect(page.locator('.detail-title')).toHaveText(item.title_en);
 await expect(page.locator('.detail header .original-title')).toHaveText('Original title: '+item.name);
 await page.goto(URL+'?q='+encodeURIComponent(item.name)+'&view=table');
 const row=page.locator('tr[data-id="'+item.id+'"]');
 await expect(row.locator('td.name a')).toHaveText(item.title_en);
 await expect(row.locator('.original-title')).toHaveText('Original title: '+item.name);
 await page.click('#export-toggle');
 const [download]=await Promise.all([page.waitForEvent('download'),page.click('#export-csv')]);
 const csv=fs.readFileSync(await download.path(),'utf8');
 expect(csv).toContain('title_en,name');expect(csv).toContain(item.title_en);expect(csv).toContain(item.name);
 expect(BUNDLE.facets.some(f=>f.id==='title_en')).toBe(false);
});
