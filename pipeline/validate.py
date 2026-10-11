#!/usr/bin/env python3
"""Validate every catalogue record against the structural schema and the vocabularies.

What is checked, per record (each check names the record file and the field):

1. **Structure.** The record parses as JSON, validates against
   ``schema/record.schema.json`` (JSON Schema draft 2020-12), sits in the folder
   of its type, and its file name equals ``<id>.json``. Ids are unique.
2. **Vocabularies** (``schema/vocab.yaml``): sectors as ``group.sector`` or bare
   ``group``, ``data_family``, ``data_kind``, ``model_kind``, ``platform_kind``, ``case_study_kind``, ``hazards``,
   ``supported_sectors``, ``simulation_uses``, ``maturity``, ``cost``,
   ``access_restrictions``, ``geographic_scope``, ``continents``, access-link
   ``kind``, ``discovery_routes[].route`` ids, ``languages`` (ISO 639-1/2/3 via
   pycountry) and ``countries`` (ISO 3166-1 alpha-2 via pycountry).
3. **Description standard** (schema.md, "Description standard"): 100 to 300 words
   is an error outside the range; the eight required content elements
   (contents, producer, coverage, format/access, licence/cost, caveats,
   simulation uses, related records) are looked for with a conservative keyword
   heuristic and a missing element is reported as a *warning*, because a
   keyword test can only suggest, not prove, that prose lacks an element.
   ``--strict-description`` turns those warnings into errors for the P9 gate.
4. **Cross-references.** Every ``related_ids`` entry, and every id-shaped entry
   in ``runs_on``, ``hosted_models`` and ``resources_used``, must resolve to an existing record.
5. **Consistency**: homepage, access-link and source URLs that are not
   well-formed absolute http(s) URLs are errors (``common.is_http_url``: no
   whitespace, a valid host and port). The schema's ``http-url`` format uses
   the same rule, including saved Unicode paths and API URL templates.
   Warnings: dedupe keys
   that are not in normalised form; type-specific fields on the wrong type;
   dates out of order; a route family that the vocabulary does not know.

Catalogue-level check: **schema.md drift** (M10 and the roadmap's "schema.md
matches vocab.yaml" checkpoint). Every value of every record vocabulary in
``vocab.yaml`` must appear in ``schema.md`` as a back-ticked token; a value
missing from the prose is an error, because schema.md is the human-readable
contract. ``--no-drift`` skips this check for record-only runs.

Exit status is 1 when any error was found, otherwise 0. ``--json`` prints a
machine-readable report instead of the text one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

import jsonschema

import vocab_map

from common import (
    RECORD_TYPES,
    Paths,
    RecordFile,
    Vocab,
    add_common_args,
    effective_dedupe_keys,
    humanise,
    is_country_code,
    is_http_url,
    is_language_code,
    load_record_schema,
    load_records,
    load_vocab,
    normalise_doi,
    normalise_name,
    normalise_repo,
    normalise_url,
    parse_date,
    word_count,
)

DESCRIPTION_MIN_WORDS = 100
DESCRIPTION_MAX_WORDS = 300

TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "data": ("data_family", "data_kind", "formats", "spatial_resolution", "spatial_resolution_m", "spatial_resolution_class", "temporal_coverage", "temporal_coverage_years", "temporal_resolution", "temporal_resolution_class", "crs", "size", "size_bytes", "schema_summary", "update_frequency"),
    "model": ("model_kind", "language", "inputs", "outputs", "validated_on", "repository", "citation", "runs_on"),
    "platform": ("platform_kind", "hosted_models", "interfaces", "deployment", "open_source", "supported_sectors", "interoperability"),
    "case_study": ("case_study_kind", "resources_used", "outcomes", "study_period", "organisations"),
}

# Fields that belong to one type but are also allowed on others (user decision 2026-09-30: `language`, the
# programming language, is also allowed on platform records).
ALSO_ALLOWED: dict[str, tuple[str, ...]] = {"language": ("platform",)}

ID_SHAPED = re.compile(r"^(data|model|platform|case_study)-[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Issue:
    """One validation finding. ``level`` is ``error`` or ``warning``."""

    level: str
    record: str
    field: str
    message: str

    def __str__(self) -> str:
        where = f"{self.record}" + (f" [{self.field}]" if self.field else "")
        return f"{self.level.upper():7} {where}: {self.message}"


# --------------------------------------------------------------------------- #
# Description content heuristic
# --------------------------------------------------------------------------- #

def _rx(words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + words + r")\b", re.IGNORECASE)


CONTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "contents": _rx(
        r"contains?|containing|includes?|including|covers?|covering|comprises?|comprising|provides?|providing|"
        r"consists?|records?|holds?|lists?|listing|describes?|describing|represents?|offers?|"
        r"implements?|simulates?|models?|computes?|solves?|datasets?|layers?|tables?|inventory|"
        r"topology|time series|network|register|catalogue|catalog"
    ),
    "coverage": _rx(
        r"global|worldwide|world|national|nationwide|continental|regional|countr(?:y|ies)|cit(?:y|ies)|"
        r"europe|european|africa|african|asia|asian|america|american|oceania|coverage|covers|covering|extent|"
        r"resolution|scale|from \d{4}|since \d{4}|\d{4} ?(?:to|–|-|until) ?\d{4}|annual|hourly|daily|monthly|"
        r"yearly|weekly|snapshot|spatial|temporal|km|kilometre|metre|meter|degree|grid cell|arc-?second|"
        r"per (?:country|city|node|asset|line|station|feeder|link)|case study|study area|"
        r"[a-z]+-specific|any (?:country|region|network|city|model|system)|user-supplied|user-provided|independent of|"
        r"generic|location-?independent|not tied to|anywhere|several countries|worldwide"
    ),
    "format_access": _rx(
        r"formats?|csv|json|geojson|shapefile|shp|geopackage|gpkg|netcdf|parquet|xml|xlsx|excel|pdf|"
        r"api|rest|wfs|wms|ogc|download(?:s|ed|able)?|access(?:ed|ible|ible via)?|available|portal|repository|"
        r"github|gitlab|zenodo|figshare|package|pip|pypi|conda|cran|npm|install(?:ed|able)?|executable|binary|"
        r"source code|python|julia|matlab|r package|web interface|gui|cli|command[- ]line|docker|hosted|"
        r"endpoint|feed|bulk|export|served|online|offline|desktop|cloud"
    ),
    "licence_cost": _rx(
        r"licen[cs]e[ds]?|licensing|cc[- ]?by(?:[- ]?(?:sa|nc|nd))*|cc0|odbl|odc|pddl|mit|apache|gpl|lgpl|agpl|bsd|"
        r"mpl|eupl|epl|public domain|open[- ]source|open[- ]data|proprietary|commercial|free of charge|"
        r"free to use|free|paid|subscription|fee|cost|price|pricing|on request|registration|terms of use|"
        r"closed[- ]source|no charge|gratis|royalty"
    ),
    "caveats": _rx(
        r"caveats?|limitations?|limited|gaps?|missing|incomplete|uncertain(?:ty|ties)?|not (?:all|every|yet|"
        r"complete|verified|updated|maintained|available)|however|although|but|only|lacks?|lacking|coarse|"
        r"outdated|stale|deprecated|discontinued|no longer|unverified|beware|note that|known issues?|bias(?:ed)?|"
        r"partial(?:ly)?|approximate(?:ly)?|omits?|excludes?|does not|do not|cannot|unknown|varies|vary|"
        r"inconsisten(?:t|cies)|errors?|sparse|undocumented|legacy|effort|manual|heavy|slow|large"
    ),
    "related": _rx(
        r"related|relates|relating|complements?|complementary|companion|see also|together with|alongside|"
        r"derived from|based on|feeds|consumed by|used by|builds on|built on|pairs? with|counterpart|successor|"
        r"predecessor|extends|links? to|linked|cross-?referenced|combined with|combine|input to|inputs? (?:for|to)|"
        r"runs (?:on|in|inside|within)|hosted (?:by|on)|hosts|integrates? with|compatible with|reads|imports?|exports? to|"
        r"catalogued here|reference case for|validated (?:on|against)|accompan(?:y|ies|ying)|adapter|"
        r"no (?:other |directly )?(?:related|catalogued|linked) (?:records?|resources?|entries)|not yet linked"
    ),
}

PRODUCER_PATTERN = _rx(
    r"(?:produced|published|maintained|developed|created|compiled|run|operated|hosted|curated|released|"
    r"led|funded|managed|provided|issued|built|written|authored|supported|coordinated)\s+(?:and\s+\w+\s+)?by|"
    r"publisher|maintainer|developer|producer|provider|consortium|agency|agencies|institute|university|"
    r"laboratory|company|community|project|team|authors?|ministry|department|operator|utility|foundation|"
    r"initiative|group|centre|center|office|bureau|survey|association|organi[sz]ation|commission|council"
)
SIMULATION_PATTERN = _rx(
    r"simulat(?:e|es|ed|ion|ions|or|ors|ing)|model(?:l)?(?:ed|ing)? (?:input|of|for|the)|used (?:for|in|to|as)|"
    r"suitable for|supports?|enables?|serves?|allows?|input(?:s)? for|scenario|scenarios|analys[ie]s|assessment|"
    r"planning|forecast(?:s|ing)?|optimi[sz]ation|resilience|reliability|risk"
)


def description_elements(data: dict[str, Any], vocab: Vocab, related_names: dict[str, str] | None = None) -> dict[str, bool]:
    """Which of the eight required content elements the description appears to contain.

    The test is deliberately conservative in what it *requires*: each element is
    satisfied by any of a broad set of keywords, so a well-written description
    passes without contortion, and only a description that says nothing about an
    element is flagged. Some elements also accept evidence from the record's own
    fields (the provider's name in the prose counts as "producer"; the ids of
    ``related_ids``, or the names of the records they resolve to when
    ``related_names`` maps id to name, count as "related"; the record's
    ``simulation_uses`` values, humanised, count as "simulation uses").
    """
    text = str(data.get("description") or "")
    lower = text.lower()
    found: dict[str, bool] = {}
    for element, pattern in CONTENT_PATTERNS.items():
        found[element] = bool(pattern.search(text))

    # producer: provider tokens or a "produced by" style phrase
    provider_tokens = [t for t in normalise_name(data.get("provider")).split() if len(t) >= 3]
    provider_hit = any(re.search(r"\b" + re.escape(tok) + r"\b", normalise_name(text)) for tok in provider_tokens)
    found["producer"] = provider_hit or bool(PRODUCER_PATTERN.search(text))

    # simulation uses: the record's own use values in prose, or the vocabulary's, or a simulation verb
    uses = list(data.get("simulation_uses") or []) + list(vocab.simulation_uses)
    use_hit = any(humanise(u).lower() in lower or u.lower() in lower or humanise(u).replace(" ", "-").lower() in lower for u in uses if isinstance(u, str))
    found["simulation_uses"] = use_hit or bool(SIMULATION_PATTERN.search(text))

    # related: ids or a phrase
    related_ids = [r for r in data.get("related_ids") or [] if isinstance(r, str)]
    related_hit = any(r.lower() in lower for r in related_ids)
    if related_names:
        norm_text = normalise_name(text)
        related_hit = related_hit or any(normalise_name(related_names.get(r, "")) and normalise_name(related_names[r]) in norm_text for r in related_ids)
    found["related"] = found["related"] or related_hit

    # coverage: also the record's geographic scope, country names or continent names in prose
    scope_words = [str(data.get("geographic_scope") or "")] + [humanise(c) for c in data.get("continents") or []]
    found["coverage"] = found["coverage"] or any(w and w.lower() in lower for w in scope_words)
    return found


ELEMENT_ORDER = ("contents", "producer", "coverage", "format_access", "licence_cost", "caveats", "simulation_uses", "related")


# --------------------------------------------------------------------------- #
# Record checks
# --------------------------------------------------------------------------- #


class Validator:
    """Runs every check and collects :class:`Issue` objects."""

    def __init__(self, paths: Paths, *, strict_description: bool = False):
        self.paths = paths
        self.vocab = load_vocab(paths)
        self.schema = load_record_schema(paths)
        format_checker = jsonschema.FormatChecker()
        format_checker.checks("http-url")(is_http_url)
        self.validator = jsonschema.Draft202012Validator(self.schema, format_checker=format_checker)
        self.strict_description = strict_description
        self.issues: list[Issue] = []
        self.records: list[RecordFile] = []
        self.names: dict[str, str] = {}

    # -- helpers --------------------------------------------------------------
    def error(self, record: str, field: str, message: str) -> None:
        self.issues.append(Issue("error", record, field, message))

    def warn(self, record: str, field: str, message: str) -> None:
        self.issues.append(Issue("warning", record, field, message))

    def _check_enum(self, rec: str, data: dict[str, Any], field: str, allowed: set[str] | list[str], *, list_field: bool = True) -> None:
        if field not in data:
            return
        allowed_set = set(allowed)
        values = data[field] if list_field else [data[field]]
        if not isinstance(values, list):
            return
        for value in values:
            if value not in allowed_set:
                self.error(rec, field, f"value {value!r} is not in vocab.yaml")

    # -- main ----------------------------------------------------------------
    def run(self, *, check_drift: bool = True) -> list[Issue]:
        self.records = load_records(self.paths.catalog_dir)
        ids = Counter(r.id for r in self.records if not r.error)
        known_ids = set(ids)
        self.names = {r.id: r.name for r in self.records if not r.error}
        for rec in self.records:
            rel = rec.path.relative_to(self.paths.catalog_dir).as_posix()
            if rec.error:
                self.error(rel, "", rec.error)
                continue
            self.check_structure(rel, rec)
            self.check_vocab(rel, rec.data)
            self.check_description(rel, rec.data)
            self.check_references(rel, rec.data, known_ids)
            self.check_consistency(rel, rec.data)
            self.check_filter_vocab(rel, rec.data)
            if ids[rec.id] > 1:
                self.error(rel, "id", f"id {rec.id!r} is used by {ids[rec.id]} files")
        if check_drift:
            self.check_schema_md_drift()
        return self.issues

    def check_structure(self, rel: str, rec: RecordFile) -> None:
        data = rec.data
        for err in sorted(self.validator.iter_errors(data), key=lambda e: list(e.path)):
            path = "/".join(str(p) for p in err.path) or "(root)"
            self.error(rel, path, f"schema: {err.message}")
        rid = data.get("id")
        rtype = data.get("type")
        if isinstance(rid, str) and rec.path.stem != rid:
            self.error(rel, "id", f"file name {rec.path.name!r} does not match id {rid!r}")
        if isinstance(rtype, str) and rec.folder != rtype:
            self.error(rel, "type", f"record of type {rtype!r} is stored in folder {rec.folder!r}")
        if isinstance(rid, str) and isinstance(rtype, str) and not rid.startswith(rtype + "-"):
            self.error(rel, "id", f"id {rid!r} must start with {rtype + '-'!r}")

    def check_vocab(self, rel: str, data: dict[str, Any]) -> None:
        v = self.vocab
        for field in ("sectors", "supported_sectors"):
            for value in data.get(field, []) or []:
                if not v.is_sector(value):
                    self.error(rel, field, f"sector {value!r} is not a group or group.sector in vocab.yaml")
        self._check_enum(rel, data, "data_family", v.data_families)
        self._check_enum(rel, data, "data_resource_type", v.data_resource_types, list_field=False)
        if "data_resource_type" in data and data.get("type") != "data":
            self.error(rel, "data_resource_type", "only data records have a data resource type")
        self._check_enum(rel, data, "data_kind", v.data_kinds)
        self._check_enum(rel, data, "model_kind", v.model_kinds)
        self._check_enum(rel, data, "platform_kind", v.platform_kinds)
        self._check_enum(rel, data, "case_study_kind", v.case_study_kinds)
        self._check_enum(rel, data, "hazards", v.hazard_types)
        self._check_enum(rel, data, "simulation_uses", v.simulation_uses)
        # maturity also accepts the filter vocabulary's values, so records rewritten by vocab_map.py stay valid
        self._check_enum(rel, data, "maturity", set(v.maturity) | set(vocab_map.load_vocabulary()["maturity"]["values"]), list_field=False)
        self._check_enum(rel, data, "cost", v.cost, list_field=False)
        self._check_enum(rel, data, "access_restrictions", v.access_restrictions, list_field=False)
        self._check_enum(rel, data, "geographic_scope", v.geographic_scope, list_field=False)
        self._check_enum(rel, data, "continents", v.continents)
        kinds = set(v.access_link_kinds)
        for i, link in enumerate(data.get("access_links", []) or []):
            if isinstance(link, dict) and link.get("kind") not in kinds:
                self.error(rel, f"access_links/{i}/kind", f"kind {link.get('kind')!r} is not in vocab.yaml")
        routes = v.route_classes
        for i, entry in enumerate(data.get("discovery_routes", []) or []):
            if isinstance(entry, dict) and entry.get("route") not in routes:
                self.error(rel, f"discovery_routes/{i}/route", f"route {entry.get('route')!r} is not a route class in vocab.yaml")
        for code in data.get("languages", []) or []:
            if not is_language_code(code):
                self.error(rel, "languages", f"{code!r} is not an ISO 639 language code")
        for code in data.get("countries", []) or []:
            if not is_country_code(code):
                self.error(rel, "countries", f"{code!r} is not an ISO 3166-1 alpha-2 country code")

    def check_filter_vocab(self, rel: str, data: dict[str, Any]) -> None:
        """Filter vocabularies (``vocab/vocabulary.yaml``, 2026-09-29).

        A stored controlled value outside its vocabulary (``licence_type``, ``*_class`` and rewritten fields) is an
        error. A raw value that ``vocab/<field>.csv`` does not list yet, or lists as waiting for a decision, is a
        warning: the dashboard files it under "other" until ``vocab_map.py refresh`` maps it.
        """
        for _, field, value, problem in vocab_map.issues([data]):
            if problem == "not a vocabulary value":
                self.error(rel, field, f"value {value!r} is not in pipeline/vocab/vocabulary.yaml")
            else:
                self.warn(rel, field, f"value {value[:80]!r} is {problem}; run vocab_map.py refresh")

    def check_description(self, rel: str, data: dict[str, Any]) -> None:
        text = data.get("description")
        if not isinstance(text, str):
            return
        n = word_count(text)
        if n < DESCRIPTION_MIN_WORDS or n > DESCRIPTION_MAX_WORDS:
            self.error(rel, "description", f"{n} words; the standard is {DESCRIPTION_MIN_WORDS} to {DESCRIPTION_MAX_WORDS}")
        elements = description_elements(data, self.vocab, self.names)
        missing = [e for e in ELEMENT_ORDER if not elements.get(e)]
        if missing:
            msg = "description may lack: " + ", ".join(missing) + " (keyword heuristic; check the prose)"
            if self.strict_description:
                self.error(rel, "description", msg)
            else:
                self.warn(rel, "description", msg)

    def check_references(self, rel: str, data: dict[str, Any], known: set[str]) -> None:
        for rid in data.get("related_ids", []) or []:
            if rid not in known:
                self.error(rel, "related_ids", f"{rid!r} does not resolve to a record")
        for field in ("runs_on", "hosted_models", "resources_used"):
            for value in data.get(field, []) or []:
                if isinstance(value, str) and ID_SHAPED.match(value) and value not in known:
                    self.error(rel, field, f"{value!r} looks like a record id but no such record exists")

    def check_consistency(self, rel: str, data: dict[str, Any]) -> None:
        rtype = data.get("type")
        for other, fields in TYPE_FIELDS.items():
            if other == rtype:
                continue
            for field in fields:
                if field in data and rtype not in ALSO_ALLOWED.get(field, ()):
                    self.warn(rel, field, f"field belongs to type {other!r}, record is {rtype!r}")
        if isinstance(data.get("homepage"), str) and not is_http_url(data["homepage"]):
            self.error(rel, "homepage", "not an absolute http(s) URL")
        for i, link in enumerate(data.get("access_links", []) or []):
            if isinstance(link, dict) and not is_http_url(link.get("url")):
                self.error(rel, f"access_links/{i}/url", "not an absolute http(s) URL")
        for i, src in enumerate(data.get("sources", []) or []):
            if isinstance(src, dict) and not is_http_url(src.get("url")):
                self.error(rel, f"sources/{i}/url", "not an absolute http(s) URL (the page a fact was read on must be followable)")
        keys = data.get("dedupe_keys") or {}
        if isinstance(keys, dict):
            if keys.get("url") and normalise_url(keys["url"]) != keys["url"]:
                self.warn(rel, "dedupe_keys/url", f"not in normalised form; expected {normalise_url(keys['url'])!r}")
            if keys.get("doi") and normalise_doi(keys["doi"]) != keys["doi"]:
                self.warn(rel, "dedupe_keys/doi", f"not in normalised form; expected {normalise_doi(keys['doi'])!r}")
            if keys.get("repo") and normalise_repo(keys["repo"]) != keys["repo"]:
                self.warn(rel, "dedupe_keys/repo", f"not in normalised form; expected {normalise_repo(keys['repo'])!r}")
            if keys.get("name") and normalise_name(keys["name"]) != keys["name"]:
                self.warn(rel, "dedupe_keys/name", f"not in normalised form; expected {normalise_name(keys['name'])!r}")
            if not keys.get("url") and effective_dedupe_keys(data).get("url"):
                self.warn(rel, "dedupe_keys/url", "missing; the deduplicator will derive it from the homepage")
        cat, ver, chk = (parse_date(data.get(k)) for k in ("date_catalogued", "date_verified", "description_checked"))
        if cat and ver and ver < cat:
            self.warn(rel, "date_verified", "earlier than date_catalogued")
        if cat and chk and chk < cat:
            self.warn(rel, "description_checked", "earlier than date_catalogued")
        for i, entry in enumerate(data.get("discovery_routes", []) or []):
            if isinstance(entry, dict) and entry.get("route") in self.vocab.route_classes and not self.vocab.route_family(entry["route"]):
                self.warn(rel, f"discovery_routes/{i}/route", "route has no family in vocab.yaml")
        if data.get("type") == "model" and isinstance(data.get("repository"), str) and not is_http_url(data["repository"]):
            self.warn(rel, "repository", "not an absolute http(s) URL")

    # -- catalogue level -------------------------------------------------------
    def check_schema_md_drift(self) -> None:
        """Every record-vocabulary value in vocab.yaml must appear back-ticked in schema.md."""
        path = self.paths.schema_md
        if not path.exists():
            self.error("schema.md", "", f"{path} not found; cannot check vocabulary drift")
            return
        text = path.read_text(encoding="utf-8")
        listed = set(re.findall(r"`([^`]+)`", text))
        for vocab_name, values in self.vocab.record_vocabularies().items():
            for value in values:
                if value not in listed:
                    self.error("schema.md", vocab_name, f"vocab.yaml value {value!r} is not listed in schema.md")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def summarise(issues: list[Issue], records: list[RecordFile]) -> dict[str, Any]:
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    by_type = Counter(r.type for r in records if not r.error)
    failing = {i.record for i in errors}
    return {
        "records": len(records),
        "by_type": {t: by_type.get(t, 0) for t in RECORD_TYPES},
        "errors": len(errors),
        "warnings": len(warnings),
        "records_with_errors": len([r for r in records if r.path.relative_to(r.path.parents[1]).as_posix() in failing]),
        "ok": not errors,
    }


def print_report(issues: list[Issue], records: list[RecordFile], summary: dict[str, Any]) -> None:
    print(f"validate: {summary['records']} records ({', '.join(f'{k} {v}' for k, v in summary['by_type'].items())})")
    for issue in issues:
        print(f"  {issue}")
    print(f"validate: {summary['errors']} errors, {summary['warnings']} warnings -> {'OK' if summary['ok'] else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(parser)
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--no-drift", action="store_true", help="skip the schema.md versus vocab.yaml drift check")
    parser.add_argument("--strict-description", action="store_true", help="treat missing description elements as errors")
    parser.add_argument("--warnings-as-errors", action="store_true", help="exit non-zero on warnings too")
    args = parser.parse_args(argv)

    paths = Paths.from_args(args.project, args.schema_dir)
    validator = Validator(paths, strict_description=args.strict_description)
    issues = validator.run(check_drift=not args.no_drift)
    summary = summarise(issues, validator.records)
    if args.json:
        print(json.dumps({"summary": summary, "issues": [asdict(i) for i in issues]}, indent=2, ensure_ascii=False))
    else:
        print_report(issues, validator.records, summary)
    failed = summary["errors"] > 0 or (args.warnings_as_errors and summary["warnings"] > 0)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
