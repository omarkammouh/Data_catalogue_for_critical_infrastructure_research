const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const HTML = process.env.DASHBOARD_HTML || path.resolve(__dirname, '../dist-test/index.html');
const bundle = JSON.parse(fs.readFileSync(path.join(path.dirname(HTML), 'bundle.json'), 'utf8'));
const records = bundle.records;
const selected = ids => records.filter(r => ids.every(id => (r.catalogues || []).includes(id)));

test('Catalogues combines memberships, restores the URL and exports the selection', async ({ page }) => {
  test.skip(!records.some(r => r.id === 'data-synth-grid-topology'), 'Uses synthetic membership fixtures');
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file://' + HTML);
  await page.waitForSelector('#app[data-state="ready"]');
  const facet = page.locator('details[data-facet="catalogues"]');
  await expect(facet.locator('summary')).toContainText('Catalogues');
  if (!(await facet.evaluate(el => el.open))) await facet.locator('summary').click();
  await facet.locator('input[data-value="mobility-database"]').check();
  await expect(page).toHaveURL(/catalogues=mobility-database/);
  const mobilityCount = selected(['mobility-database']).length;
  await expect(page.locator('#summary')).toContainText(`${mobilityCount} of ${records.length}`);
  await page.reload();
  await page.waitForSelector('#app[data-state="ready"]');
  await expect(page.locator('#summary')).toContainText(`${mobilityCount} of ${records.length}`);
  if (!(await facet.evaluate(el => el.open))) await facet.locator('summary').click();
  await facet.locator('input[data-value="hdx"]').check();
  const union = records.filter(r => (r.catalogues || []).some(id => ['hdx', 'mobility-database'].includes(id))).length;
  await expect(page.locator('#summary')).toContainText(`${union} of ${records.length}`);
  // Deep links use the same all-of control as the other multi-value filters.
  await page.goto('file://' + HTML + '?catalogues=mobility-database,hdx&catalogues.all=1');
  await page.waitForSelector('#app[data-state="ready"]');
  await expect(page.locator('#summary')).toContainText(`${selected(['mobility-database', 'hdx']).length} of ${records.length}`);
  await page.click('#export-toggle');
  const downloadPromise = page.waitForEvent('download');
  await page.click('#export-json');
  const download = await downloadPromise;
  const exported = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
  expect(exported.records.map(r => r.id)).toEqual(['data-synth-grid-topology']);
  expect(exported.records[0].catalogues).toEqual(['hdx', 'mobility-database']);
  expect(exported.records[0].catalogue_membership_evidence['mobility-database']).toBeTruthy();
  expect(errors).toEqual([]);
});
