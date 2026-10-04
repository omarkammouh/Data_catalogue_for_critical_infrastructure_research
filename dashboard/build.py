#!/usr/bin/env python3
"""Build the catalogue dashboard: one self-contained ``dist/index.html``.

The dashboard is a static page. This script reads the compiled catalogue
(``catalog/catalog.json``, or the record files directly when the
compiled file is absent) and the controlled vocabularies
(``schema/vocab.yaml``), derives the facet definitions, and inlines
records, facets, CSS and JavaScript into a single HTML file that makes no
network request. The page therefore works from ``file://``, from any static
host, and offline.

How facets are generated (the rule a methods section can cite)
--------------------------------------------------------------

A *facet* is one filterable axis of the catalogue. Facets are not written by
hand; they are derived from two sources at build time:

1. ``FACET_TABLE`` below, a small table that gives, per field, only a label, a
   facet kind (``hierarchy``, ``multi``, ``range`` or ``text``), a panel group
   and the path in the record that yields the values. It carries no values.
2. The vocabularies in ``vocab.yaml`` and the values actually present in the
   records. For every facet the value list is the union of the vocabulary
   values (so an unused vocabulary value appears, with a count of zero and
   disabled) and the values found in the data (so a value used before it was
   added to the vocabulary still appears).

Any further field that holds strings or lists of strings in at least one
record, is not prose (``EXCLUDED_FIELDS``) and is not already in the table,
becomes a ``multi`` facet automatically with a humanised label. A field added
to the schema therefore appears as a facet at the next build with no change
to this script.

Hierarchies come from the vocabulary: sectors (group > sector), data families
(family group > family) and discovery routes (route family > route class).
For a hierarchy facet a record's values are expanded upwards to the parent
and, for a bare parent value, downwards to every child, so selecting a group
matches every record in the group, and a record that spans a whole group
matches every child.

Range facets hold numbers: the year part of the three dates a record
carries (catalogued, verified, last updated), every year of the period a
record covers (``temporal_coverage_years``), and, on a logarithmic scale, size
in bytes and spatial resolution in metres (added by the audit on 2026-09-26).
They are filtered with an inclusive ``min..max`` interval.

The free-text facet searches a small set of prose fields with a trigram
index (see ``src/engine.js``).

Output
------

``dist/index.html`` (the page) and ``dist/bundle.json`` (the same records,
facets and metadata as plain JSON, used by the tests and by anyone who wants
the derived facets without the page). The build is deterministic: the same
inputs produce byte-identical outputs.

Usage: ``python3 build.py [--project DIR] [--schema-dir DIR] [--out FILE] [--data-file NAME] [--no-bundle]``.

The build stops with a message, and a non-zero exit, when a record is malformed (not an object, no id or
name, a duplicate id, the wrong type for its folder, a list field that is not a list), when
``catalog/catalog.json`` no longer matches the record files, or when ``pycountry`` is missing (country and
language labels would silently be bare codes).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

try:  # optional: nicer country and language labels
    import pycountry
except ImportError:  # pragma: no cover
    pycountry = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import vocab_map  # noqa: E402  (the filter vocabularies and the mapping of raw values onto them)
DEFAULT_PROJECT = REPO_ROOT
RECORD_TYPES = ("data", "model", "platform", "case_study")

# --------------------------------------------------------------------------- #
# The facet table: labels, kinds and paths only. No values live here.
# --------------------------------------------------------------------------- #

#: Fields that are prose or identifiers and must never become value facets.
#: They are searched by the free-text facet instead (where listed in TEXT_FIELDS).
EXCLUDED_FIELDS = frozenset({
    "id", "name", "title_en", "provider", "description", "homepage", "notes", "access_note", "citation", "repository",
    "schema_summary", "access_links", "sources", "discovery_routes", "dedupe_keys", "link_health", "related_ids",
    "date_catalogued", "date_verified", "description_checked", "last_updated", "open_source", "size",
    # Free text kept for the detail view; the filters read their controlled form instead (vocab_map.py, 2026-09-29):
    # licence -> licence_type and licence_name, spatial_resolution -> spatial_resolution_class,
    # temporal_resolution -> temporal_resolution_class.
    "licence", "spatial_resolution", "temporal_resolution",
    # Prose, names or record references that became "Other" facets with thousands of one-off values
    # (tags alone had 15,000); they are shown in the detail view, and tags are searched by the text box.
    "tags", "inputs", "outputs", "outcomes", "resources_used", "hosted_models", "runs_on", "validated_on",
    "organisations", "study_period", "temporal_coverage", "interoperability", "crs",
})

#: Fields the free-text facet searches, in the order they are concatenated.
TEXT_FIELDS = ("title_en", "name", "provider", "description", "tags", "id", "notes", "regions")

#: One row per facet: id, label, kind, panel group, value path, options.
#: ``path`` uses ``a.b`` for nesting and ``a[].b`` to iterate a list.
#: ``transform`` names a derivation that both the JS engine and the Python
#: reference implement: ``year`` (first four digits of a date) or ``bool``.
#: ``vocab`` names the vocabulary that supplies the canonical value list.
#: ``hierarchy`` names the vocabulary hierarchy (parents and children).
FACET_TABLE: list[dict[str, Any]] = [
    {"id": "type", "label": "Type", "kind": "multi", "group": "Scope", "path": "type", "vocab": "types"},
    {"id": "sectors", "label": "Sector", "kind": "hierarchy", "group": "Scope", "path": "sectors", "hierarchy": "sectors"},
    {"id": "supported_sectors", "label": "Supported sectors", "kind": "hierarchy", "group": "Scope", "path": "supported_sectors", "hierarchy": "sectors"},
    {"id": "data_family", "label": "Data family", "kind": "hierarchy", "group": "Classification", "path": "data_family", "hierarchy": "data_families"},
    {"id": "data_kind", "label": "Data kind", "kind": "multi", "group": "Classification", "path": "data_kind", "vocab": "data_kinds"},
    {"id": "model_kind", "label": "Model kind", "kind": "multi", "group": "Classification", "path": "model_kind", "vocab": "model_kinds"},
    {"id": "platform_kind", "label": "Platform kind", "kind": "multi", "group": "Classification", "path": "platform_kind", "vocab": "platform_kinds"},
    {"id": "case_study_kind", "label": "Case study purpose", "kind": "multi", "group": "Classification", "path": "case_study_kind", "vocab": "case_study_kinds"},
    {"id": "hazards", "label": "Hazard", "kind": "multi", "group": "Classification", "path": "hazards", "vocab": "hazard_types"},
    {"id": "simulation_uses", "label": "Simulation use", "kind": "multi", "group": "Classification", "path": "simulation_uses", "vocab": "simulation_uses"},
    {"id": "geographic_scope", "label": "Geographic scope", "kind": "multi", "group": "Geography", "path": "geographic_scope", "vocab": "geographic_scope"},
    {"id": "continents", "label": "Continent", "kind": "multi", "group": "Geography", "path": "continents", "vocab": "continents"},
    {"id": "countries", "label": "Country", "kind": "multi", "group": "Geography", "path": "countries", "labels": "country"},
    {"id": "regions", "label": "Region or city", "kind": "multi", "group": "Geography", "path": "regions"},
    # Filter vocabularies (pipeline/vocab, 2026-09-29): records are normalised through vocab_map before counting,
    # so these facets hold short controlled lists instead of every spelling found in the records.
    {"id": "licence", "label": "Licence type", "kind": "multi", "group": "Access", "path": "licence_type", "vocab": "filter:licence"},
    {"id": "licence_name", "label": "Standard licence", "kind": "multi", "group": "Access", "path": "licence_name", "vocab": "filter:licence_name"},
    {"id": "cost", "label": "Cost", "kind": "multi", "group": "Access", "path": "cost", "vocab": "cost"},
    {"id": "access_restrictions", "label": "Access restrictions", "kind": "multi", "group": "Access", "path": "access_restrictions", "vocab": "access_restrictions"},
    {"id": "open_source", "label": "Open source", "kind": "multi", "group": "Access", "path": "open_source", "transform": "bool"},
    {"id": "access_link_kinds", "label": "Link kind", "kind": "multi", "group": "Access", "path": "access_links[].kind", "vocab": "access_link_kinds"},
    {"id": "formats", "label": "Format", "kind": "multi", "group": "Technical", "path": "formats", "vocab": "filter:formats"},
    {"id": "language", "label": "Programming language", "kind": "multi", "group": "Technical", "path": "language", "vocab": "filter:language"},
    {"id": "languages", "label": "Language", "kind": "multi", "group": "Technical", "path": "languages", "labels": "language"},
    {"id": "update_frequency", "label": "Update frequency", "kind": "multi", "group": "Technical", "path": "update_frequency", "vocab": "filter:update_frequency"},
    {"id": "temporal_resolution", "label": "Time step", "kind": "multi", "group": "Technical", "path": "temporal_resolution_class", "vocab": "filter:temporal_resolution"},
    {"id": "spatial_resolution", "label": "Spatial resolution", "kind": "multi", "group": "Technical", "path": "spatial_resolution_class", "vocab": "filter:spatial_resolution"},
    {"id": "interfaces", "label": "Interface", "kind": "multi", "group": "Technical", "path": "interfaces", "vocab": "filter:interfaces"},
    {"id": "deployment", "label": "Deployment", "kind": "multi", "group": "Technical", "path": "deployment", "vocab": "filter:deployment"},
    {"id": "maturity", "label": "Maturity", "kind": "multi", "group": "Technical", "path": "maturity", "vocab": "filter:maturity"},
    # Range facets beyond the record dates (audit 2026-09-26; roadmap: "Range facets exist for dates, size and resolution").
    # They read the optional structured fields; the free-text fields stay what the detail view shows.
    {"id": "coverage_years", "label": "Years covered", "kind": "range", "group": "Technical", "path": "temporal_coverage_years", "transform": "year_span"},
    {"id": "size_bytes", "label": "Size", "kind": "range", "group": "Technical", "path": "size_bytes", "transform": "number", "scale": "log10", "unit": "bytes"},
    {"id": "resolution_m", "label": "Resolution in metres", "kind": "range", "group": "Technical", "path": "spatial_resolution_m", "transform": "number", "scale": "log10", "unit": "metres"},
    {"id": "provider", "label": "Provider", "kind": "multi", "group": "Provenance", "path": "provider"},
    {"id": "discovery_route", "label": "Discovery route", "kind": "hierarchy", "group": "Provenance", "path": "discovery_routes[].route", "hierarchy": "route_classes"},
    {"id": "link_health", "label": "Link health", "kind": "multi", "group": "Provenance", "path": "link_health", "transform": "link_status",
     "value_labels": {"all links alive": "All links alive", "some links unverified": "Some links unverified", "dead links": "Dead links", "not checked": "Not checked"}},
    {"id": "content_check", "label": "Description checked", "kind": "multi", "group": "Provenance", "path": "description_checked", "transform": "presence",
     "value_labels": {"checked": "Checked on the provider's pages", "not checked": "Not checked yet"}},
    {"id": "year_catalogued", "label": "Year catalogued", "kind": "range", "group": "Provenance", "path": "date_catalogued", "transform": "year"},
    {"id": "year_verified", "label": "Year links checked", "kind": "range", "group": "Provenance", "path": "date_verified", "transform": "year"},
    {"id": "year_updated", "label": "Year last updated", "kind": "range", "group": "Provenance", "path": "last_updated", "transform": "year"},
    {"id": "q", "label": "Search", "kind": "text", "group": "Search", "fields": list(TEXT_FIELDS)},
]

PANEL_GROUP_ORDER = ("Scope", "Classification", "Geography", "Access", "Technical", "Provenance", "Other")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_vocab(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise SystemExit(f"{path}: vocabulary must be a mapping")
    return raw


def tidy_whitespace(record: dict[str, Any]) -> dict[str, Any]:
    """Provider and place names with padding or doubled spaces (104 and 58 values on 2026-10-01) become separate filter values
    next to their trimmed twins (11 and 2 of them), so the panel listed the same provider twice. Collapse the whitespace; the
    record files are not touched."""
    out = dict(record)
    if isinstance(out.get("provider"), str):
        out["provider"] = " ".join(out["provider"].split())
    if isinstance(out.get("regions"), list):
        seen: list[Any] = []
        for item in out["regions"]:
            item = " ".join(item.split()) if isinstance(item, str) else item
            if item not in seen:
                seen.append(item)
        out["regions"] = seen
    return out


LIST_FIELDS = ("sectors", "countries", "languages", "regions", "tags", "access_links", "sources", "related_ids", "organisations")


def record_problems(records: list[Any], origins: list[str]) -> list[str]:
    """Structural faults that would drop, merge or mis-render a record in the page.

    The pipeline's validate.py checks the schema; this is the build's own guard so that a malformed
    record stops the build instead of disappearing or showing wrongly (round 2 check B-4, 2026-10-01).
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    for record, origin in zip(records, origins):
        if not isinstance(record, dict):
            problems.append(f"{origin}: the record is not a JSON object")
            continue
        rid = record.get("id")
        if not isinstance(rid, str) or not rid.strip():
            problems.append(f"{origin}: no id")
        elif rid in seen:
            problems.append(f"{origin}: id {rid!r} is also used by {seen[rid]}")
        else:
            seen[rid] = origin
        if not isinstance(record.get("name"), str) or not record["name"].strip():
            problems.append(f"{origin}: no name")
        if record.get("type") not in RECORD_TYPES:
            problems.append(f"{origin}: type {record.get('type')!r} is not one of {', '.join(RECORD_TYPES)}")
        for key in LIST_FIELDS:
            if key in record and not isinstance(record[key], list):
                problems.append(f"{origin}: {key} must be a list, found {type(record[key]).__name__}")
    return problems


def load_records(project: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Records and header from ``catalog/catalog.json``, else from the record files.

    Records are always returned sorted by ``(type, id)`` so that the build is
    deterministic whichever source was used. A record that is malformed, nameless, a
    duplicate or filed under the wrong type stops the build with the list of faults, and a compiled
    catalogue that no longer matches the record files is refused (it would silently show old data).
    """
    compiled = project / "catalog" / "catalog.json"
    on_disk = {rtype: sorted((project / "catalog" / rtype).glob("*.json")) for rtype in RECORD_TYPES}
    problems: list[str] = []
    if compiled.exists():
        with compiled.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        records = payload.get("records", [])
        origins = [f"{compiled.name}[{i}]" for i in range(len(records))]
        files = sum(len(v) for v in on_disk.values())
        if files and files != len(records):
            raise SystemExit(f"{compiled} holds {len(records)} records but {files} record files exist: the compiled catalogue is out of date. "
                             f"Run `python3 pipeline/compile.py` and build again.")
        newest = max((f.stat().st_mtime for v in on_disk.values() for f in v), default=0)
        if newest > compiled.stat().st_mtime + 1:
            print(f"warning: a record file is newer than {compiled.name}; run `python3 pipeline/compile.py` if records changed since it was built", file=sys.stderr)
        header = {k: v for k, v in payload.items() if k not in ("records", "vocab")}
        header["source"] = str(compiled.relative_to(project.parent)) if compiled.is_relative_to(project.parent) else str(compiled)
    else:
        records, origins = [], []
        for rtype in RECORD_TYPES:
            for path in on_disk[rtype]:
                origin = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
                try:
                    with path.open(encoding="utf-8") as fh:
                        data = json.load(fh)
                except ValueError as err:
                    raise SystemExit(f"{path}: not valid JSON ({err})")
                if isinstance(data, dict):
                    data.setdefault("type", rtype)
                    if data["type"] != rtype:
                        problems.append(f"{origin}: filed under {rtype}/ but its type is {data['type']!r}")
                records.append(data)
                origins.append(origin)
        header = {"source": "record files", "built": None}
    problems += record_problems(records, origins)
    if problems:
        shown = "\n  ".join(problems[:25])
        raise SystemExit(f"{len(problems)} malformed record(s); the build stops rather than drop or mis-show them:\n  {shown}" + ("\n  ..." if len(problems) > 25 else ""))
    records.sort(key=lambda r: (str(r.get("type", "")), str(r.get("id", ""))))
    return records, header


# --------------------------------------------------------------------------- #
# Value extraction (mirrors engine.js extract() and the Python reference)
# --------------------------------------------------------------------------- #

def walk_path(obj: Any, path: str) -> list[Any]:
    """Every value at ``path`` in ``obj``: ``a.b`` nests, ``a[]`` iterates a list."""
    parts = path.split(".") if path else []
    current: list[Any] = [obj]
    for part in parts:
        nxt: list[Any] = []
        iterate = part.endswith("[]")
        key = part[:-2] if iterate else part
        for item in current:
            if not isinstance(item, dict) or key not in item:
                continue
            value = item[key]
            if iterate:
                if isinstance(value, list):
                    nxt.extend(value)
            else:
                nxt.append(value)
        current = nxt
    return current


def link_status(health: Any) -> str:
    """Link-health class of a record (same rule in engine.js and the property test).

    ``dead links`` when any link answered 404 or 410; ``some links unverified`` when the
    last check left links without a definitive result; ``all links alive`` otherwise;
    ``not checked`` when the record has never been checked. Before the audit
    (2026-09-24) unverified links were ignored, so a record whose homepage could not
    be reached showed as simply "checked", and records without ``link_health`` had no
    value at all and could not be filtered.
    """
    if not isinstance(health, dict) or not health.get("checked"):
        return "not checked"
    if health.get("dead"):
        return "dead links"
    if health.get("unverified"):
        return "some links unverified"
    return "all links alive"


MAX_SPAN = 1000  # same rule as engine.js; historical catalogues such as Wikimpacts start around 1100
"""A ``year_span`` longer than this is a data error and is ignored (same constant in engine.js)."""


def year_of(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    m = re.match(r"^\s*(\d{4})", str(value)) if value not in (None, "") else None
    return int(m.group(1)) if m else None


def apply_transform(values: list[Any], transform: str | None, facet: dict[str, Any] | None = None) -> list[Any]:
    """Turn raw values into facet values; the same rules exist in engine.js."""
    out: list[Any] = []
    for value in values:
        if transform == "year_span":
            if not isinstance(value, dict):
                continue
            a = year_of(value.get("start"))
            b = ((facet or {}).get("open_end", a) if value.get("end") is None else year_of(value.get("end")))
            if a is None or b is None or b < a or b - a > MAX_SPAN:
                continue
            out.extend(range(a, b + 1))
        elif transform == "number":
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf"):
                out.append(int(value) if isinstance(value, float) and value.is_integer() else value)
        elif transform == "presence":
            if value not in (None, ""):
                out.append("checked")
        elif transform == "year":
            m = re.match(r"^\s*(\d{4})", str(value)) if value not in (None, "") else None
            if m:
                out.append(int(m.group(1)))
        elif transform == "bool":
            if isinstance(value, bool):
                out.append("yes" if value else "no")
        elif transform == "link_status":
            if isinstance(value, dict):
                out.append(link_status(value))
        else:
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, (str, int, float)) and not isinstance(item, bool) and str(item) != "":
                    out.append(str(item))
                elif isinstance(item, bool):
                    out.append("yes" if item else "no")
    if transform in ("link_status", "presence") and not out:
        out.append("not checked")
    return out


def extract(record: dict[str, Any], facet: dict[str, Any]) -> list[Any]:
    return apply_transform(walk_path(record, facet["path"]), facet.get("transform"), facet)


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #

def humanise(value: str) -> str:
    """``district_heating_cooling`` -> ``District heating cooling``; other strings unchanged."""
    if re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", value):
        return value.replace("_", " ").capitalize()
    return value


#: Written labels for vocabulary values (``labels.yaml``, audit 2026-09-26), by vocabulary name.
LABELS: dict[str, dict[str, str]] = {}
#: Vocabulary values that had no written label in this build, as ``vocabulary:value``.
MISSING_LABELS: list[str] = []


def load_labels(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): {str(a): str(b) for a, b in (v or {}).items()} for k, v in raw.items()}


def label_for(vocabulary: str, value: str) -> str:
    """The written label of a vocabulary value, else the humanised key (recorded in MISSING_LABELS)."""
    written = LABELS.get(vocabulary, {}).get(value)
    if written:
        return written
    key = f"{vocabulary}:{value}"
    if key not in MISSING_LABELS:
        MISSING_LABELS.append(key)
    return humanise(value.split(".")[-1])


def country_label(code: str) -> str:
    if code == "XK":
        return "Kosovo"
    if pycountry is not None:
        found = pycountry.countries.get(alpha_2=code)
        if found is not None:
            return getattr(found, "common_name", None) or found.name
    return code


def language_label(code: str) -> str:
    if pycountry is not None:
        found = None
        if len(code) == 2:
            found = pycountry.languages.get(alpha_2=code)
        if found is None:
            found = pycountry.languages.get(alpha_3=code)
        if found is not None:
            return found.name
    return code


def add_filter_vocabularies(vocab: dict[str, Any]) -> None:
    """Put the filter vocabularies (``pipeline/vocab/vocabulary.yaml``) into ``vocab`` and ``LABELS`` as ``filter:<name>``.

    Values carry their one-line definition as the note, which the panel shows as the value's tooltip.
    """
    for name, spec in vocab_map.load_vocabulary().items():
        vocab[f"filter:{name}"] = {value: meta["definition"] for value, meta in spec["values"].items()}
        LABELS[f"filter:{name}"] = {value: meta["label"] for value, meta in spec["values"].items()}


# --------------------------------------------------------------------------- #
# Hierarchies from the vocabulary
# --------------------------------------------------------------------------- #

def hierarchy_values(name: str, vocab: dict[str, Any]) -> list[dict[str, Any]]:
    """Parent and child values for a named vocabulary hierarchy.

    ``sectors``: group -> ``group.sector``; ``data_families``: family group ->
    family; ``route_classes``: route family -> ``Rnn`` class. Each value entry is
    ``{value, label, parent?, note?}``; parents come first, in vocabulary order.
    """
    out: list[dict[str, Any]] = []
    if name == "sectors":
        for group, body in (vocab.get("sectors") or {}).items():
            out.append({"value": group, "label": LABELS.get("sectors", {}).get(group) or body.get("label") or label_for("sectors", group)})
            for sector, note in (body.get("sectors") or {}).items():
                out.append({"value": f"{group}.{sector}", "label": label_for("sectors", f"{group}.{sector}"), "parent": group, "note": str(note)})
    elif name == "data_families":
        for group, families in (vocab.get("data_families") or {}).items():
            out.append({"value": group, "label": label_for("data_families", group)})
            for family, note in (families or {}).items():
                out.append({"value": family, "label": label_for("data_families", family), "parent": group, "note": str(note)})
    elif name == "route_classes":
        families = vocab.get("route_families") or {}
        for family, note in families.items():
            out.append({"value": family, "label": label_for("route_families", family), "note": str(note)})
        for route, body in (vocab.get("route_classes") or {}).items():
            body = body or {}
            entry = {"value": route, "label": f"{route} {body.get('name', '')}".strip(), "parent": body.get("family")}
            if body.get("mode"):
                entry["note"] = "Mode " + str(body["mode"])
            out.append(entry)
    else:
        raise SystemExit(f"unknown hierarchy {name!r}")
    return out


def vocab_values(name: str, vocab: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat vocabulary values (lists, or mappings whose values are notes)."""
    raw = vocab.get(name)
    if isinstance(raw, dict):
        return [{"value": str(k), "label": label_for(name, str(k)), "note": str(v)} for k, v in raw.items()]
    if isinstance(raw, list):
        return [{"value": str(v), "label": label_for(name, str(v))} for v in raw]
    return []


# --------------------------------------------------------------------------- #
# Facet generation
# --------------------------------------------------------------------------- #

def discover_extra_fields(records: Iterable[dict[str, Any]], known_paths: set[str]) -> list[dict[str, Any]]:
    """Facet rows for fields present in the data that the table does not cover.

    A field qualifies when it holds a string, a boolean or a list of strings in
    at least one record and is not a prose field. Ordered by name.
    """
    seen: dict[str, str] = {}
    for record in records:
        for key, value in record.items():
            if key in EXCLUDED_FIELDS or key in known_paths or key in seen:
                continue
            if isinstance(value, bool):
                seen[key] = "bool"
            elif isinstance(value, str) or (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
                seen[key] = "str"
    rows = []
    for key in sorted(seen):
        row = {"id": key, "label": label_for("fields", key), "kind": "multi", "group": "Other", "path": key, "auto": True}
        if seen[key] == "bool":
            row["transform"] = "bool"
        rows.append(row)
    return rows


def build_facets(records: list[dict[str, Any]], vocab: dict[str, Any], open_end: int | None = None) -> list[dict[str, Any]]:
    """Facet definitions with value lists and counts over the whole catalogue.

    ``open_end`` (the build year) closes a ``year_span`` whose end is null (still running).
    """
    rows = [dict(r) for r in FACET_TABLE]
    for r in rows:
        if r.get("transform") == "year_span" and open_end is not None:
            r["open_end"] = open_end
    known_paths = {r["path"].split(".")[0].rstrip("[]") for r in rows if "path" in r}
    rows.extend(discover_extra_fields(records, known_paths))

    facets: list[dict[str, Any]] = []
    for row in rows:
        facet: dict[str, Any] = {k: v for k, v in row.items() if k not in ("vocab", "hierarchy", "labels", "value_labels")}
        if row["kind"] == "text":
            facets.append(facet)
            continue

        # values from the vocabulary first, in vocabulary order
        entries: dict[str, dict[str, Any]] = {}
        if row.get("hierarchy"):
            for entry in hierarchy_values(row["hierarchy"], vocab):
                entries[entry["value"]] = entry
        elif row.get("vocab"):
            for entry in vocab_values(row["vocab"], vocab):
                entries[entry["value"]] = entry

        # then values from the data, with counts
        counter: Counter[Any] = Counter()
        multi_valued = False
        for record in records:
            values = extract(record, row)
            if len(set(values)) > 1:
                multi_valued = True
            for value in set(values):
                counter[value] += 1

        if row["kind"] == "range":
            numbers = sorted(v for v in counter if isinstance(v, (int, float)))
            facet["min"] = numbers[0] if numbers else None
            facet["max"] = numbers[-1] if numbers else None
            facet["counts"] = {str(k): counter[k] for k in numbers}
            facet["multi_valued"] = multi_valued
            facets.append(facet)
            continue

        # sorted: iterating the Counter follows set order, which changes with PYTHONHASHSEED, so two builds of the
        # same catalogue gave different value orders (round 2 check B-2, 2026-10-01)
        for value in sorted(counter, key=str):
            value = str(value)
            if value not in entries:
                label = value
                if value in (row.get("value_labels") or {}):
                    label = row["value_labels"][value]
                elif row.get("labels") == "country":
                    label = country_label(value)
                elif row.get("labels") == "language":
                    label = language_label(value)
                elif row.get("vocab") or row.get("hierarchy") or row.get("auto") or row.get("transform"):
                    label = humanise(value)
                entries[value] = {"value": value, "label": label}
        for value, entry in entries.items():
            entry["count"] = counter.get(value, 0)
        # a hierarchy counts what the page's engine counts: a record's values are expanded upwards to the parent
        # and a bare parent downwards to every child (round 2 check: children used to omit the bare-parent records,
        # so the catalogue count that orders the list differed from the live count)
        if row["kind"] == "hierarchy":
            parent_of = {e["value"]: e["parent"] for e in entries.values() if e.get("parent")}
            kids_of: dict[str, list[str]] = {}
            for child, parent in parent_of.items():
                kids_of.setdefault(parent, []).append(child)
            expanded_counter: Counter = Counter()
            for record in records:
                expanded: set[str] = set()
                for value in extract(record, row):
                    value = str(value)
                    expanded.add(value)
                    if value in parent_of:
                        expanded.add(parent_of[value])
                    expanded.update(kids_of.get(value, ()))
                expanded_counter.update(expanded)
            for value, entry in entries.items():
                entry["count"] = expanded_counter.get(value, 0)
        facet["values"] = list(entries.values())
        facet["multi_valued"] = multi_valued or "[]" in row["path"] or row["kind"] == "hierarchy"
        facets.append(facet)

    # a facet with no values at all (no vocabulary, nothing in the data) is kept
    # in the definitions but flagged so the panel can skip it
    for facet in facets:
        if facet["kind"] in ("multi", "hierarchy"):
            facet["empty"] = not facet.get("values")
        elif facet["kind"] == "range":
            facet["empty"] = facet.get("min") is None
        else:
            facet["empty"] = False
    return facets


# --------------------------------------------------------------------------- #
# Estimated completeness (audit E10, 2026-09-26)
# --------------------------------------------------------------------------- #

SWEPT_STATUSES = ("swept", "saturated", "verified_empty")
# Below this many records in a population the page shows no estimate: at 3 records a Lincoln-Petersen
# estimate of "0 % missing" (one recapture) or a Chao1 of "40 %" says nothing about the catalogue.
MIN_RECORDS_FOR_ESTIMATE = 20


def _float(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #

def json_for_html(obj: Any) -> str:
    """Compact JSON safe inside a ``<script type="application/json">`` block."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def assemble(template: str, parts: dict[str, str]) -> str:
    page = template
    for key, value in parts.items():
        marker = "/*@" + key + "@*/" if key in ("STYLES", "ENGINE", "I18N", "APP") else "<!--@" + key + "@-->"
        if marker not in page:
            raise SystemExit(f"template lacks marker {marker}")
        page = page.replace(marker, value)
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--project", default=str(DEFAULT_PROJECT), help="project directory holding catalog/ (default: the real project)")
    parser.add_argument("--schema-dir", default=None, help="directory holding vocab.yaml (default: <project>/schema, else the real schema)")
    parser.add_argument("--out", default=str(HERE / "dist" / "index.html"), help="output page (default: dist/index.html next to this script)")
    parser.add_argument("--data-file", default=None, help="write the records next to the page as NAME-1.json, NAME-2.json, ... (8 MB parts) and load them at run time, instead of inlining them")
    parser.add_argument("--date", default=None, help="build date YYYY-MM-DD (default: today)")
    parser.add_argument("--allow-missing-pycountry", action="store_true", help="build even when pycountry is not installed (country and language filters then show bare codes; for fixture tests only)")
    parser.add_argument("--no-bundle", action="store_true", help="do not write bundle.json next to the page (it is 260 MB for the real catalogue)")
    args = parser.parse_args(argv)
    if pycountry is None and not args.allow_missing_pycountry:
        raise SystemExit("pycountry is not installed, so the country and language filters would show bare codes such as DE and fr. "
                         "Install it with `pip install -r requirements.txt`, or pass --allow-missing-pycountry for a throw-away build.")

    if pycountry is None:
        print("WARNING: pycountry is not installed: the Country and Language filters will show codes (FR, fra) instead of names. "
              "Run `python3 -m pip install pycountry` and build again before publishing.", file=sys.stderr)

    project = Path(args.project).resolve()
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else (project / "schema" if (project / "schema" / "vocab.yaml").exists() else DEFAULT_PROJECT / "schema")
    out = Path(args.out).resolve()

    vocab = load_vocab(schema_dir / "vocab.yaml")
    LABELS.clear(); LABELS.update(load_labels(HERE / "labels.yaml"))
    MISSING_LABELS.clear()
    add_filter_vocabularies(vocab)
    records, header = load_records(project)
    records = [tidy_whitespace(vocab_map.apply_to_record(r)) for r in records]
    built = args.date or dt.date.today().isoformat()
    facets = build_facets(records, vocab, open_end=int(built[:4]))

    meta = {
        "built": built,
        "catalogue_built": header.get("built"),
        "source": header.get("source"),
        "schema_version": vocab.get("version"),
        "vocab_updated": str(vocab.get("updated")),
        "record_types": list(RECORD_TYPES),
        "counts": {"total": len(records), "by_type": {t: sum(1 for r in records if r.get("type") == t) for t in RECORD_TYPES}},
        "text_fields": list(TEXT_FIELDS),
        "panel_groups": list(PANEL_GROUP_ORDER),
        "sector_groups": {g: (LABELS.get("sectors", {}).get(g) or b.get("label") or humanise(g)) for g, b in (vocab.get("sectors") or {}).items()},
        "family_groups": {g: label_for("data_families", g) for g in (vocab.get("data_families") or {})},
        "missing_labels": list(MISSING_LABELS),
        "completeness": None,
    }
    bundle = {"meta": meta, "facets": facets, "records": records}

    # Split mode: the JSON text is cut into parts under 8 MB that the page joins before parsing.
    data_parts: list[tuple[str, str]] = []
    if args.data_file:
        text = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        stem = args.data_file.removesuffix(".json")
        size = 8_000_000
        data_parts = [(f"{stem}-{i + 1}.json", text[k:k + size]) for i, k in enumerate(range(0, len(text), size))]

    src = HERE / "src"
    template = (src / "template.html").read_text(encoding="utf-8")
    page = assemble(template, {
        "STYLES": (src / "styles.css").read_text(encoding="utf-8"),
        "ENGINE": (src / "engine.js").read_text(encoding="utf-8"),
        "I18N": (src / "i18n.js").read_text(encoding="utf-8"),
        "APP": (src / "app.js").read_text(encoding="utf-8"),
        "DATA": "" if args.data_file else json_for_html(bundle),
        "DATA_SRC": f' data-src="{" ".join(n for n, _ in data_parts)}"' if data_parts else "",
        "BUILT": built,
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    for name, part in data_parts:
        (out.parent / name).write_text(part, encoding="utf-8")
    if not args.no_bundle:
        (out.parent / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    n_values = sum(len(f.get("values", [])) for f in facets)
    print(f"dashboard: {len(records)} records from {header.get('source')}; {len(facets)} facets, {n_values} facet values; "
          f"{out} ({out.stat().st_size / 1024:.0f} kB)" + ("" if args.no_bundle else "; bundle.json alongside"))
    for f in facets:
        if f.get("auto"):
            print(f"  auto facet: {f['id']} ({f['label']})")
    if MISSING_LABELS:
        print(f"  {len(MISSING_LABELS)} vocabulary values without a written label in labels.yaml: {', '.join(MISSING_LABELS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
