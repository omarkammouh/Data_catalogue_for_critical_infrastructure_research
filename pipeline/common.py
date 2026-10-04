"""Shared helpers for the catalogue pipeline.

This module is the single place where the pipeline learns where files live,
how the controlled vocabularies are structured, how records and sweep-log
entries are read, and how identifiers (URLs, DOIs, repository URLs, names)
are normalised before comparison. Every other script in ``pipeline``
imports from here so that the same rules apply throughout.

Conventions that matter for the paper's methods section:

* **Paths.** All inputs and outputs are resolved from one project directory
  (``--project``). The controlled vocabularies are read from a separate schema
  directory (``--schema-dir``) that defaults to the real ``schema``, so
  a test fixture can be validated against the real schema without copying it.
* **Records** are one JSON object per file under ``catalog/<type>/<id>.json``.
  Reading is tolerant (a broken file is reported, not fatal) so that
  ``validate.py`` can list every problem in one run.
* **Sweep log** (``sources/sweeps.jsonl``) holds one JSON object per query run
  against a registered source. Its ``cell`` field addresses a cell of the search
  space at either the global grain (``type:sector:facet``) or the national grain
  (``country:CC:group:organisation_class``); see :func:`parse_cell`.
* **Normalisation** is deterministic and documented in each function's
  docstring so that the deduplication rules (mechanism M14 of the roadmap) can
  be described precisely.
"""

from __future__ import annotations

import csv
import datetime as dt
import fcntl
import hashlib
import json
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

PIPELINE_DIR = Path(__file__).resolve().parent
REAL_PROJECT_DIR = PIPELINE_DIR.parent
REPO_ROOT = REAL_PROJECT_DIR.parent
RECORD_TYPES: tuple[str, ...] = ("data", "model", "platform", "case_study")


@dataclass(frozen=True)
class Paths:
    """Every file the pipeline reads or writes, derived from one project directory.

    ``project`` is the directory that holds ``catalog/``, ``sources/`` and
    ``docs/``. ``schema_dir`` holds ``vocab.yaml`` and ``record.schema.json``
    and defaults to the real project's schema so fixtures share it.
    """

    project: Path
    schema_dir: Path

    @classmethod
    def from_args(cls, project: str | Path | None = None, schema_dir: str | Path | None = None) -> "Paths":
        proj = Path(project).resolve() if project else REAL_PROJECT_DIR
        schema = Path(schema_dir).resolve() if schema_dir else REAL_PROJECT_DIR / "schema"
        return cls(project=proj, schema_dir=schema)

    # schema
    @property
    def vocab(self) -> Path:
        return self.schema_dir / "vocab.yaml"

    @property
    def record_schema(self) -> Path:
        return self.schema_dir / "record.schema.json"

    @property
    def schema_md(self) -> Path:
        """schema.md sits next to the schema directory (schema.md)."""
        return self.schema_dir.parent / "schema.md"

    # catalogue
    @property
    def catalog_dir(self) -> Path:
        return self.project / "catalog"

    @property
    def catalog_json(self) -> Path:
        return self.catalog_dir / "catalog.json"

    @property
    def catalog_sqlite(self) -> Path:
        return self.catalog_dir / "catalog.sqlite"

    # sources
    @property
    def sources_dir(self) -> Path:
        return self.project / "sources"

    @property
    def sweeps(self) -> Path:
        return self.sources_dir / "sweeps.jsonl"

    @property
    def candidates_dir(self) -> Path:
        return self.sources_dir / "candidates"

    @property
    def merges(self) -> Path:
        return self.sources_dir / "merges.jsonl"

    @property
    def linkchecks(self) -> Path:
        """Append-only log of link checks: one JSON line per URL per applied run (see ``linkcheck.py``)."""
        return self.sources_dir / "linkchecks.jsonl"

    @property
    def organisations(self) -> Path:
        return self.sources_dir / "organisations.csv"

    @property
    def register(self) -> Path:
        return self.sources_dir / "register.yaml"

    @property
    def negative_results(self) -> Path:
        """The negative-result registry (M27), read by ``negatives.py``."""
        return self.sources_dir / "negative_results.yaml"

    # docs
    @property
    def docs_dir(self) -> Path:
        return self.project / "docs"

    @property
    def coverage_md(self) -> Path:
        return self.docs_dir / "coverage.md"

    @property
    def coverage_json(self) -> Path:
        return self.docs_dir / "coverage.json"

    @property
    def coverage_priors(self) -> Path:
        return self.docs_dir / "coverage_priors.csv"

    @property
    def gold_dir(self) -> Path:
        return self.docs_dir / "gold_lists"

    @property
    def paper_dir(self) -> Path:
        return self.docs_dir / "paper"

    @property
    def statistics_dir(self) -> Path:
        return self.paper_dir / "statistics"

    @property
    def snapshots(self) -> Path:
        return self.paper_dir / "snapshots.jsonl"

    @property
    def dashboard_build(self) -> Path:
        return self.project / "dashboard" / "build.py"


def add_common_args(parser: Any) -> None:
    """Add ``--project`` and ``--schema-dir`` to an argparse parser."""
    parser.add_argument("--project", default=None, help="project directory holding catalog/, sources/, docs/ (default: the real project)")
    parser.add_argument("--schema-dir", default=None, help="directory holding vocab.yaml and record.schema.json (default: schema of the real project)")


# --------------------------------------------------------------------------- #
# Dates and small utilities
# --------------------------------------------------------------------------- #

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> str:
    """Today's date as ISO ``YYYY-MM-DD`` (local time)."""
    return dt.date.today().isoformat()


def parse_date(value: Any) -> dt.date | None:
    """Parse an ISO date string; return None when it is not a full date."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def word_count(text: str) -> int:
    """Count words as maximal runs of non-whitespace characters."""
    return len(text.split())


def _json_default(value: Any) -> Any:
    """Serialise the non-JSON types the pipeline meets: dates (from YAML) as ISO strings, sets as sorted lists."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dump_json(obj: Any, path: Path, *, sort_keys: bool = True) -> None:
    """Write JSON deterministically: UTF-8, two-space indent, sorted keys, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=sort_keys, default=_json_default) + "\n"
    path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(line_number, object)`` for each non-blank, non-comment line of a JSONL file.

    Lines starting with ``#`` are ignored so that a log can carry a header.
    A malformed line raises ``ValueError`` naming the line.
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{n}: expected a JSON object")
            yield n, obj


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    """Append one compact JSON object as a line, creating the file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV into dicts with lower-cased, underscore-joined header names; empty file gives []."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, str]] = []
        for row in reader:
            clean = {}
            for key, value in row.items():
                if key is None:
                    continue
                norm = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
                clean[norm] = (value or "").strip()
            rows.append(clean)
        return rows


def first_present(row: dict[str, str], *names: str) -> str:
    """Return the first non-empty value among alternative column names."""
    for name in names:
        if row.get(name):
            return row[name]
    return ""


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


class Vocab:
    """Typed access to ``schema/vocab.yaml``.

    The YAML holds nested structures (sector groups, data-family groups, route
    classes); this class flattens them into the lists the validator, the
    coverage matrix and the statistics need, without changing their meaning.
    """

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @classmethod
    def load(cls, path: Path) -> "Vocab":
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: vocabulary file must be a mapping")
        return cls(raw)

    # -- simple lists -------------------------------------------------------
    def list(self, key: str) -> list[str]:
        value = self.raw.get(key, [])
        if isinstance(value, dict):
            return list(value.keys())
        return list(value)

    @property
    def version(self) -> Any:
        return self.raw.get("version")

    @property
    def updated(self) -> Any:
        return self.raw.get("updated")

    @property
    def types(self) -> list[str]:
        return list(self.raw.get("types", {}).keys()) or list(RECORD_TYPES)

    # -- sectors ------------------------------------------------------------
    @property
    def sector_groups(self) -> dict[str, list[str]]:
        """Mapping group -> ordered list of sector names (without the group prefix)."""
        out: dict[str, list[str]] = {}
        for group, body in self.raw.get("sectors", {}).items():
            sectors = body.get("sectors", {}) if isinstance(body, dict) else {}
            out[group] = list(sectors.keys())
        return out

    def group_label(self, group: str) -> str:
        body = self.raw.get("sectors", {}).get(group, {})
        return body.get("label", group) if isinstance(body, dict) else group

    @property
    def sectors(self) -> list[str]:
        """Every two-level sector value ``group.sector`` in vocabulary order."""
        return [f"{g}.{s}" for g, sectors in self.sector_groups.items() for s in sectors]

    @property
    def sector_values(self) -> set[str]:
        """Values a record may use in ``sectors``: every ``group.sector`` and every bare group."""
        return set(self.sectors) | set(self.sector_groups.keys())

    def is_sector(self, value: str) -> bool:
        return value in self.sector_values

    def sector_group(self, value: str) -> str | None:
        """Group of a sector value; a bare group maps to itself; unknown values give None."""
        if value in self.sector_groups:
            return value
        group, _, sector = value.partition(".")
        if sector and sector in self.sector_groups.get(group, []):
            return group
        return None

    def expand_sector(self, value: str) -> list[str]:
        """Expand a bare group to all its ``group.sector`` values; a sector maps to itself."""
        if value in self.sector_groups:
            return [f"{value}.{s}" for s in self.sector_groups[value]]
        return [value] if value in self.sector_values else []

    # -- data families ------------------------------------------------------
    @property
    def data_family_groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for group, families in self.raw.get("data_families", {}).items():
            out[group] = list(families.keys()) if isinstance(families, dict) else list(families)
        return out

    @property
    def data_families(self) -> list[str]:
        return [f for fams in self.data_family_groups.values() for f in fams]

    # -- kinds and other lists ---------------------------------------------
    @property
    def data_kinds(self) -> list[str]:
        return self.list("data_kinds")

    @property
    def model_kinds(self) -> list[str]:
        return self.list("model_kinds")

    @property
    def platform_kinds(self) -> list[str]:
        return self.list("platform_kinds")

    @property
    def case_study_kinds(self) -> list[str]:
        return self.list("case_study_kinds")

    @property
    def hazard_types(self) -> list[str]:
        return self.list("hazard_types")

    @property
    def simulation_uses(self) -> list[str]:
        return self.list("simulation_uses")

    @property
    def maturity(self) -> list[str]:
        return self.list("maturity")

    @property
    def cost(self) -> list[str]:
        return self.list("cost")

    @property
    def access_restrictions(self) -> list[str]:
        return self.list("access_restrictions")

    @property
    def geographic_scope(self) -> list[str]:
        return self.list("geographic_scope")

    @property
    def continents(self) -> list[str]:
        return self.list("continents")

    @property
    def access_link_kinds(self) -> list[str]:
        return self.list("access_link_kinds")

    @property
    def cell_status(self) -> list[str]:
        return self.list("cell_status")

    @property
    def coverage_prior(self) -> list[str]:
        return self.list("coverage_prior")

    @property
    def candidate_status(self) -> list[str]:
        return self.list("candidate_status")

    # -- routes -------------------------------------------------------------
    @property
    def route_families(self) -> dict[str, str]:
        """Mapping family id -> description."""
        return dict(self.raw.get("route_families", {}))

    @property
    def route_classes(self) -> dict[str, dict[str, Any]]:
        """Mapping route id (R01..) -> {name, family, mode}."""
        return dict(self.raw.get("route_classes", {}))

    def route_family(self, route: str | None) -> str | None:
        """Family of a route id, or None when the route is unknown."""
        if not route:
            return None
        body = self.route_classes.get(route)
        return body.get("family") if isinstance(body, dict) else None

    def facets_for_type(self, rtype: str) -> list[str]:
        """The second axis of the global grain per type (M01): family, model kind or platform kind."""
        if rtype == "data":
            return self.data_families
        if rtype == "model":
            return self.model_kinds
        if rtype == "platform":
            return self.platform_kinds
        if rtype == "case_study":
            return self.case_study_kinds
        return []

    def facet_field_for_type(self, rtype: str) -> str:
        """Record field holding the facet values for a type."""
        return {"data": "data_family", "model": "model_kind", "platform": "platform_kind", "case_study": "case_study_kind"}.get(rtype, "")

    def record_vocabularies(self) -> dict[str, list[str]]:
        """Vocabularies whose values appear in record fields (the ones schema.md must list).

        Route classes, route families, cell statuses, coverage priors and
        candidate statuses are pipeline vocabularies; schema.md delegates them
        to vocab.yaml explicitly, so they are not part of the drift check.
        """
        return {
            "sectors (groups)": list(self.sector_groups.keys()),
            "sectors": [s.split(".", 1)[1] for s in self.sectors],
            "data_families": self.data_families,
            "data_kinds": self.data_kinds,
            "model_kinds": self.model_kinds,
            "platform_kinds": self.platform_kinds,
            "case_study_kinds": self.case_study_kinds,
            "hazard_types": self.hazard_types,
            "simulation_uses": self.simulation_uses,
            "maturity": self.maturity,
            "cost": self.cost,
            "access_restrictions": self.access_restrictions,
            "geographic_scope": self.geographic_scope,
            "continents": self.continents,
            "access_link_kinds": self.access_link_kinds,
        }


def load_vocab(paths: Paths) -> Vocab:
    return Vocab.load(paths.vocab)


def load_record_schema(paths: Paths) -> dict[str, Any]:
    with paths.record_schema.open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class RecordFile:
    """A record as stored on disk: its path, the type folder it sits in, and its content.

    ``error`` is set when the file could not be parsed; ``data`` is then empty.
    """

    path: Path
    folder: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def id(self) -> str:
        return str(self.data.get("id") or self.path.stem)

    @property
    def type(self) -> str:
        return str(self.data.get("type") or self.folder)

    @property
    def name(self) -> str:
        return str(self.data.get("name") or "")

    @property
    def provider(self) -> str:
        return str(self.data.get("provider") or "")

    def sectors(self) -> list[str]:
        return [s for s in self.data.get("sectors", []) if isinstance(s, str)]

    def facets(self, vocab: Vocab) -> list[str]:
        """Values on the type's facet axis (data_family, model_kind, platform_kind or case_study_kind)."""
        fld = vocab.facet_field_for_type(self.type)
        return [v for v in self.data.get(fld, []) if isinstance(v, str)] if fld else []

    def cells(self, vocab: Vocab) -> list[str]:
        """Global-grain cells this record fills: each (expanded) sector x each facet value.

        A bare sector group in ``sectors`` counts for every sector of the group,
        because such a record spans the whole group by definition (schema.md).
        """
        out: list[str] = []
        for sector in self.sectors():
            for expanded in vocab.expand_sector(sector):
                for facet in self.facets(vocab):
                    out.append(f"{self.type}:{expanded}:{facet}")
        return sorted(set(out))

    def route_families(self, vocab: Vocab) -> set[str]:
        """Distinct route families among the record's discovery routes (M25)."""
        fams = set()
        for entry in self.data.get("discovery_routes", []) or []:
            fam = vocab.route_family(entry.get("route") if isinstance(entry, dict) else None)
            if fam:
                fams.add(fam)
        return fams

    def urls(self) -> list[tuple[str, str]]:
        """``(label, url)`` for the homepage and every access link, in record order."""
        out: list[tuple[str, str]] = []
        if isinstance(self.data.get("homepage"), str):
            out.append(("homepage", self.data["homepage"]))
        for link in self.data.get("access_links", []) or []:
            if isinstance(link, dict) and isinstance(link.get("url"), str):
                out.append((str(link.get("label") or link.get("kind") or "link"), link["url"]))
        return out


def iter_record_files(catalog_dir: Path) -> Iterator[Path]:
    """Yield record paths in deterministic order: by type folder, then file name."""
    for rtype in RECORD_TYPES:
        folder = catalog_dir / rtype
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            yield path


def load_records(catalog_dir: Path) -> list[RecordFile]:
    """Load every record under ``catalog/{data,model,platform}/*.json``.

    Files that fail to parse are returned with ``error`` set rather than raised,
    so callers can report every problem in one pass.
    """
    records: list[RecordFile] = []
    for path in iter_record_files(catalog_dir):
        folder = path.parent.name
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                records.append(RecordFile(path, folder, {}, "top-level JSON value is not an object"))
                continue
            records.append(RecordFile(path, folder, data))
        except (OSError, json.JSONDecodeError) as exc:
            records.append(RecordFile(path, folder, {}, f"cannot parse: {exc}"))
    return records


def valid_records(catalog_dir: Path) -> list[RecordFile]:
    """Records that parsed; sorted by (type, id)."""
    return sorted((r for r in load_records(catalog_dir) if not r.error), key=lambda r: (r.type, r.id))


def write_record(record: RecordFile) -> None:
    """Write a record back preserving its key order (two-space indent, UTF-8)."""
    record.path.write_text(json.dumps(record.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Normalisation (mechanism M14, M18)
# --------------------------------------------------------------------------- #

TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "pk_", "piwik_", "matomo_", "hsa_", "vero_", "oly_")
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "twclid", "ttclid",
    "igshid", "mkt_tok", "_ga", "_gl", "_hsenc", "_hsmi", "ref", "ref_src", "ref_url",
    "referrer", "source", "si", "spm", "trk", "trkinfo", "cmpid", "s_kwcid", "ncid",
    "fb_action_ids", "fb_action_types", "fb_source", "action_object_map", "action_type_map",
}
DOI_HOSTS = {"doi.org", "dx.doi.org", "hdl.handle.net"}
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
REPO_HOSTS = {"github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "gitee.com", "sourceforge.net"}
REPO_DEEP_SEGMENTS = frozenset({"-", "tree", "blob", "releases", "issues", "wiki", "pull", "pulls", "commit", "commits", "src", "tags", "archive", "raw"})
"""Path segments that start a deep link inside a repository (``/tree/main``, ``/-/blob/...``). Matched as whole
segments, never as prefixes: ``/org/releases-tool`` is a repository, not the releases page of ``/org``."""


def normalise_doi(value: str | None) -> str | None:
    """Reduce any DOI spelling to the bare lower-case identifier ``10.xxxx/yyyy``.

    Accepts ``doi:10.1/abc``, ``https://doi.org/10.1/abc``, ``DOI: 10.1/ABC`` and
    the bare form. Trailing punctuation is stripped. Returns None when no DOI
    is present. DOIs are case-insensitive by specification, hence lower-casing.
    """
    if not value or not isinstance(value, str):
        return None
    match = DOI_RE.search(value.strip())
    if not match:
        return None
    return match.group(1).rstrip(".,;:)]}").lower()


def normalise_url(value: str | None) -> str | None:
    """Canonical form of a URL for exact-match deduplication.

    Rules, applied in order:

    1. strip surrounding whitespace; a bare ``host/path`` gets ``https://``;
    2. scheme lower-cased, ``http`` mapped to ``https`` (the same resource served on
       both is one resource), the host lower-cased, a leading ``www.`` removed,
       default ports removed;
    3. the fragment is dropped;
    4. tracking query parameters (``utm_*``, ``fbclid``, ``gclid`` and the like) are
       removed and the remaining parameters sorted, so parameter order does not
       create false distinctions;
    5. a trailing slash is removed (the root path becomes empty);
    6. a DOI resolver URL (``doi.org``, ``dx.doi.org``) becomes ``doi:10.xxxx/yyyy``
       so that the DOI and its resolver link compare equal.

    Returns None for empty input. The result is a key, not a fetchable URL.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.lower().startswith("doi:"):
        doi = normalise_doi(text)
        return f"doi:{doi}" if doi else None
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in DOI_HOSTS and host != "hdl.handle.net":
        doi = normalise_doi(parts.path)
        if doi:
            return f"doi:{doi}"
    try:
        port = parts.port
    except ValueError:  # port out of range or not a number: keep the text as written rather than crash the run
        port = None
        host = (parts.netloc.rsplit("@", 1)[-1]).lower()
        if host.startswith("www."):
            host = host[4:]
    netloc = host
    if port and port not in (80, 443):  # default ports of http and https (http is mapped to https above, so test both)
        netloc = f"{host}:{port}"
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower() in TRACKING_PARAMS or k.lower().startswith(TRACKING_PARAM_PREFIXES))
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    path = parts.path
    if path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def is_site_root_key(key: str | None) -> bool:
    """True when a normalised URL key is a bare site root (``https://epa.gov``: no path, no query).

    Many providers' datasets and tools share the provider's home page, so a site
    root identifies a publisher, not a resource. Matching on it alone merged
    distinct resources (audit 2026-09-24); callers require agreeing names too.
    """
    if not key or key.startswith("doi:"):
        return False
    parts = urlsplit(key)
    return bool(parts.netloc) and parts.path in ("", "/") and not parts.query


def normalise_repo(value: str | None) -> str | None:
    """Canonical ``host/owner/name`` for a code repository URL.

    Handles ``git@github.com:owner/name.git`` (SSH form), ``.git`` suffixes and
    the deep links people paste (``/tree/main``, ``/blob/...``, ``/-/tree``,
    ``/releases``); the host is lower-cased and ``www.`` removed. A deep link
    is cut at the first whole path segment of :data:`REPO_DEEP_SEGMENTS` after
    ``owner/name``, so a repository whose own name merely starts like one
    (``releases-tool``, ``wikidata-toolkit``, ``archiver``) is kept intact (audit
    2026-09-24: the former substring cut collapsed such repositories onto their
    owner and let dedupe merge distinct repositories). GitHub-like forges keep
    ``owner/name``; GitLab keeps every sub-group up to ``/-/``; SourceForge keeps
    ``projects/name``; other hosts keep the path up to the first deep-link
    segment. Returns None for empty input.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    ssh = re.match(r"^(?:git\+ssh://)?git@([^:/]+)[:/](.+)$", text)
    if ssh:
        text = f"https://{ssh.group(1)}/{ssh.group(2)}"
    if text.startswith("git+"):
        text = text[4:]
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    segments = [s for s in parts.path.split("/") if s]
    if host == "sourceforge.net" and segments[:1] == ["projects"]:
        segments = segments[:2]
    elif host in REPO_HOSTS and host != "gitlab.com":
        segments = segments[:2]
    else:
        # GitLab and self-hosted forges: owner, sub-groups and name, up to the first deep-link segment after owner/name
        for i, seg in enumerate(segments):
            if i >= 2 and seg.lower() in REPO_DEEP_SEGMENTS:
                segments = segments[:i]
                break
            if seg == "-":  # GitLab's separator is unambiguous at any depth
                segments = segments[:i]
                break
    if segments and segments[-1].lower().endswith(".git"):
        segments[-1] = segments[-1][:-4]
    path = "/".join(s for s in segments if s)
    if not host or not path:
        return None
    return f"{host}/{path}".lower()


NAME_STOPWORDS = {"the", "a", "an", "of", "and", "for", "de", "la", "le", "der", "die", "das", "du", "des"}


def normalise_name(value: str | None, *, drop_stopwords: bool = False) -> str:
    """Lower-case, accent-stripped, punctuation-free, whitespace-collapsed name.

    Unicode NFKD decomposition followed by removal of combining marks turns
    ``Réseau`` into ``reseau`` so that names typed with and without accents
    compare equal (part of cross-language identity, M18). Optionally removes
    articles and prepositions in a few languages for the fuzzy matcher.
    """
    if not value or not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"_", " ", text)
    tokens = text.split()
    if drop_stopwords:
        tokens = [t for t in tokens if t not in NAME_STOPWORDS]
    return " ".join(tokens)


HOSTNAME_RE = re.compile(r"^(?:\[[0-9a-fA-F:.]+\]|[^\s/?#@:\[\]]+)$")


def is_http_url(value: Any) -> bool:
    """True for an absolute http(s) URL with a well-formed host.

    Rejects (audit 2026-09-24) any whitespace or control character anywhere in
    the URL (``https://exa mple.com/ x`` passed before and could crash later
    steps), an empty or malformed host, and a port that is not a number in
    0-65535. Leading and trailing whitespace is also an error, because a record
    stores the URL exactly as it will be followed. Non-ASCII host names
    (internationalised domains) are accepted.
    """
    if not isinstance(value, str) or not value:
        return False
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    try:
        parts = urlsplit(value)
        parts.port  # raises ValueError for a bad port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = parts.netloc.rsplit("@", 1)[-1]
    if host.startswith("["):
        host = host[: host.find("]") + 1] if "]" in host else host
    else:
        host = host.split(":", 1)[0]
    if not host or not HOSTNAME_RE.match(host) or host.startswith(".") or ".." in host:
        return False
    return True


def derived_dedupe_keys(data: dict[str, Any]) -> dict[str, str]:
    """Dedupe keys computed from a record's own fields.

    ``url`` from the homepage, ``repo`` from the ``repository`` field or the
    first access link of kind ``repo``, ``doi`` from ``citation`` or any access
    link of kind ``paper`` that carries a DOI, ``name`` from the name. Explicit
    ``dedupe_keys`` on the record take precedence in :func:`effective_dedupe_keys`.
    """
    keys: dict[str, str] = {}
    url = normalise_url(data.get("homepage"))
    if url:
        keys["url"] = url
    repo_src = data.get("repository")
    if not repo_src:
        for link in data.get("access_links", []) or []:
            if isinstance(link, dict) and link.get("kind") == "repo":
                repo_src = link.get("url")
                break
    repo = normalise_repo(repo_src) if isinstance(repo_src, str) else None
    if repo:
        keys["repo"] = repo
    doi = normalise_doi(data.get("citation")) if isinstance(data.get("citation"), str) else None
    if not doi:
        for link in data.get("access_links", []) or []:
            if isinstance(link, dict) and link.get("kind") == "paper":
                doi = normalise_doi(link.get("url"))
                if doi:
                    break
    if doi:
        keys["doi"] = doi
    name = normalise_name(data.get("name"))
    if name:
        keys["name"] = name
    return keys


def effective_dedupe_keys(data: dict[str, Any]) -> dict[str, str]:
    """Explicit ``dedupe_keys`` (normalised again, defensively) merged over derived ones."""
    keys = derived_dedupe_keys(data)
    explicit = data.get("dedupe_keys") or {}
    if isinstance(explicit, dict):
        if explicit.get("url"):
            keys["url"] = normalise_url(explicit["url"]) or keys.get("url", "")
        if explicit.get("doi"):
            keys["doi"] = normalise_doi(explicit["doi"]) or keys.get("doi", "")
        if explicit.get("repo"):
            keys["repo"] = normalise_repo(explicit["repo"]) or keys.get("repo", "")
        if explicit.get("name"):
            keys["name"] = normalise_name(explicit["name"]) or keys.get("name", "")
    return {k: v for k, v in keys.items() if v}


# --------------------------------------------------------------------------- #
# Languages and countries (pycountry)
# --------------------------------------------------------------------------- #

EXTRA_COUNTRY_CODES = {"XK"}  # Kosovo: user-assigned ISO 3166 code in wide use, absent from pycountry


def is_language_code(code: Any) -> bool:
    """True for an ISO 639-1 (two-letter) or ISO 639-2/3 (three-letter) language code known to pycountry.

    Both the terminology (``deu``) and bibliographic (``ger``) three-letter codes are accepted.
    """
    import pycountry

    if not isinstance(code, str):
        return False
    code = code.strip().lower()
    if len(code) == 2:
        return pycountry.languages.get(alpha_2=code) is not None
    if len(code) == 3:
        if pycountry.languages.get(alpha_3=code) is not None:
            return True
        try:
            return pycountry.languages.get(bibliographic=code) is not None
        except (KeyError, LookupError):
            return False
    return False


def is_country_code(code: Any) -> bool:
    """True for an ISO 3166-1 alpha-2 code known to pycountry (plus XK for Kosovo)."""
    import pycountry

    if not isinstance(code, str) or len(code) != 2 or not code.isupper():
        return False
    if code in EXTRA_COUNTRY_CODES:
        return True
    return pycountry.countries.get(alpha_2=code) is not None


def country_name(code: str) -> str:
    """Display name of a country code, or the code itself when unknown."""
    import pycountry

    if code in EXTRA_COUNTRY_CODES:
        return {"XK": "Kosovo"}.get(code, code)
    country = pycountry.countries.get(alpha_2=code)
    return getattr(country, "name", code) if country else code


# --------------------------------------------------------------------------- #
# Sweep log and cells
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cell:
    """One cell of the search space.

    Global grain: ``type:sector:facet`` (``data:energy.electricity:system_description``,
    ``model:water.wastewater:physical``, ``platform:transport.rail:simulation_engine``,
    ``case_study:water.drinking_water:adaptation_planning``).
    National grain: ``country:CC:group:organisation_class`` (``country:DE:energy:regulator``).
    ``sector`` at the global grain may be a bare group; :meth:`expand` resolves it.
    """

    grain: str  # "global" or "national"
    key: str
    type: str = ""
    sector: str = ""
    facet: str = ""
    country: str = ""
    group: str = ""
    org_class: str = ""

    @property
    def sector_group(self) -> str:
        if self.grain == "national":
            return self.group
        return self.sector.split(".", 1)[0]


def parse_cell(text: str) -> Cell | None:
    """Parse a cell key; return None when it has neither recognised shape."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split(":")
    if len(parts) == 4 and parts[0] == "country":
        _, cc, group, org_class = parts
        return Cell(grain="national", key=text.strip(), country=cc.strip().upper(), group=group.strip(), org_class=org_class.strip())
    if len(parts) == 3 and parts[0] in RECORD_TYPES:
        rtype, sector, facet = (p.strip() for p in parts)
        return Cell(grain="global", key=f"{rtype}:{sector}:{facet}", type=rtype, sector=sector, facet=facet)
    return None


def expand_cell(cell: Cell, vocab: Vocab) -> list[Cell]:
    """A global-grain cell whose sector is a bare group expands to one cell per sector of the group."""
    if cell.grain != "global" or cell.sector not in vocab.sector_groups:
        return [cell]
    return [
        Cell(grain="global", key=f"{cell.type}:{s}:{cell.facet}", type=cell.type, sector=s, facet=cell.facet)
        for s in vocab.expand_sector(cell.sector)
    ]


@dataclass
class Sweep:
    """One line of ``sources/sweeps.jsonl``: a logged query against a registered source.

    ``cells`` holds every cell the query addressed (the log line may give one
    string or a list). ``family`` is taken from the log line or derived from the
    route. Counts default to zero when missing so arithmetic never fails.
    """

    line: int
    route: str
    family: str
    cells: list[str]
    source: str
    query: str
    language: str
    date: str
    n_returned: int
    n_new: int
    n_known: int
    raw: dict[str, Any] = field(default_factory=dict)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sweep_key(obj: dict[str, Any]) -> tuple[str, str, str] | None:
    meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
    if not meta.get("state"):
        return None
    return (str(obj.get("source") or ""), str(meta.get("state")), str(meta.get("run_id") or ""))


VOID_SWEEPS_FILE = "sweeps_void.csv"
"""Sweep-log lines shown afterwards to be no evidence (columns ``source, date, query, reason``), next to ``sweeps.jsonl``."""


def void_key(obj: dict[str, Any]) -> tuple[str, str, str]:
    """Identity of a sweep line for the void list: source, date and query text (case and spacing folded)."""
    return (str(obj.get("source") or ""), str(obj.get("date") or ""), " ".join(str(obj.get("query") or "").lower().split()))


def load_void_sweeps(path: Path) -> dict[tuple[str, str, str], str]:
    """The void list: sweep lines that the log keeps (it is append-only) but that are no evidence.

    A line goes on the list when it is shown to have reported something the source did not
    mean, for example a zero from a query syntax the source does not parse (HDX and quoted
    phrases joined by OR, round 1, 2026-09-26). Every entry carries its reason. Missing file
    gives an empty list.
    """
    if not path.is_file():
        return {}
    out: dict[tuple[str, str, str], str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[void_key(row)] = str(row.get("reason") or "").strip()
    return out


def read_sweeps(path: Path, vocab: Vocab | None = None) -> list[Sweep]:
    """Read the sweep log. Missing file gives []. A malformed line raises ValueError.

    Lines on the void list (:data:`VOID_SWEEPS_FILE`, :func:`load_void_sweeps`) are skipped.

    A harvest query that stops at its page limit and is resumed later writes one line per run,
    each with that run's own counts and ``meta.resumed = true`` on the continuations (audit
    2026-09-24). Such continuation lines are joined to the sweep they continue (same source,
    ``meta.state`` and ``meta.run_id``): counts are summed, the date and ``raw`` are the last
    run's, ``raw["joined_lines"]`` lists every line number. One query is therefore one sweep,
    counted once, however many runs it took. A restart (``meta.resumed`` false) is a new sweep.
    """
    sweeps: list[Sweep] = []
    open_sweeps: dict[tuple[str, str, str], Sweep] = {}
    void = load_void_sweeps(path.with_name(VOID_SWEEPS_FILE))
    for line_no, obj in read_jsonl(path):
        if void and void_key(obj) in void:
            continue
        key = _sweep_key(obj)
        meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
        if key is not None and meta.get("resumed") and key in open_sweeps:
            prev = open_sweeps[key]
            prev.n_returned += _as_int(obj.get("n_returned"))
            prev.n_new += _as_int(obj.get("n_new"))
            prev.n_known += _as_int(obj.get("n_known"))
            prev.date = str(obj.get("date") or prev.date)
            joined = list(prev.raw.get("joined_lines") or [prev.line])
            prev.raw = dict(obj, joined_lines=joined + [line_no])
            continue
        cell_value = obj.get("cell") or obj.get("cells") or []
        cells = [cell_value] if isinstance(cell_value, str) else [c for c in cell_value if isinstance(c, str)]
        route = str(obj.get("route") or "")
        family = str(obj.get("family") or "") or (vocab.route_family(route) or "" if vocab else "")
        sweeps.append(
            Sweep(
                line=line_no,
                route=route,
                family=family,
                cells=cells,
                source=str(obj.get("source") or ""),
                query=str(obj.get("query") or ""),
                language=str(obj.get("language") or "").lower(),
                date=str(obj.get("date") or ""),
                n_returned=_as_int(obj.get("n_returned")),
                n_new=_as_int(obj.get("n_new")),
                n_known=_as_int(obj.get("n_known")),
                raw=obj,
            )
        )
        if key is not None:
            open_sweeps[key] = sweeps[-1]
    return sweeps


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

CANDIDATE_FIELDS: tuple[str, ...] = (
    "candidate_id", "source", "route", "family", "query", "language", "cell", "found_date",
    "raw", "dedupe_keys", "status", "reason", "record_id",
)
PENDING_CANDIDATE_STATUSES = ("new", "in_review", "needs_vocab")


@dataclass
class CandidateFile:
    """All candidates of one source: ``sources/candidates/<source>.jsonl``."""

    path: Path
    source: str
    rows: list[dict[str, Any]]


CLOSED_CANDIDATE_DIR = "closed"
"""Subfolder holding each source's rejected and duplicate rows, ``candidates/closed/<source>.jsonl``
(2026-09-26: the merged DataCite queue passed 60 MB and GitHub refuses files over 100 MB). Loading
joins the two files, so every reader sees one queue per source; :func:`write_candidate_file` splits
them again by status. Harvesters append to the open file and read both (``KnownIndex``)."""


def closed_candidate_path(path: Path) -> Path:
    """Where the closed rows of the candidate file ``path`` live."""
    return path.parent / CLOSED_CANDIDATE_DIR / path.name


CLOSED_SHARD_MIN_ROWS = 10_000
"""A source with more closed rows than this keeps them in 16 shards, ``closed/<source>/<0-f>.jsonl``,
picked by a hash of ``candidate_id`` (2026-09-26: ``closed/datacite.jsonl`` passed GitHub's 50 MB
warning within hours of the split). ``closed/<source>.jsonl`` then stays as an empty file, because
round 1 branches may still append to it; reconcile moves such rows into their shards."""


def closed_shard_key(row: dict[str, Any]) -> str:
    """Shard of a closed row: the first hex digit of the SHA-1 of its ``candidate_id``."""
    ident = str(row.get("candidate_id") or json.dumps(row, sort_keys=True))
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()[0]


def closed_shard_dir(path: Path) -> Path:
    """Folder holding the closed shards of the candidate file ``path``."""
    return path.parent / CLOSED_CANDIDATE_DIR / path.stem


def _read_candidate_rows(path: Path) -> list[dict[str, Any]]:
    rows = [obj for _, obj in read_jsonl(path)] if path.is_file() else []
    closed = closed_candidate_path(path)
    if closed.is_file():
        rows.extend({**obj, "_in_closed_file": True} for _, obj in read_jsonl(closed))
    for shard in sorted(closed_shard_dir(path).glob("*.jsonl")):
        rows.extend({**obj, "_in_closed_file": True, "_closed_shard": shard.stem} for _, obj in read_jsonl(shard))
    return rows


def misplaced_closed_rows(rows: list[dict[str, Any]]) -> int:
    """Closed rows not in the file :func:`write_candidate_file` would put them in (flat file versus shard)."""
    closed = [r for r in rows if r.get("status") in CLOSED_CANDIDATE_STATUSES and r.get("_in_closed_file")]
    total = sum(1 for r in rows if r.get("status") in CLOSED_CANDIDATE_STATUSES)
    sharded = total > CLOSED_SHARD_MIN_ROWS
    return sum(1 for r in closed if r.get("_closed_shard") != (closed_shard_key(r) if sharded else None))


def misfiled_candidate(row: dict[str, Any]) -> bool:
    """True when a row sits in the wrong part of its source's queue (open file versus ``closed/``)."""
    return (row.get("status") in CLOSED_CANDIDATE_STATUSES) != bool(row.get("_in_closed_file"))


def load_candidate_files(candidates_dir: Path) -> list[CandidateFile]:
    """Load every ``<source>.jsonl`` (with its closed rows) under the candidates directory, sorted by source name."""
    files: list[CandidateFile] = []
    if not candidates_dir.is_dir():
        return files
    names = {p.name for p in candidates_dir.glob("*.jsonl")}
    names |= {p.name for p in (candidates_dir / CLOSED_CANDIDATE_DIR).glob("*.jsonl")}
    names |= {f"{p.name}.jsonl" for p in (candidates_dir / CLOSED_CANDIDATE_DIR).glob("*/") if any(p.glob("*.jsonl"))}
    for name in sorted(names):
        path = candidates_dir / name
        files.append(CandidateFile(path=path, source=path.stem, rows=_read_candidate_rows(path)))
    return files


def all_candidates(candidates_dir: Path) -> list[dict[str, Any]]:
    """Flat list of candidate rows across sources, each tagged with ``_source_file``."""
    out: list[dict[str, Any]] = []
    for cf in load_candidate_files(candidates_dir):
        for row in cf.rows:
            tagged = dict(row)
            tagged.setdefault("source", cf.source)
            tagged["_source_file"] = str(cf.path)
            out.append(tagged)
    return out


CANDIDATES_LOCK = ".lock"
"""Lock file in the candidates folder. Every writer holds it: harvesters while appending, and
``candidates.py``/``dedupe.py`` while reading and rewriting, so a rewrite never drops lines a
parallel harvester appended (round 1 transport piece, 2026-09-26). Not committed (.gitignore)."""


@contextmanager
def candidates_lock(candidates_dir: Path) -> Iterator[None]:
    """Hold the exclusive lock on the candidate queue (blocking) for the duration of the block."""
    candidates_dir.mkdir(parents=True, exist_ok=True)
    with (candidates_dir / CANDIDATES_LOCK).open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_candidate_file(candidates_dir: Path, source: str) -> CandidateFile:
    """One source's candidate file (empty when it does not exist yet)."""
    path = candidates_dir / f"{source}.jsonl"
    return CandidateFile(path=path, source=source, rows=_read_candidate_rows(path))


CANDIDATE_DESCRIPTION_MAX = 500
"""Characters of a harvested description kept in the candidate queue (2026-09-26: the DataCite queue
file reached GitHub's 50 MB warning and would pass its 100 MB push limit as harvesting continued).
Screening needs only the opening, and a record is written from the provider's page read that day,
never from the queue, so nothing a record needs is lost. The original length is kept in
``raw.description_chars``; ``sources/harvesters/base.py`` applies the same cut when it writes."""


def trim_candidate_description(row: dict[str, Any]) -> bool:
    """Cut ``raw.description`` to :data:`CANDIDATE_DESCRIPTION_MAX` characters; True when the row changed.

    Idempotent: a row that carries ``raw.description_chars`` has been cut already.
    """
    raw = row.get("raw")
    if not isinstance(raw, dict) or "description_chars" in raw:
        return False
    text = raw.get("description")
    if not isinstance(text, str) or len(text) <= CANDIDATE_DESCRIPTION_MAX:
        return False
    raw["description"] = text[:CANDIDATE_DESCRIPTION_MAX].rstrip() + " […]"
    raw["description_chars"] = len(text)
    return True


CLOSED_CANDIDATE_STATUSES = ("rejected", "duplicate")
CLOSED_RAW_KEYS = (
    "name", "title", "url", "homepage", "doi", "concept_doi", "identifier", "repo", "repository",
    "publisher", "kind", "resource_type", "year", "created", "published", "licence", "language", "version",
)
CLOSED_DESCRIPTION_MAX = 200
"""A rejected or duplicate candidate keeps only what identifies it and why it was closed (2026-09-26:
the DataCite queue passed 55 MB with half its rows rejected). Its ``status``, ``reason``, provenance and
``dedupe_keys`` stay, so it is still excluded from re-harvest and counted in capture statistics; the
other harvested fields (tags, related identifiers, creators, file sizes, harvest details) are dropped
and can be fetched again from the source by DOI or URL. ``raw.compacted`` lists what was dropped."""


def compact_closed_candidate(row: dict[str, Any]) -> bool:
    """Shrink ``raw`` of a rejected or duplicate candidate to :data:`CLOSED_RAW_KEYS`; True when the row changed.

    Idempotent: a row whose ``raw`` carries ``compacted`` is left alone. Rows in any other status are never touched.
    """
    raw = row.get("raw")
    if row.get("status") not in CLOSED_CANDIDATE_STATUSES or not isinstance(raw, dict) or "compacted" in raw:
        return False
    dropped = sorted(k for k in raw if k not in CLOSED_RAW_KEYS and k not in ("description", "description_chars"))
    text = raw.get("description")
    long_text = isinstance(text, str) and len(text.removesuffix(" […]")) > CLOSED_DESCRIPTION_MAX
    if not dropped and not long_text:
        return False
    for k in dropped:
        del raw[k]
    if long_text:
        raw.setdefault("description_chars", len(text))
        raw["description"] = text[:CLOSED_DESCRIPTION_MAX].rstrip() + " […]"
    raw["compacted"] = dropped
    return True


def append_candidate_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rows to a candidate file without rewriting the lines already there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            trim_candidate_description(row)
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")


def _write_rows_atomically(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            trim_candidate_description(row)
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def write_candidate_file(cf: CandidateFile) -> None:
    """Rewrite a candidate file atomically (temp file then replace), one compact object per line.

    Rejected and duplicate rows go to ``closed/<source>.jsonl``, or to its 16 shards
    ``closed/<source>/<0-f>.jsonl`` once there are more than :data:`CLOSED_SHARD_MIN_ROWS`, and the rest
    to ``<source>.jsonl``. The open file (and a sharded source's flat closed file) is kept even when
    empty, because round 1 branches still append to it and a deleted file would turn their next merge
    into a modify/delete conflict; an unused closed file or shard is removed otherwise.
    """
    closed = [r for r in cf.rows if r.get("status") in CLOSED_CANDIDATE_STATUSES]
    open_rows = [r for r in cf.rows if r.get("status") not in CLOSED_CANDIDATE_STATUSES]
    _write_rows_atomically(cf.path, open_rows)
    closed_path = closed_candidate_path(cf.path)
    shard_dir = closed_shard_dir(cf.path)
    shards: dict[str, list[dict[str, Any]]] = {}
    if len(closed) > CLOSED_SHARD_MIN_ROWS:
        for row in closed:
            shards.setdefault(closed_shard_key(row), []).append(row)
        _write_rows_atomically(closed_path, [])
    elif closed:
        _write_rows_atomically(closed_path, closed)
    elif closed_path.is_file():
        closed_path.unlink()
    for key, rows in sorted(shards.items()):
        _write_rows_atomically(shard_dir / f"{key}.jsonl", rows)
    for old in shard_dir.glob("*.jsonl"):
        if old.stem not in shards:
            old.unlink()


def candidate_cells(row: dict[str, Any]) -> list[str]:
    value = row.get("cell") or row.get("cells") or []
    return [value] if isinstance(value, str) else [c for c in value if isinstance(c, str)]


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #


def humanise(value: str) -> str:
    """``network_flow`` -> ``network flow``; used to search for vocabulary terms in prose."""
    return value.replace("_", " ")


def uniq(items: Iterable[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
