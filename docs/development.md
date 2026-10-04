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

`dashboard/build.py` combines records with labels and filter vocabularies, then assembles HTML, CSS and JavaScript. The published build stores catalogue text in numbered parts. The browser loads every part before parsing and displaying results. `engine.js` implements querying independently of the DOM; `app.js` handles controls, rendering, exports and URL state.

There is no backend or resource-download service. Search runs locally in the browser. The dashboard does not send searches to a catalogue server. GitHub Pages serves static files and has its own hosting logs and policies.

## Tests

Small synthetic records exercise filter semantics, URL state, exports, responsive layouts and accessibility. Property tests compare randomly combined filters against a direct reference query. Python tests check vocabulary mappings, record-title preservation and update conflicts. Full-catalogue browser checks supplement these tests before a release.

For reproducible builds, use the same records, dependency locks and explicit date: `make build DATE=2026-10-04`. Dependencies and generated files must not refer to another local repository.

For a release-sized check, run `npm --prefix dashboard run test:full` after `make build`. It serves the site at the same project subpath used on GitHub Pages and checks record counts, reference queries, URL state, exports, record details, phone layout, accessibility and failure of a data part. It writes measurements and screenshots to `.local/` and refreshes the README screenshot. Set `CATALOGUE_URL` to test a deployed copy of the same snapshot.
