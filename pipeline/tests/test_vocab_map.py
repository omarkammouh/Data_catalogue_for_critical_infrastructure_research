"""Filter vocabularies and the mapping of raw record values onto them (vocab_map.py, 2026-09-29)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

import vocab_map

VOCAB_DIR = vocab_map.VOCAB_DIR


@pytest.fixture(scope="module")
def vocabulary():
    return vocab_map.load_vocabulary()


@pytest.mark.parametrize("raw", [
    "not stated", "Not stated.", "not established", "Not established from the reviewed metadata", "unknown", "Unknown",
    "not stated on the page read", "not read", "", "not stated (provider pages not readable from the cloud on 2026-09-28)",
])
def test_not_stated_variants_collapse_to_one_value(raw):
    for name in ("licence", "update_frequency", "temporal_resolution", "spatial_resolution", "formats"):
        assert vocab_map.classify(name, raw)[0] == ["not_stated"], (name, raw)


@pytest.mark.parametrize("raw, types, names", [
    ("CC-BY-4.0", ["attribution"], ["CC-BY"]),
    ("CC BY 4.0", ["attribution"], ["CC-BY"]),
    ("cc-by-4.0", ["attribution"], ["CC-BY"]),
    ("Creative Commons Attribution Non Commercial 4.0 International", ["non_commercial"], ["CC-BY-NC"]),
    ("CC BY-NC-SA 4.0", ["non_commercial"], ["CC-BY-NC-SA"]),
    ("CC0 1.0", ["public_domain"], ["CC0"]),
    ("GPL-3.0-or-later", ["copyleft_code"], ["GPL"]),
    ("LGPL-2.1", ["copyleft_code"], ["LGPL"]),
    ("MIT (code); CC BY 4.0 (data and figures)", ["attribution", "permissive_code"], ["CC-BY", "MIT"]),
    ("Public domain (U.S. federal government work)", ["public_domain"], ["US-Gov-PD"]),
    ("UK Open Government Licence (OGL)", ["attribution"], ["OGL-UK"]),
    ("Open Government Licence - Canada", ["attribution"], ["OGL-Canada"]),
    ("ODbL-1.0", ["share_alike"], ["ODbL"]),
    ("proprietary (commercial)", ["proprietary"], []),
    ("varies by dataset", ["varies"], []),
    ("NYC Open Data terms of use", ["provider_terms"], []),
    ("https://creativecommons.org/publicdomain/zero/1.0/", ["public_domain"], ["CC0"]),
])
def test_licence_types_and_names(raw, types, names):
    assert vocab_map.classify("licence", raw)[0] == types
    assert vocab_map.classify("licence_name", raw)[0] == names


@pytest.mark.parametrize("raw, expected", [
    ("CSV", ["csv"]), ("csv", ["csv"]), ("XLSX", ["spreadsheet"]), ("Excel", ["spreadsheet"]), ("GeoJSON", ["geojson"]),
    ("API JSON", ["api"]), ("JSON (Socrata API)", ["api"]), ("CSV in ZIP", ["csv"]), ("ZIP", ["archive"]), ("WMS", ["ogc_map_service"]),
    ("ArcGIS feature service", ["ogc_map_service"]), ("GeoTIFF", ["raster"]), ("NetCDF", ["netcdf_hdf"]), ("web map", ["web_page"]),
    ("PDF reports", ["document"]), ("GTFS", ["transit_feed"]), ("Shapefile", ["shapefile"]), ("SHP", ["shapefile"]),
])
def test_formats(raw, expected):
    assert vocab_map.classify("formats", raw)[0] == expected


@pytest.mark.parametrize("raw, expected", [
    ("30 m", "10m_to_100m"), ("1 km", "1km_to_10km"), ("10 cm per pixel", "under_10m"), ("3 arc-seconds (about 90 m)", "10m_to_100m"),
    ("0.5 degrees", "over_10km"), ("5 arc-minutes (about 10 km)", "1km_to_10km"), ("Individual buildings", "asset"), ("municipality", "local_units"),
    ("NUTS 2 regions", "regional_units"), ("national", "national"), ("not spatial", "non_spatial"), ("Germany", "national"),
])
def test_spatial_resolution(raw, expected):
    assert vocab_map.classify("spatial_resolution", raw)[0] == [expected]


@pytest.mark.parametrize("name, raw, expected", [
    ("update_frequency", "Annual", "annual"), ("update_frequency", "one-off", "not_updated"), ("update_frequency", "none", "not_updated"),
    ("update_frequency", "real time", "real_time"), ("update_frequency", "every five years", "multi_year"), ("update_frequency", "versioned releases", "irregular"),
    ("temporal_resolution", "15 minutes", "sub_hourly"), ("temporal_resolution", "Hourly", "hourly"), ("temporal_resolution", "single census", "snapshot"),
    ("temporal_resolution", "decennial census", "multi_year"), ("temporal_resolution", "per event", "event"), ("temporal_resolution", "Annual", "annual"),
    ("maturity", "maintained", "active"), ("maturity", "unknown", "not_stated"),
])
def test_scalar_fields(name, raw, expected):
    assert vocab_map.classify(name, raw)[0] == [expected]


@pytest.mark.parametrize("last_updated, expected", [
    ("2026-01-15", "active"), ("2024-10-01", "active"), ("2024-09-28", "stale"), ("2021", "stale"),
    ("2024", "active"), ("2024-06", "stale"), ("2025", "active"), ("", None), ("not dated", None), (None, None),
])
def test_dated_resource_maturity_from_last_update(last_updated, expected):
    assert vocab_map.maturity_from_date(last_updated) == expected


def test_maturity_is_taken_from_the_date_only_when_none_is_stated():
    dated = {"id": "data-x", "maturity": "unknown", "last_updated": "2019"}
    assert vocab_map.apply_to_record(dated)["maturity"] == "stale"
    assert vocab_map.apply_to_record({**dated, "last_updated": "2026-05"})["maturity"] == "active"
    assert vocab_map.apply_to_record({**dated, "last_updated": None})["maturity"] == "not_stated"
    assert vocab_map.apply_to_record({**dated, "maturity": "active"})["maturity"] == "active"


@pytest.mark.parametrize("raw", ["pip install blackmarblepy", "conda install foo", "installed locally as a Python library", "install.packages(\"x\")", "R package from CRAN"])
def test_library_installed_on_own_computer_is_desktop(raw):
    assert vocab_map.classify("deployment", raw)[0] == ["desktop"]


def test_language_interfaces_deployment():
    assert vocab_map.classify("language", "C++")[0] == ["c_cpp"]
    assert vocab_map.classify("language", "C")[0] == ["c_cpp"]
    assert vocab_map.classify("language", "C#")[0] == ["dotnet"]
    assert vocab_map.classify("language", "R")[0] == ["r"]
    assert vocab_map.classify("language", "Jupyter Notebook")[0] == ["python"]
    assert vocab_map.classify("interfaces", "REST API")[0] == ["web_api"]
    assert vocab_map.classify("interfaces", "Python API")[0] == ["code_library"]
    assert vocab_map.classify("interfaces", "desktop GUI")[0] == ["desktop_gui"]
    assert vocab_map.classify("interfaces", "FMI")[0] == ["cosimulation"]
    assert vocab_map.classify("deployment", "self-hosted with containers")[0] == ["own_server"]
    assert vocab_map.classify("deployment", "web browser")[0] == ["hosted_service"]


def test_every_rule_output_and_csv_value_is_in_the_vocabulary(vocabulary):
    for name, spec in vocabulary.items():
        allowed = set(spec["values"]) | {vocab_map.UNMAPPED}
        path = VOCAB_DIR / f"{name}.csv"
        assert path.exists(), f"missing mapping file {path.name}"
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                for v in (x for x in row["mapped"].split("|") if x):
                    assert v in allowed, (name, row["raw_value"], v)


def test_vocabulary_values_map_to_themselves(vocabulary):
    for name, spec in vocabulary.items():
        for value in spec["values"]:
            assert vocab_map.lookup(name, value)[0] == [value]


def test_every_value_has_a_label_and_a_definition(vocabulary):
    for name, spec in vocabulary.items():
        assert spec["label"] and spec["record_field"] and spec["target"]
        for value, meta in spec["values"].items():
            assert meta["label"] and meta["definition"], (name, value)


def test_no_two_values_share_a_label(vocabulary):
    for name, spec in vocabulary.items():
        labels = [meta["label"].lower() for meta in spec["values"].values()]
        assert len(labels) == len(set(labels)), name


def test_apply_to_record_normalises_without_touching_the_input():
    record = {"id": "data-x", "type": "data", "licence": "CC BY 4.0", "formats": ["CSV", "csv", "XLSX"], "maturity": "maintained",
              "update_frequency": "Not stated.", "spatial_resolution": "30 m", "temporal_resolution": "Hourly"}
    before = json.dumps(record, sort_keys=True)
    out = vocab_map.apply_to_record(record)
    assert json.dumps(record, sort_keys=True) == before
    assert out["licence_type"] == ["attribution"] and out["licence_name"] == ["CC-BY"] and out["licence"] == "CC BY 4.0"
    assert out["formats"] == ["csv", "spreadsheet"]
    assert out["maturity"] == "active" and out["update_frequency"] == "not_stated"
    assert out["spatial_resolution_class"] == "10m_to_100m" and out["spatial_resolution"] == "30 m"
    assert out["temporal_resolution_class"] == "hourly"


def test_a_value_stored_in_the_record_wins_over_the_mapping():
    record = {"id": "data-x", "licence": "CC BY 4.0", "licence_type": ["provider_terms"]}
    assert vocab_map.apply_to_record(record)["licence_type"] == ["provider_terms"]


def test_unplaced_values_become_other_and_are_reported():
    record = {"id": "data-x", "formats": ["some brand-new format nobody has seen"]}
    assert vocab_map.apply_to_record(record)["formats"] == ["other"]
    problems = vocab_map.issues([record])
    assert problems and problems[0][1] == "formats" and "not in vocab/formats.csv" in problems[0][3]
    bad = {"id": "data-y", "licence": "MIT", "licence_type": ["free"]}
    assert ("data-y", "licence_type", "free", "not a vocabulary value") in vocab_map.issues([bad])


def test_rewrite_is_a_dry_run_unless_applied_and_is_idempotent(tmp_path):
    project = tmp_path / "project"
    (project / "catalog" / "data").mkdir(parents=True)
    rec = {"id": "data-x", "type": "data", "licence": "CC BY 4.0", "formats": ["CSV in ZIP"], "maturity": "unknown", "spatial_resolution": "1 km grid"}
    path = project / "catalog" / "data" / "data-x.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert vocab_map.main(["rewrite", "--project", str(project)]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == rec
    assert vocab_map.main(["rewrite", "--project", str(project), "--apply"]) == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["licence"] == "CC BY 4.0" and written["licence_type"] == ["attribution"] and "licence_name" not in written
    assert written["formats"] == ["csv"] and written["maturity"] == "not_stated" and written["spatial_resolution_class"] == "1km_to_10km"
    assert vocab_map.issues([written]) == []
    assert vocab_map.main(["rewrite", "--project", str(project), "--apply"]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == written


def test_refresh_keeps_manual_rows(tmp_path):
    project = tmp_path / "project"
    (project / "catalog" / "data").mkdir(parents=True)
    (project / "catalog" / "data" / "data-x.json").write_text(json.dumps({"id": "data-x", "type": "data", "formats": ["CSV", "Mystery"]}), encoding="utf-8")
    vocab_dir = tmp_path / "vocab"
    vocab_dir.mkdir()
    shutil.copy(VOCAB_DIR / "vocabulary.yaml", vocab_dir / "vocabulary.yaml")
    (vocab_dir / "formats.csv").write_text("raw_value,records,mapped,rule\nMystery,1,database,manual\n", encoding="utf-8")
    vocab_map.load_vocabulary.cache_clear(); vocab_map.load_tables.cache_clear()
    try:
        assert vocab_map.main(["refresh", "--project", str(project), "--vocab-dir", str(vocab_dir)]) == 0
        rows = {r["raw_value"]: r for r in csv.DictReader((vocab_dir / "formats.csv").open(encoding="utf-8"))}
        assert rows["Mystery"]["mapped"] == "database" and rows["Mystery"]["rule"] == "manual"
        assert rows["CSV"]["mapped"] == "csv"
    finally:
        vocab_map.load_vocabulary.cache_clear(); vocab_map.load_tables.cache_clear()
