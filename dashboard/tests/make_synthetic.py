#!/usr/bin/env python3
"""Generate a large synthetic catalogue for performance and property tests.

Writes ``N`` records (roughly 55 % data, 20 % model, 15 % platform, 10 % case study; case studies added 2026-09-24) to
``<out>/catalog/<type>/<id>.json`` in the shape the dashboard reads, drawing
every controlled value from ``vocab.yaml`` so the facets look like the real
ones. Names, providers and descriptions are assembled from word lists so the
trigram index sees realistic vocabulary. The generator is seeded and
deterministic. Nothing here is a real resource; the output stays in the
sandbox and is never placed in ``catalog``.

Usage: ``python3 tests/make_synthetic.py --out DIR [--n 20000] [--seed 7]``.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
VOCAB = HERE.parent.parent / "schema" / "vocab.yaml"

WORDS = ("grid transmission substation feeder outage load demand hydro reservoir levee flood hazard fragility bridge tunnel rail "
         "metro depot port berth freight corridor fibre backbone exchange hospital shelter waste landfill refinery pipeline "
         "compressor telemetry sensor scenario projection synthetic benchmark register inventory topology timetable survey "
         "census cadastre parcel canopy wildfire heat drought storm surge subsidence liquefaction spectrum coverage twin "
         "coupling engine suite toolkit solver optimiser simulator estimator emulator library dataset atlas map layer").split()
ORGS = ("National Grid Office", "Bureau of Statistics", "Water Board", "Transport Authority", "Geological Survey", "Met Office",
        "Open Mapping Collective", "University Lab", "Resilience Institute", "Energy Agency", "City Council", "Port Authority",
        "Regulator", "Research Council", "Systems Consortium", "Cadastre Office", "Rail Infrastructure Manager", "Civil Protection")
COUNTRIES = "DE NL FR GB US CA JP AU BR IN ZA KE NG MX AR SE NO FI PL IT ES PT CZ CH AT".split()
LANGS = "en de nl fr es pt ja".split()
FORMATS = "CSV GeoJSON Shapefile GeoPackage NetCDF GeoTIFF Parquet JSON XML GTFS WMS WFS".split()
LICENCES = "CC-BY-4.0 CC0-1.0 ODbL-1.0 MIT Apache-2.0 GPL-3.0-only proprietary DL-DE-BY-2.0 OGL-UK-3.0".split()
PLANG = "Python Julia C++ Java R MATLAB Fortran Rust".split()


def sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--n", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    vocab = yaml.safe_load(VOCAB.read_text(encoding="utf-8"))
    sectors = [f"{g}.{s}" for g, body in vocab["sectors"].items() for s in body["sectors"]]
    groups = list(vocab["sectors"])
    families = [f for fams in vocab["data_families"].values() for f in fams]
    routes = list(vocab["route_classes"])
    out = Path(args.out)
    for t in ("data", "model", "platform", "case_study"):
        (out / "catalog" / t).mkdir(parents=True, exist_ok=True)
    ids = []
    for i in range(args.n):
        rtype = "data" if i % 20 < 11 else "model" if i % 20 < 15 else "platform" if i % 20 < 18 else "case_study"
        ids.append(f"{rtype}-synthetic-{i:06d}")
    for i, rid in enumerate(ids):
        rtype = rid.split("-")[0]
        name = " ".join(w.capitalize() for w in rng.sample(WORDS, k=rng.randint(2, 4))) + f" {i % 97}"
        year = rng.randint(2015, 2026)
        rec = {
            "id": rid, "type": rtype, "name": name, "provider": rng.choice(ORGS),
            "description": " ".join(sentence(rng, rng.randint(8, 16)) for _ in range(rng.randint(6, 10))),
            "homepage": f"https://example.org/{rid}/",
            "access_links": [{"label": "Landing page", "url": f"https://example.org/{rid}/", "kind": rng.choice(vocab["access_link_kinds"])}],
            "licence": rng.choice(LICENCES), "cost": rng.choice(vocab["cost"]), "access_restrictions": rng.choice(vocab["access_restrictions"]),
            "sectors": rng.sample(sectors, k=rng.randint(1, 3)) + ([rng.choice(groups)] if rng.random() < 0.05 else []),
            "geographic_scope": rng.choice(vocab["geographic_scope"]),
            "continents": rng.sample(vocab["continents"], k=rng.randint(0, 2)),
            "countries": rng.sample(COUNTRIES, k=rng.randint(0, 3)),
            "simulation_uses": rng.sample(vocab["simulation_uses"], k=rng.randint(1, 4)),
            "maturity": rng.choice(vocab["maturity"]),
            "last_updated": str(year) if rng.random() < 0.7 else "",
            "date_catalogued": f"{rng.randint(2024, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "date_verified": f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}",
            "description_checked": "2026-09-01",
            "related_ids": rng.sample(ids, k=rng.randint(0, 2)),
            "tags": rng.sample(WORDS, k=rng.randint(0, 3)),
            "sources": [{"url": f"https://example.org/{rid}/", "accessed": "2026-09-01", "note": "synthetic"}],
            "discovery_routes": [{"route": r, "source": "synthetic", "query": rng.choice(WORDS), "date": "2026-09-01"} for r in rng.sample(routes, k=rng.randint(1, 3))],
            "dedupe_keys": {"url": f"https://example.org/{rid}", "name": name.lower()},
            "languages": rng.sample(LANGS, k=rng.randint(1, 2)),
        }
        if rtype == "data":
            rec.update({"data_family": rng.sample(families, k=rng.randint(1, 3)), "data_kind": rng.sample(vocab["data_kinds"], k=rng.randint(1, 2)),
                        "formats": rng.sample(FORMATS, k=rng.randint(1, 3)), "update_frequency": rng.choice(["daily", "monthly", "yearly", "irregular", "once"])})
        elif rtype == "model":
            rec.update({"model_kind": rng.sample(vocab["model_kinds"], k=rng.randint(1, 2)), "language": rng.sample(PLANG, k=rng.randint(1, 2)),
                        "inputs": rng.sample(WORDS, k=2), "outputs": rng.sample(WORDS, k=2)})
        elif rtype == "case_study":
            rec.update({"case_study_kind": rng.sample(list(vocab["case_study_kinds"]), k=rng.randint(1, 2)), "hazards": rng.sample(list(vocab["hazard_types"]), k=rng.randint(1, 2)),
                        "resources_used": rng.sample(ids, k=rng.randint(1, 3)), "outcomes": sentence(rng, 12), "study_period": str(year)})
        else:
            rec.update({"platform_kind": rng.sample(vocab["platform_kinds"], k=1), "interfaces": rng.sample(["GUI", "CLI", "API", "FMI", "HELICS"], k=rng.randint(1, 3)),
                        "deployment": rng.sample(["desktop", "server", "cloud", "web"], k=rng.randint(1, 2)), "open_source": rng.random() < 0.6})
        if rng.random() < 0.3:
            rec["link_health"] = {"checked": "2026-09-01", "dead": [rec["homepage"]] if rng.random() < 0.1 else []}
        (out / "catalog" / rtype / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(ids)} synthetic records under {out / 'catalog'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
