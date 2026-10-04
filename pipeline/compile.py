#!/usr/bin/env python3
"""Compile the record files into ``catalog.json`` and ``catalog.sqlite``.

The compiled catalogue is what the dashboard and the statistics read. It is
regenerated from the record files at every checkpoint and never edited by hand.

``catalog.json`` holds a header (build date, schema version, record counts by
type, sector group, sector, facet and country, a ``facets`` block with value
counts for every list-valued vocabulary field, and the full vocabulary) followed
by the records, each exactly as stored on disk. ``catalog.sqlite`` holds a
``records`` table (one row per record, scalar fields as columns plus the whole
record as JSON) and one-to-many tables for sectors, families, kinds, countries,
continents, simulation uses, access links, discovery routes, tags, languages,
formats and related ids, so that any facet can be queried with a join.

Determinism: records are ordered by (type, id), JSON keys are sorted, the
SQLite file is rebuilt from scratch with rows inserted in that order, and the
build date is the ``--date`` argument, else the latest ``date_verified`` or
``date_catalogued`` among the records, else today. Two builds of the same
records with the same date produce byte-identical ``catalog.json``.

Records that fail record-level validation (schema, vocabulary, references)
block the build unless ``--skip-validation`` is given; description warnings do not.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import RECORD_TYPES, Paths, RecordFile, Vocab, add_common_args, dump_json, load_vocab, parse_date, today, valid_records
from validate import Validator
import vocab_map

LIST_FACETS = (
    "sectors", "data_family", "data_kind", "model_kind", "platform_kind", "case_study_kind", "hazards", "simulation_uses", "continents",
    "countries", "languages", "formats", "language", "interfaces", "deployment", "tags", "supported_sectors", "licence_type", "licence_name",
)
SCALAR_FACETS = ("type", "cost", "access_restrictions", "geographic_scope", "maturity", "provider", "open_source", "update_frequency",
                 "temporal_resolution_class", "spatial_resolution_class")


def build_date(records: list[RecordFile], explicit: str | None) -> str:
    """``--date`` if given; else the newest date_verified/date_catalogued; else today."""
    if explicit:
        return explicit
    dates = [d for r in records for d in (parse_date(r.data.get("date_verified")), parse_date(r.data.get("date_catalogued"))) if d]
    return max(dates).isoformat() if dates else today()


def counts(records: list[RecordFile], vocab: Vocab) -> dict[str, Any]:
    """Record counts by type, sector group, sector, facet value and country."""
    by_type = Counter(r.type for r in records)
    by_group: Counter[str] = Counter()
    by_sector: Counter[str] = Counter()
    by_facet: dict[str, Counter[str]] = {t: Counter() for t in RECORD_TYPES}
    by_country: Counter[str] = Counter()
    for r in records:
        groups = {vocab.sector_group(s) for s in r.sectors()}
        for g in groups:
            if g:
                by_group[g] += 1
        for s in {x for sec in r.sectors() for x in vocab.expand_sector(sec)}:
            by_sector[s] += 1
        for f in set(r.facets(vocab)):
            by_facet[r.type][f] += 1
        for c in set(r.data.get("countries", []) or []):
            by_country[c] += 1
    return {
        "total": len(records),
        "by_type": {t: by_type.get(t, 0) for t in RECORD_TYPES},
        "by_sector_group": dict(sorted(by_group.items())),
        "by_sector": dict(sorted(by_sector.items())),
        "by_facet": {t: dict(sorted(c.items())) for t, c in by_facet.items()},
        "by_country": dict(sorted(by_country.items())),
    }


def facets(records: list[RecordFile]) -> dict[str, dict[str, int]]:
    """Value counts for every filterable field, for the dashboard's facet panel.

    Fields with a filter vocabulary (``vocab/vocabulary.yaml``) are counted after normalisation through
    ``vocab_map``, as the dashboard shows them; the records themselves are written exactly as on disk.
    """
    out: dict[str, Counter[str]] = {}
    for r in records:
        data = vocab_map.apply_to_record(r.data)
        for field in LIST_FACETS:
            values = data.get(field, []) or []
            for value in values if isinstance(values, list) else [values]:
                out.setdefault(field, Counter())[str(value)] += 1
        for field in SCALAR_FACETS:
            if field in data and data[field] not in (None, ""):
                out.setdefault(field, Counter())[str(data[field])] += 1
        for link in r.data.get("access_links", []) or []:
            if isinstance(link, dict) and link.get("kind"):
                out.setdefault("access_link_kinds", Counter())[str(link["kind"])] += 1
        for entry in r.data.get("discovery_routes", []) or []:
            if isinstance(entry, dict) and entry.get("route"):
                out.setdefault("discovery_routes", Counter())[str(entry["route"])] += 1
    return {field: dict(sorted(c.items())) for field, c in sorted(out.items())}


def write_json(records: list[RecordFile], vocab: Vocab, date: str, path: Path) -> dict[str, Any]:
    header = {
        "built": date,
        "schema_version": vocab.version,
        "vocab_updated": str(vocab.updated),
        "counts": counts(records, vocab),
        "facets": facets(records),
        "vocab": vocab.raw,
    }
    payload = dict(header)
    payload["records"] = [r.data for r in records]
    dump_json(payload, path, sort_keys=True)
    return header


SQL_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE records (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, provider TEXT, description TEXT, homepage TEXT,
    licence TEXT, cost TEXT, access_restrictions TEXT, access_note TEXT, geographic_scope TEXT, maturity TEXT,
    last_updated TEXT, date_catalogued TEXT, date_verified TEXT, description_checked TEXT, notes TEXT,
    repository TEXT, citation TEXT, open_source INTEGER, spatial_resolution TEXT, temporal_coverage TEXT,
    temporal_resolution TEXT, update_frequency TEXT, link_health_checked TEXT, link_health_dead INTEGER,
    json TEXT NOT NULL, title_en TEXT
);
CREATE TABLE record_sectors (record_id TEXT NOT NULL, sector TEXT NOT NULL, sector_group TEXT NOT NULL, as_written TEXT NOT NULL);
CREATE TABLE record_families (record_id TEXT NOT NULL, family TEXT NOT NULL);
CREATE TABLE record_kinds (record_id TEXT NOT NULL, axis TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE record_countries (record_id TEXT NOT NULL, country TEXT NOT NULL);
CREATE TABLE record_continents (record_id TEXT NOT NULL, continent TEXT NOT NULL);
CREATE TABLE record_regions (record_id TEXT NOT NULL, region TEXT NOT NULL);
CREATE TABLE record_uses (record_id TEXT NOT NULL, use TEXT NOT NULL);
CREATE TABLE record_links (record_id TEXT NOT NULL, position INTEGER NOT NULL, label TEXT, url TEXT NOT NULL, kind TEXT, note TEXT);
CREATE TABLE record_routes (record_id TEXT NOT NULL, route TEXT NOT NULL, family TEXT, source TEXT, query TEXT, date TEXT);
CREATE TABLE record_tags (record_id TEXT NOT NULL, tag TEXT NOT NULL);
CREATE TABLE record_languages (record_id TEXT NOT NULL, language TEXT NOT NULL);
CREATE TABLE record_formats (record_id TEXT NOT NULL, format TEXT NOT NULL);
CREATE TABLE record_related (record_id TEXT NOT NULL, related_id TEXT NOT NULL);
CREATE TABLE record_sources (record_id TEXT NOT NULL, url TEXT NOT NULL, accessed TEXT, note TEXT);
CREATE TABLE record_hazards (record_id TEXT NOT NULL, hazard TEXT NOT NULL);
CREATE TABLE record_resources_used (record_id TEXT NOT NULL, resource TEXT NOT NULL);
CREATE INDEX idx_sectors ON record_sectors (sector);
CREATE INDEX idx_families ON record_families (family);
CREATE INDEX idx_kinds ON record_kinds (axis, kind);
CREATE INDEX idx_countries ON record_countries (country);
CREATE INDEX idx_uses ON record_uses (use);
CREATE INDEX idx_routes ON record_routes (route);
"""


def write_sqlite(records: list[RecordFile], vocab: Vocab, date: str, path: Path) -> None:
    """Rebuild the SQLite catalogue from scratch (delete, create, insert in sorted order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(SQL_SCHEMA)
        con.executemany("INSERT INTO meta VALUES (?, ?)", [("built", date), ("schema_version", str(vocab.version)), ("records", str(len(records)))])
        for r in records:
            d = r.data
            health = d.get("link_health") or {}
            con.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.id, r.type, r.name, r.provider, d.get("description"), d.get("homepage"), d.get("licence"), d.get("cost"),
                    d.get("access_restrictions"), d.get("access_note"), d.get("geographic_scope"), d.get("maturity"), d.get("last_updated"),
                    d.get("date_catalogued"), d.get("date_verified"), d.get("description_checked"), d.get("notes"), d.get("repository"),
                    d.get("citation"), None if d.get("open_source") is None else int(bool(d.get("open_source"))), d.get("spatial_resolution"),
                    d.get("temporal_coverage"), d.get("temporal_resolution"), d.get("update_frequency"), health.get("checked"),
                    len(health.get("dead", []) or []) if health else None, json.dumps(d, ensure_ascii=False, sort_keys=True), d.get("title_en"),
                ),
            )
            for sector in r.sectors():
                for expanded in vocab.expand_sector(sector) or [sector]:
                    con.execute("INSERT INTO record_sectors VALUES (?,?,?,?)", (r.id, expanded, vocab.sector_group(expanded) or "", sector))
            for fam in d.get("data_family", []) or []:
                con.execute("INSERT INTO record_families VALUES (?,?)", (r.id, fam))
            for axis in ("data_kind", "model_kind", "platform_kind", "case_study_kind"):
                for kind in d.get(axis, []) or []:
                    con.execute("INSERT INTO record_kinds VALUES (?,?,?)", (r.id, axis, kind))
            for c in d.get("countries", []) or []:
                con.execute("INSERT INTO record_countries VALUES (?,?)", (r.id, c))
            for c in d.get("continents", []) or []:
                con.execute("INSERT INTO record_continents VALUES (?,?)", (r.id, c))
            for c in d.get("regions", []) or []:
                con.execute("INSERT INTO record_regions VALUES (?,?)", (r.id, c))
            for u in d.get("simulation_uses", []) or []:
                con.execute("INSERT INTO record_uses VALUES (?,?)", (r.id, u))
            for i, link in enumerate(d.get("access_links", []) or []):
                if isinstance(link, dict):
                    con.execute("INSERT INTO record_links VALUES (?,?,?,?,?,?)", (r.id, i, link.get("label"), link.get("url", ""), link.get("kind"), link.get("note")))
            for entry in d.get("discovery_routes", []) or []:
                if isinstance(entry, dict):
                    con.execute("INSERT INTO record_routes VALUES (?,?,?,?,?,?)", (r.id, entry.get("route", ""), vocab.route_family(entry.get("route")), entry.get("source"), entry.get("query"), entry.get("date")))
            for t in d.get("tags", []) or []:
                con.execute("INSERT INTO record_tags VALUES (?,?)", (r.id, t))
            for lang in d.get("languages", []) or []:
                con.execute("INSERT INTO record_languages VALUES (?,?)", (r.id, lang))
            for f in d.get("formats", []) or []:
                con.execute("INSERT INTO record_formats VALUES (?,?)", (r.id, f))
            for rel in d.get("related_ids", []) or []:
                con.execute("INSERT INTO record_related VALUES (?,?)", (r.id, rel))
            for hz in d.get("hazards", []) or []:
                con.execute("INSERT INTO record_hazards VALUES (?,?)", (r.id, hz))
            for res in d.get("resources_used", []) or []:
                con.execute("INSERT INTO record_resources_used VALUES (?,?)", (r.id, res))
            for src in d.get("sources", []) or []:
                if isinstance(src, dict):
                    con.execute("INSERT INTO record_sources VALUES (?,?,?,?)", (r.id, src.get("url", ""), src.get("accessed"), src.get("note")))
        con.commit()
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(parser)
    parser.add_argument("--date", default=None, help="build date (YYYY-MM-DD); default: newest record date, else today")
    parser.add_argument("--json-out", default=None, help="output path for catalog.json (default: <project>/catalog/catalog.json)")
    parser.add_argument("--sqlite-out", default=None, help="output path for catalog.sqlite (default: <project>/catalog/catalog.sqlite)")
    parser.add_argument("--skip-validation", action="store_true", help="compile even when records have validation errors")
    args = parser.parse_args(argv)

    paths = Paths.from_args(args.project, args.schema_dir)
    vocab = load_vocab(paths)
    if not args.skip_validation:
        issues = Validator(paths).run(check_drift=False)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            for issue in errors:
                print(f"  {issue}", file=sys.stderr)
            print(f"compile: refusing to build, {len(errors)} validation errors (use --skip-validation to override)", file=sys.stderr)
            return 1
    records = valid_records(paths.catalog_dir)
    date = build_date(records, args.date)
    json_out = Path(args.json_out) if args.json_out else paths.catalog_json
    sqlite_out = Path(args.sqlite_out) if args.sqlite_out else paths.catalog_sqlite
    header = write_json(records, vocab, date, json_out)
    write_sqlite(records, vocab, date, sqlite_out)
    c = header["counts"]
    print(f"compile: {c['total']} records ({', '.join(f'{k} {v}' for k, v in c['by_type'].items())}), built {date}")
    print(f"compile: wrote {json_out} and {sqlite_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
