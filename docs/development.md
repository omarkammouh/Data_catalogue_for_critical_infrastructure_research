# Development

## Install

Use Python 3.12 and Node.js 22 on Linux or macOS. Work from the repository root.

```sh
python3 -m venv .venv
source .venv/bin/activate
make install
```

`make install` installs pinned Python dependencies, the locked dashboard dependencies and Chromium for browser tests. On Linux CI, use `npx playwright install --with-deps chromium` from `dashboard/` to include browser system libraries.

## Commands

| Command | Result |
|---|---|
| `make validate` | Validate all records and public metadata |
| `make test` | Run Python tests and reference-query filter tests |
| `make test-browser` | Run fixture browser tests, including accessibility |
| `make build` | Rebuild the complete static dashboard |
| `make serve` | Serve it at `http://127.0.0.1:8789/` |
| `make release` | Create compressed JSON/CSV exports and checksums |

Generated outputs stay in ignored directories. Do not edit compiled data or site output. Edit individual records or dashboard source and rebuild. `make build` always reads the individual records, so stale compiled metadata cannot hide a record edit.

## Architecture

Individual JSON records in `catalog/<type>/` are the editable data source. The JSON Schema describes record structure and the YAML vocabularies define permitted classifications. `pipeline/validate.py` checks these rules and cross-record references. `pipeline/compile.py` provides JSON and SQLite compilation for local use.

`dashboard/build.py` combines records with labels and filter vocabularies, then assembles HTML, CSS and JavaScript. The published build uses `--lazy-details`. `mobile.py` writes an index with every record identity, filter value and searchable word. Repeated card values and filter value sets use shared dictionaries. Search word references and filter columns use variable-length integers on disk and typed arrays in the browser. Each index part is valid JSON, loaded and decoded with at most two concurrent requests. Results appear only after all identities are loaded and reconciled with the total.

Complete records are stored in content-addressed batches of 128. Opening a record fetches its batch; the browser caches at most two batches. Exports fetch each selected batch once, retain selection order and include the complete records. The original metadata is preserved. Cards show a short description preview. The inline build remains available for small offline snapshots and reference tests.

`engine.js` implements querying independently of the DOM; `app.js` handles controls, rendering, exports and URL state. Compact-mode search computes the same substring and padded-trigram scores from shared words for each query. It does not build the large persistent trigram-to-record index. Large filter lists create controls only for visible values; searches examine all values, and the show-more control adds 200 values per step.

There is no backend or resource-download service. Search runs locally in the browser. The dashboard does not send searches to a catalogue server. GitHub Pages serves static files and has its own hosting logs and policies.

## Tests

Small synthetic records exercise filter semantics, URL state, exports, responsive layouts and accessibility. Property tests compare randomly combined filters against a direct reference query. Python tests check vocabulary mappings, record-title preservation and update conflicts. Full-catalogue browser checks supplement these tests before a release.

For reproducible builds, use the same records, dependency locks and explicit date: `make build DATE=2026-10-04`. Dependencies and generated files must not refer to another local repository.

For a release-sized check, run `npm --prefix dashboard run test:full` after `make build`. It serves the site at the same project subpath used on GitHub Pages and checks record counts, reference queries, URL state, exports, record details, phone layout, accessibility and failure of a data part. Chromium runs with a 192 MB JavaScript heap limit. The test measures initial download size and heap use and verifies that no detail batches load at startup. This checks a constrained desktop browser; it does not replace testing on a physical iPhone. It writes measurements and screenshots to `.local/` and refreshes the README screenshot. Set `CATALOGUE_URL` to test a deployed copy of the same snapshot.
