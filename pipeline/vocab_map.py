#!/usr/bin/env python3
"""Map the free-text values behind the dashboard filters onto short controlled vocabularies.

Several record fields that the dashboard offers as filters are free text (licence, formats, update
frequency, time step, spatial resolution, programming language, interfaces, deployment) or carry
near-synonyms (maturity ``active`` and ``maintained``, ``unknown``). Over rounds of collection they grew
to thousands of spellings of the same few ideas. This module defines how every raw value maps onto the
vocabularies in ``vocab/vocabulary.yaml``:

1. A value stored in the record's *target* field (for example ``licence_type``) wins: that is a
   decision made for that record.
2. Otherwise the raw value is looked up in ``vocab/<vocabulary>.csv`` (columns ``raw_value``,
   ``records``, ``mapped``, ``rule``). ``mapped`` holds vocabulary values joined by ``|``; an empty
   ``mapped`` means "no value" (used by ``licence_name`` for non-standard licences); ``?`` means the
   value is waiting for a decision. Rows whose ``rule`` is ``manual`` are hand decisions and are kept
   by ``refresh``.
3. Otherwise the rules below classify the raw value (the same rules that wrote the CSV).
4. A value that is already a vocabulary value maps to itself, so records rewritten by ``rewrite`` pass
   through unchanged.

A raw value nothing can place becomes ``other`` at build time (the dashboard never loses a record from a
filter) and is reported by ``check`` and by ``validate.py`` as a warning.

Commands::

    python3 vocab_map.py refresh [--extra FILE.json ...]   # rewrite the CSVs from the records (keeps manual rows)
    python3 vocab_map.py check                              # values outside the vocabulary or the mapping
    python3 vocab_map.py rewrite [--apply]                  # write the normalised values into the record files
    python3 vocab_map.py report --out FILE.md               # values before and after, per filter

``rewrite`` is meant for the integrator once the open branches have merged; without ``--apply`` it only
prints what it would change.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime
import json
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

HERE = Path(__file__).resolve().parent
VOCAB_DIR = HERE / "vocab"
RECORD_TYPES = ("data", "model", "platform", "case_study")
UNMAPPED = "?"
#: Rule name for a clear value that no rule places; it goes to "other" and is listed in vocab/decisions.csv.
FALLBACK = "fallback_other"

# --------------------------------------------------------------------------- #
# Vocabulary and mapping tables
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=4)
def load_vocabulary(vocab_dir: Path = VOCAB_DIR) -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load((vocab_dir / "vocabulary.yaml").read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for name, body in raw.items():
        values = {}
        for k, v in (body.get("values") or {}).items():
            if not (isinstance(v, list) and len(v) == 2):
                raise ValueError(f"vocabulary.yaml: {name}.{k} must be [label, definition]; quote a label that holds a comma")
            values[str(k)] = {"label": str(v[0]), "definition": str(v[1])}
        out[name] = {**{k: v for k, v in body.items() if k != "values"}, "values": values}
    return out


@lru_cache(maxsize=4)
def load_tables(vocab_dir: Path = VOCAB_DIR) -> dict[str, dict[str, tuple[str, ...] | None]]:
    """``{vocabulary: {raw_value: values or None (waiting for a decision)}}`` from the CSV files."""
    tables: dict[str, dict[str, tuple[str, ...] | None]] = {}
    for name in load_vocabulary(vocab_dir):
        path = vocab_dir / f"{name}.csv"
        table: dict[str, tuple[str, ...] | None] = {}
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    mapped = row.get("mapped", "")
                    table[row["raw_value"]] = None if mapped == UNMAPPED else tuple(v for v in mapped.split("|") if v)
        tables[name] = table
    return tables


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

#: Phrases that mean "the source gives no value", the same for every field.
NOT_STATED = re.compile(
    r"^\s*$|^(n/?a|none stated|null|tbd|\?|-)\s*\.?$|not stated|not read\b|unknown|unclear|not (fully )?established|not specified|"
    r"not recorded|not given|not found|not available|not confirmed|not determined|not documented|not readable|"
    r"not verified|not reported|not known|not identified|not provided|not described|not published|no information|"
    r"none stated|not inspected|could not be (read|determined)|cannot be determined|undetermined|unspecified|not applicable|not named|"
    r"not clearly|not yet (specified|stated|known)|no (schedule|routine)|^see\b|^see (the )?(portal|repository|record|page)|"
    r"no (licen[cs]e|terms|statement)\b[^;]{0,30}(stated|named|found|given|shown|published|statement)|"
    r"^no licen[cs]e\b|licen[cs]e not\b|no licen[cs]e (was )?(stated|found)|no (open |reuse |explicit )licen[cs]e"
)
NOT_STATED_START = re.compile(
    r"^\s*(not stated|not read|unknown|unclear|not (fully )?established|not specified|not recorded|not given|not found|"
    r"none stated|no licen[cs]e|licen[cs]e not|not available|not confirmed|not determined|not readable|not verified)"
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace(" ", " ")).strip().lower()


def _find_all(text: str, table: list[tuple[str, str]]) -> list[str]:
    """Every value whose pattern matches, in table order; a matched span is blanked for later patterns."""
    found: list[str] = []
    for value, pattern in table:
        rx = re.compile(pattern)
        if rx.search(text):
            if value not in found:
                found.append(value)
            text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return found


def _first(text: str, table: list[tuple[str, str]]) -> str | None:
    for value, pattern in table:
        if re.search(pattern, text):
            return value
    return None


# Licences ----------------------------------------------------------------- #

LICENCE_NAMES: list[tuple[str, str]] = [
    ("CC-BY-NC-ND", r"\bcc[\s_-]*by[\s_-]*nc[\s_-]*nd\b|attribution[\s-]*non[\s-]*commercial[\s-]*no-?deriv"),
    ("CC-BY-NC-SA", r"\bcc[\s_-]*by[\s_-]*nc[\s_-]*sa\b|attribution[\s-]*non[\s-]*commercial[\s-]*share-?alike"),
    ("CC-BY-NC", r"\bcc[\s_-]*by[\s_-]*nc\b|attribution[\s-]*non[\s-]*commercial"),
    ("CC-BY-ND", r"\bcc[\s_-]*by[\s_-]*nd\b|attribution[\s-]*no-?deriv"),
    ("CC-BY-SA", r"\bcc[\s_-]*by[\s_-]*sa\b|attribution[\s-]*share-?alike"),
    ("CC0", r"\bcc[\s_-]*0\b|\bcc[\s_-]*zero\b|creative commons zero|\bcc0"),
    ("CC-BY", r"\bcc[\s_-]*by\b|creative commons attribution|creative commons atribui|creative commons \(?by\b|\bcc[\s_-]*-?by\b"),
    ("PDDL", r"\bpddl\b|public domain dedication and licen"),
    ("ODC-By", r"\bodc[\s_-]*by\b|open data commons attribution"),
    ("ODbL", r"\bodbl\b|open database licen[cs]e"),
    ("Unlicense", r"\bunlicen[sc]e\b"),
    ("OGL-Canada", r"ogl[\s_-]*(canada|bc|ontario|alberta)|open government licen[cs]e[\s,:(–-]*(v?[\d.]+[\s,:(–-]*)?(canada|british columbia|alberta|ontario|nova scotia|prince edward|new brunswick|yukon|newfoundland|manitoba|saskatchewan)"),
    ("OGL-UK", r"\bogl\b|ogl[\s_-]*uk|\buk open government|open government licen[cs]e(?! for| data)"),
    ("Etalab", r"licence ouverte|open licen[cs]e (v(ersion)? ?)?[12]\.0|etalab"),
    ("DL-DE", r"datenlizenz deutschland|\bdl-de\b|\bdl-(by|zero)-de\b|data licen[cs]e germany"),
    ("NLOD", r"\bnlod\b|norwegian licen[cs]e for open government"),
    ("CDLA", r"\bcdla\b"),
    ("AGPL", r"\bagpl|\bapgl|affero general"),
    ("LGPL", r"\blgpl|lesser general public|library general public"),
    ("GPL", r"\bgpl|gnu general public|\bgnu gpl|general public licen[cs]e"),
    ("MPL", r"\bmpl\b|mozilla public"),
    ("EPL", r"\bepl\b|eclipse public"),
    ("EUPL", r"\beupl|european union public licen"),
    ("CeCILL", r"cecill"),
    ("AFL", r"\bafl\b|academic free licen"),
    ("BSL", r"\bbsl-1|boost software licen"),
    ("Zlib", r"\bzlib\b"),
    ("ISC", r"\bisc\b(?! ?(group|press))"),
    ("Apache", r"\bapache"),
    ("BSD", r"\bbsd(?![a-z])|\b0bsd\b|bsd-style"),
    ("MIT", r"\bmit\b(?! (press|university|energy initiative|lincoln))(?![- ]based)|\bmit-0\b|\bexpat licen"),
    ("US-Gov-PD", r"(u\.\s?s\.|\bus\b|united states|federal)[^;]{0,30}(government|federal)[^;]{0,20}work|"
                  r"public[- ]domain[^;]{0,60}(u\.\s?s\.|\bus\b|united states|federal|usgs|noaa|nasa|\beia\b|\bepa\b|fema|nrel|census bureau|\bdoe\b|\bdot\b|faa|usda|usace)|"
                  r"(u\.\s?s\.|\bus\b|united states|federal|usgs|noaa|nasa|\beia\b|\bepa\b|fema|nrel|census bureau|usda|usace)[^;]{0,60}public[- ]domain|"
                  r"u\.s\. government works?|(u\.\s?s\.|\bus\b|united states)[^;]{0,12}(federal |government )+(information|data|public records|public information)"),
]

LICENCE_NAME_TYPE = {
    "CC0": "public_domain", "PDDL": "public_domain", "Unlicense": "public_domain", "US-Gov-PD": "public_domain",
    "CC-BY": "attribution", "ODC-By": "attribution", "OGL-UK": "attribution", "OGL-Canada": "attribution", "Etalab": "attribution",
    "DL-DE": "attribution", "NLOD": "attribution", "CDLA": "attribution",
    "CC-BY-SA": "share_alike", "ODbL": "share_alike",
    "CC-BY-NC": "non_commercial", "CC-BY-NC-SA": "non_commercial", "CC-BY-NC-ND": "non_commercial",
    "CC-BY-ND": "no_derivatives",
    "MIT": "permissive_code", "BSD": "permissive_code", "Apache": "permissive_code", "ISC": "permissive_code",
    "AFL": "permissive_code", "BSL": "permissive_code", "Zlib": "permissive_code",
    "GPL": "copyleft_code", "LGPL": "copyleft_code", "AGPL": "copyleft_code", "MPL": "copyleft_code", "EPL": "copyleft_code",
    "EUPL": "copyleft_code", "CeCILL": "copyleft_code",
}

LICENCE_KEYWORDS: list[tuple[str, str]] = [
    ("not_stated", r"^public\b(?![- ]domain)|website content|web page|government (publication|document)|public (document|report|record|testimony|municipal)|"
                   r"stated in the (code )?repository|no code release|not released|internal models|free to read|^open access"),
    ("permissive_code", r"\becl-|\bpsf-|\bncsa\b|python software foundation"),
    ("copyleft_code", r"nasa-1\.3|nasa open source"),
    ("varies", r"provider-specific|per (database|api)|set by each|\bvar(y|ies|ying)\b|\bvarious\b|\bmixed\b|multiple licen|per[- ](dataset|layer|item|product|collection|record|file|source|series)|"
               r"each (dataset|layer|item|product|collection|record|file|source|catalogue entry)|dataset[- ]specific|layer[- ]specific|"
               r"product[- ]specific|by dataset|own licen[cs]es|separate licen[cs]es|individual (dataset|licen)|depend(s|ing) on the (dataset|product|layer)|"
               r"set per dataset|differ(s|ent)? (by|per|between)"),
    ("public_domain", r"public[- ]domain|no copyright|free of copyright|copyright[- ]free|no restrictions? on (use|reuse|distribution)|no use restrictions?|"
                      r"without (any )?restrictions?|제한 없음|any use allowed(?! with)|no limitations|without charge or restriction"),
    ("non_commercial", r"(?<!commercial and )non[- ]?commercial|academic (and research |or research )?use only|research use only|"
                       r"free for (research|academic|non-commercial)|(academic|research|educational|teaching|scientific)[^;]{0,20}(use )?only|not for commercial|no commercial|personal use only|private use only"),
    ("attribution", r"open (government |gov )?(data |user |access )?licen[cs]e|free (re)?use with (attribution|citation|credit|source|acknowledg)|"
                    r"reuse with (attribution|citation|credit|acknowledg)|free (re)?use[^;]{0,40}(attribution|citation|credit|source)|"
                    r"open data licen|freely (re)?us(able|ed)|(free|open) (re)?use|reuse (is )?(permitted|allowed)|reuse policy|"
                    r"attribution (licen|required|only)|reusable with|source attribution|datos abiertos|libre uso|use allowed with attribution|other \(attribution\)|"
                    r"(reproduction|reuse|use)[^;]{0,40}(allowed|permitted)[^;]{0,40}(source|credit|citation|attribution|reference)|with (proper )?reference to"),
    ("proprietary", r"proprietary|commercial|all rights reserved|subscription|\bpaid\b|licen[cs]e fees?|\beula\b|end[- ]user licen|freeware|"
                    r"no reproduction|permission (is )?required|with permission|written permission|not open|closed|purchase|\bsold\b|\bfee\b|"
                    r"licensed users|retain(s)? copyright|no open reuse|restricted|copyright[^;]{0,40}(reserved|permission)|confidential|"
                    r"members only|non-free|not free|for sale|by agreement|pricing|licen[cs]ed (software|product)|access only|on request|request form|"
                    r"non-disclosure|prohibited|© original authors|publisher copyright"),
    ("provider_terms", r"terms|conditions|polic(y|ies)|agreement|legal notice|rules of the road|\brules\b|disclaimer|reuse notice|"
                       r"copyright|licencia de uso|licen[cs]e\b|licen[cs]e(d)? (to|for|under)|data use|acceptable use|fair use|citation (requested|required)|"
                       r"acknowledg|notice"),
]


def classify_licence(raw: str) -> tuple[list[str], list[str], str]:
    """(licence types, standard licence names, rule) for one licence text."""
    text = _norm(raw)
    text = re.sub(r"https?://creativecommons\.org/(?:licenses|publicdomain)/([a-z-]+)/?[\d.]*/?",
                  lambda m: " cc0 " if m.group(1) == "zero" else " cc " + m.group(1) + " ", text)
    if NOT_STATED_START.search(text) or text in ("", "none", "n/a", "na", "-"):
        return ["not_stated"], [], "not_stated"
    names = _find_all(text, LICENCE_NAMES)
    if names:
        if "DL-DE" in names and "zero" in text:
            types = ["public_domain"]
        else:
            types = []
            for n in names:
                t = LICENCE_NAME_TYPE[n]
                if t not in types:
                    types.append(t)
        # "CC BY 4.0 for data; paid for the depth layer" keeps both the named licence and the proprietary part
        if re.search(r"proprietary|commercial licen|paid\b|subscription", text) and not re.search(r"non[- ]?commercial", text):
            types.append("proprietary")
        return types, names, "named_licence"
    if NOT_STATED.search(text):
        return ["not_stated"], [], "not_stated"
    kind = _first(text, LICENCE_KEYWORDS)
    if kind:
        return [kind], [], "keyword"
    if re.search(r"\bopen\b(?! access)|\bfree\b(?! to read)", text):
        return ["attribution"], [], "open_or_free"
    return ["other"], [], FALLBACK


# Formats ------------------------------------------------------------------- #

FORMAT_TABLE: list[tuple[str, str]] = [
    ("not_stated", r"^(data |bulk |file |open data |web |tabular |downloadable |data on request|custom |microdata )*(downloads?|download files|data files?|files?|tables?|tabular( data| files)?|"
                   r"downloadable (files?|tables?|data( files?)?|dataset)|data (download|export|feed|tables)s?|microdata( files)?|statistics|catalogues|url|https?|s?ftp|various|mixed|"
                   r"extracts on request|custom extracts|data on request|satellite products|survey microdata)( \(.*\))?$"),
    ("transit_feed", r"gtfs|\bnetex\b|\bsiri\b|transxchange|\bgbfs\b|\bkv6|bison|\bgtfs-?rt\b"),
    ("geojson", r"geo-?json|topojson|\bgeojsonl?\b"),
    ("domain_model_file", r"graphml|\bidf\b|\bepw\b|\binp\b|epanet|matpower|pss/?e|\.raw\b|opendss|\.dss\b|rinex|pcap|\bfmu\b|"
                          r"\bsumo\b|matsim|\bpsse\b|\bcim\b|\bcgmes\b|\bcomtrade\b|\bgdx\b|\bmps\b|\blp file|\bbdf\b|\bsdf\b|swmm|hec-?ras|\bbufr\b|\bmseed\b|miniseed|\bsac\b(?! file)|\bgrib-?1\b|"
                          r"ros ?bag|can bus|\bubx\b|rtcm|iaga|ionex|antex|\bclk\b|seg-?y|\bdlis\b|\btle\b|\biq\b|\bendf|exfor|ensdf|\bfits\b|corrections|netflow|biargus|"
                          r"\bdbc\b|powerworld|pslf|comsol|antares|calliope|energyplan|eclipse input|\.?scn\b|envi-met|\bgexf\b|\bbrick\b|\bdtdl\b|\byang\b|\bbpmn\b|\buml\b|"
                          r"aixm|arinc|\bcmml\b|\bcfg\b|\bddy\b|cli climate|\bcoco\b|annotations?|labels|\bplc\b|flowtuple|cap'n proto|ionograms?|trajector(y|ies)|\bsp3\b|\bnmea\b|\bais\b"),
    ("gml", r"citygml|\bgml\b|inspire gml"),
    ("ogc_map_service", r"\bwms\b|\bwfs\b|\bwmts\b|\bwcs\b|\btms\b|ogc api|ogc web|arcgis[^,;]{0,12}(rest|feature|map|image|server|service|online|hub)|"
                        r"feature (service|layer|server)|map ?server|image ?server|esri rest|tile (service|server)|xyz tiles|map services?|geoservices?"),
    ("api", r"earth engine|\bstac\b|\bcsw\b|openapi|dcat|\bapis?\b|\brest(ful)?\b|graphql|socrata|\bckan\b|sparql|\bodata\b|mqtt|web ?services?|endpoint|websocket|opendap|thredds|erddap|\bsoap\b|\bgrpc\b|\bsos\b|sensorthings"),
    ("web_page", r"html?\b|web ?(page|site|map|app|application|table|portal|dashboard|database|viewer|interface|search|gis|tool|form|platform|catalogue|query)s?|"
                 r"online (database|map|tool|viewer|dashboard|table|portal|catalogue|query|platform|application|search)s?|dashboard|interactive|viewer|browser|"
                 r"\bportal\b|story ?map|^web$|^online$|website|explorer\b|query tool|\bweb \w+|databank|query system|knowledge base"),
    ("esri_geodatabase", r"geodatabase|filegdb|fgdbr?\b|esri multipatch|arcgis (layer|scene)|arcmap|\bgdb\b|\bfgdb\b|layer package|\blpkx?\b|\bmpkx?\b|map package|\blyrx?\b|\bsde\b"),
    ("geopackage", r"geopackage|\bgpkg\b"),
    ("shapefile", r"shape ?files?|\bshp\b"),
    ("kml", r"\bkml\b|\bkmz\b"),
    ("other_vector", r"\btab\b|mapinfo|\bmif\b|\bgpx\b|\bwkt\b|\bsosi\b|interlis|gis (layers?|files?|data|vector|databases?)|vector (gis|data|download)|\bgis\b|\bqgz\b|\bqml\b|\bpbf\b|osm xml|\.osm\b|\bosm\b|flatgeobuf|\bfgb\b|vector tiles?|\bmvt\b|mbtiles|pmtiles|\bdgn\b|\be00\b|coverage file"),
    ("netcdf_hdf", r"\bcdf\b|netcdf|\bnc4?\b|\bhdf|\bh5\b|\bhe5\b|grib|zarr"),
    ("parquet", r"parquet|\barrow\b|feather|\bdelta lake\b|\borc\b"),
    ("raster", r"\bdems?\b|\bdtms?\b|\bdsms?\b|aaigrid|arcgis grid|arc/info grid|\benvi\b(?!-)|\bbag\b|geotiff|\bgeotif\b|\bcog\b|\btiff?\b|ascii grid|\basc\b|\bimg\b|jpeg ?2000|\bjp2\b|\bdem\b|\bgrd\b|esri grid|\bbil\b|\bvrt\b|raster|\becw\b|\bmrsid\b|\bsid\b|\bhgt\b|\bdted\b|\bsafe\b"),
    ("analysis_package_file", r"numpy|\bnpy\b|\bnpz\b|pickle|\bpkl\b|pytorch|\barff\b|\bbiom\b|redatam|cspro|stata|\bdta\b|spss|\bsav\b|\bsas\b|sas7bdat|\brdata\b|\brda\b|\brds\b|\bmat\b|matlab (mat|data)|\bpx\b|pc-?axis|sdmx|\bdbf\b"),
    ("database", r"microsoft access|bigquery|sqlite|\bsql\b|postgres|postgis|\bmdb\b|\baccdb\b|access database|ms access|database dump|\bdump\b|mysql|\bduckdb\b|\bneo4j\b|\bmongodb\b|\bdatabase\b|\bdb\b|\bgraph database|triple ?store|\bturtle\b|\bttl\b|\brdf\b|json-?ld|\bowl\b|linked data|n-?triples"),
    ("cad_bim_3d", r"\bifc\b|\bdwg\b|\bdxf\b|revit|\brvt\b|\bobj\b|gltf|\bglb\b|3d tiles|cityjson|\blas\b|\blaz\b|point cloud|\bply\b|\bstl\b|\bcad\b|\bbim\b|\bfbx\b|\b3ds\b|\bskp\b|\bi3s\b|\bslpk\b|\busdz?\b|\bczml\b|\bcopc\b|\be57\b|\bstep\b|\b3d\b|sketchup|\bmesh\b"),
    ("csv", r"\bdsv\b|\bcsv|\btsv\b|delimited|comma[- ]separated|tab[- ]separated|semicolon"),
    ("spreadsheet", r"\bxlsx?\b|\bxlsm\b|\bxlsb\b|excel|\bods\b|spreadsheet|workbook"),
    ("json", r"\bjson|\bjsonl\b|ndjson"),
    ("xml", r"\bxml\b|\bxsd\b|\bkml\b|\batom\b|\brss\b|\bdatex\b|\bnetcdf-?ml\b"),
    ("plain_text", r"\btxt\b|plain text|\btext\b|\bascii\b|fixed[- ]width|\.dat\b|\bdat\b|\blog files?\b|\byaml\b|\byml\b|\btoml\b|\bini\b"),
    ("document", r"\bpdf|\bdocx?\b|\bword\b|markdown|\bmd\b|readme|reports?\b|documentation|slides|\bpptx?\b|\bepub\b|guidance|handbook|manual|"
                 r"guidelines?|publications?|articles?|papers?\b|documents?\b|bulletins?|factsheets?|briefs?\b|\brtf\b|\bodt\b|\blatex\b|\btex\b|\bbook\b|atlas"),
    ("image", r"\bpng\b|\bjpe?g\b|\bsvg\b|\bgif\b|\bimages?\b|\bmaps?\b|photos?|photographs?|figures?|\bbmp\b|\bwebp\b|\bcharts?\b|infographics?|\bvideos?\b|\bmp4\b|imagery|\bplots?\b|\bwav\b|\bavi\b|\bmov\b|\bflac\b|audio|\bmp3\b|\bglz\b"),
    ("source_code", r"python|\br\b(?! ?data)|\bjulia\b|matlab|jupyter|notebooks?|ipynb|\.py\b|\bscripts?\b|source code|\bcode\b|c\+\+|fortran|\bjava\b|"
                    r"modelica|netlogo|\bgams\b|\bampl\b|\bc#|javascript|\bgit\b|repository|\bpackages? \(|\bpip\b|\bconda\b|\bcran\b|\blibrary\b|^\.?py$|\.cs\b"),
    ("software_package", r"executables?|\bexe\b|installers?|\bmsi\b|\bdmg\b|docker|containers?|virtual machine|\bvm\b|\bova\b|binar(y|ies)|software|"
                         r"applications?|\bapps?\b|plug-?ins?|\bpackages?\b|\bjar\b|toolbox|add-?in|extension|\bdeb\b|\brpm\b|\bplugin\b|\bdll\b|\bapk\b"),
    ("archive", r"\bzip\b|\bzipped\b|\brar\b|\b7z\b|\b7-zip\b|\btar\b|tar\.gz|\bgz\b|\bgzip\b|\btgz\b|compressed|\bbz2\b|\bxz\b|\barchives?\b"),
]


def classify_formats(raw: str) -> tuple[list[str], str]:
    text = re.sub(r"\bapplication/", "", _norm(raw))
    if re.fullmatch(r"(n/?a|none|-|)", text) or NOT_STATED_START.search(text):
        return ["not_stated"], "not_stated"
    found = _find_all(text, FORMAT_TABLE)
    if "api" in found and "json" in found:
        found.remove("json")
    if "ogc_map_service" in found and "api" in found and re.search(r"arcgis", text) and not re.search(r"\bapi\b", text):
        found.remove("api")
    if "archive" in found and len(found) > 1:
        found.remove("archive")
    if len(found) > 1 and "not_stated" in found:
        found.remove("not_stated")
    if found:
        return found, "keyword"
    if NOT_STATED.search(text):
        return ["not_stated"], "not_stated"
    return ["other"], FALLBACK


# Update frequency and time step ------------------------------------------- #

FREQ_TABLE: list[tuple[str, str]] = [
    ("varies", r"\bvar(y|ies|ying|iable)\b|dataset[- ]specific|product[- ]specific|depends|depending|per (dataset|series|product|layer)|by (dataset|series|product|source)|\bmixed\b|differs"),
    ("not_stated", r"^(last updated|hub modified|item modified|metadata (record )?(published|modified)|the page was changed)|no schedule|no routine|^see\b"),
    ("real_time", r"real[- ]?time|online for most|constant for|continuous|\blive\b|stream|every (few )?(minute|second)|\bminut|\bseconds?\b|sub-?hourly|\b\d+ ?min\b|on the fly"),
    ("sub_daily", r"\bhour|twice (a |per )?day|several times (a|per) day|\b\d+ ?h\b|\b\d+h\b|\bintraday|times daily|\b(3|6|12)[- ]hourly"),
    ("daily", r"\bdail|diari|every day|working days?|business days?|each day|per day|\bday\b|nightly|quotidien|täglich|diaria"),
    ("weekly", r"week|fortnight|biweekly|semanal|hebdo|twice a month|bi-?monthly|dekad"),
    ("monthly", r"month|mensal|mensuel|monatlich|mensual|28 days|airac"),
    ("several_per_year", r"quarter|half[- ]?year|semi-?annual|biannual|twice (a|per) year|several times (a|per) year|seasonal|trimest|"
                         r"\b(2|3|4|6|two|three|four|six) times (a|per) year|every (three|six|3|6) months|triannual|every (90|120|180) days"),
    ("multi_year", r"every (\w+ )?(one|two|three|\d+) to (two|three|five|seven|\d+) years|revised about every|directive cycles|inventory cycle|"
                   r"every (two|three|four|five|six|seven|eight|nine|ten|2|3|4|5|6|7|8|9|10|few|several|\d+)[- ](or \w+ )?years|biennial|decennial|decadal|"
                   r"quinquennial|census|\b\d+[- ]year(ly)? (cycle|interval|round)|triennial|\b(five|ten|5|10)[- ]year(ly)?\b|intercensal|every (decade|\d+-\d+ years)"),
    ("annual", r"growing season|annual|yearly|every year|each year|per year|once a year|\banual\b|jährlich|\byear\b|\bfy\b|financial year|fiscal year|vintage"),
    ("not_updated", r"^none\b|^no\b|not updated|no (longer|further|updates?|regular)|one[- ]?off|one[- ]?time|static|single (release|edition|publication|version|snapshot)|"
                    r"discontinued|archived|historical|\bfinal\b|\bnever\b|ceased|frozen|completed|not maintained|^once\b|^since \d{4}|"
                    r"published (in )?\d{4}|\bended\b|\bclosed\b|legacy|superseded|retired|dormant|inactive|halted|stopped|not planned|stable standard"),
    ("irregular", r"^as\b|\bas (\w+ ){0,4}(are|is|arrive|change|report|submit|publish|approve|adopt)|^per\b|with each|each new|on acquisition|added|additions|progressively|"
                  r"submissions?|continues|re-executable|kept up|\bv\d|\brevised\b|deliverables|national studies|domain by domain|irregular|as needed|ad[- ]?hoc|periodic|versions?|releases?|\bregular|occasional|when|frequent|ongoing|updated|rolling|new (data|editions?|issues?)|"
                  r"sporadic|as available|\bevents?\b|editions?|continual|actively|maintained|active|\bupdates\b|revisions?|on (demand|request)|as (they|new)|"
                  r"campaign|per (project|study|survey)|\bwaves?\b|rounds?|surveys?"),
]

TIMESTEP_TABLE: list[tuple[str, str]] = [
    ("varies", r"dataset[- ]specific|instrument[- ]specific|endpoint[- ]dependent|mission dependent|\bvar(y|ies|ying|iable)\b|depends|depending|per (dataset|series|product|layer|variable)|by (dataset|series|product|variable)|\bmixed\b|multiple (time )?resolutions?|\b\d+ ?(-|–|to) ?\d+ days\b"),
    ("sub_hourly", r"\bseconds?\b|\bminut|\bmins?\b|sub-?hourly|real[- ]?time|\b\d+ ?s\b|millisecond|\b\d+-min|continuous|\bhz\b|\bms\b|\bstream|high-frequency|\bpmu\b|synchrophasor|\bscada\b|instantaneous|\bk?hz\b|\bk?sps\b|packet"),
    ("hourly", r"\bhour|\b\d+ ?h\b|\b\d+h\b|\bintraday|times daily|twice daily"),
    ("daily", r"\bdail|\bday\b|\bdays\b|diari|per day"),
    ("weekly", r"week|fortnight"),
    ("monthly", r"month"),
    ("sub_annual", r"quarter|season|half[- ]?year|semi-?annual|biannual|trimest|twice (a|per) year"),
    ("multi_year", r"epochs|assessment cycle|every (two|three|four|five|ten|2|3|4|5|10|few|several|\d+)[- ]years|decennial|decadal|quinquennial|biennial|census (every|years|rounds|waves)|"
                   r"censuses|\b(five|ten|5|10)[- ]year(ly)?\b|multi-?year|\bdecades?\b|intercensal|triennial|\bwaves\b|survey rounds|rounds?\b"),
    ("snapshot", r"^one (\w+ ){0,4}(per|row)|cross-?section|period average|cumulative|one survey wave|single wave|one census round|single census"),
    ("annual", r"annual|yearly|\bfy\b|financial year|fiscal year|per year"),
    ("event", r"^per\b|^individual|individual (measurements|records)|irregular|\bcall\b|\bcalls\b|\brequests?\b|\bmeasurements?\b|\bsurveys?\b|\bstud(y|ies)\b|\bevents?\b|incidents?|per (test|trip|record|case|outage|failure|earthquake|storm|flood|disaster|accident|crash|observation|experiment|run|scenario)|occurrences?|\btrips?\b|"
              r"\bcases?\b|\bruns?\b|scenario|experiments?|\btests?\b|campaigns?|episodes?|\bjourneys?\b|transactions?|\bflights?\b|\bvoyages?\b|\bshipments?\b"),
    ("snapshot", r"snapshot|static|\bsingle\b|one[- ]?off|cross-?sectional|^none\b|not applicable|^n/?a\b|no time|point in time|one[- ]?time|\bonce\b|as of|vintage|"
                 r"\bcensus\b|current|latest|no temporal|not temporal|timeless|\beditions?\b|release|\bversion|\bstudy period\b|\bone (year|date|period)\b|\bat \d{4}"),
    ("annual", r"\byears?\b|\b(19|20)\d{2}\b"),
]


def classify_scalar(raw: str, table: list[tuple[str, str]]) -> tuple[list[str], str]:
    text = _norm(raw)
    if not text or NOT_STATED_START.search(text) or re.fullmatch(r"(n/?a|-|none stated|null)\.?", text):
        return ["not_stated"], "not_stated"
    value = _first(text, table)
    if value:
        return [value], "keyword"
    if NOT_STATED.search(text):
        return ["not_stated"], "not_stated"
    return ["other"], FALLBACK


# Spatial resolution --------------------------------------------------------- #

UNIT_METRES = [
    (r"arc[- ]?sec(ond)?s?|″|''|\"", 30.87),
    (r"arc[- ]?min(ute)?s?|′", 1852.0),
    (r"km|kilomet(er|re)s?", 1000.0),
    (r"cm|centimet(er|re)s?", 0.01),
    (r"mm|millimet(er|re)s?", 0.001),
    (r"°|deg(ree)?s?", 111_000.0),
    (r"m\b|met(er|re)s?|-?m\b", 1.0),
]
NUMBER_UNIT = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(?:x\s*\d+(?:[.,]\d+)?\s*)?(arc[- ]?sec(?:ond)?s?|arc[- ]?min(?:ute)?s?|″|′|''|\"|km\b|kilomet(?:er|re)s?|cm\b|centimet(?:er|re)s?|mm\b|millimet(?:er|re)s?|°|deg(?:ree)?s?\b|m\b|met(?:er|re)s?\b)")
SCALE = re.compile(r"1\s*:\s*(\d[\d,. ]*\d)")

SPATIAL_KEYWORDS: list[tuple[str, str]] = [
    ("varies", r"\bvar(y|ies|ying|iable)\b|multiple (spatial )?resolutions|several resolutions|\bmixed\b|depends|depending|from [^;]{1,30} to "),
    ("non_spatial", r"not spatial|non-?spatial|not applicable|^n/?a$|no spatial|aspatial|not geographic|not geo-?referenced|no geographic|none \(non|^none$|no location"),
    ("asset", r"\bip\b|ipv[46]|\bhosts?\b|routers?|\bas\b|\bpop\b|reservoirs?|treatment works|moorings|instruments?|\bfactory|testbed|laborator|orbit|spacecraft|per exchange|building|facilit|\bsites?\b|points?\b|station|plants?\b|assets?\b|segments?|coordinates|individual|\bmines?\b|\bports?\b|airports?|parcels?|address|"
              r"\blines?\b|\blinks?\b|\bnodes?\b|substation|turbines?|\bwells?\b|bridges?|\bdams?\b|towers?|transmitters?|establishments?|households?|\bunits?\b|"
              r"machines?|\bfields?\b|deposits?|\bbanks?\b|\bevents?\b|vessels?|vehicles?|meters?\b|pipes?|streets?|features?|objects?|\bhouses?\b|premises|"
              r"locations?|lat(itude)?\b|\bgps\b|per (asset|feature|object|record|project|incident)|project level|footprints?|\broads?\b|\brail\b|\bcells? tower|"
              r"\bantennas?\b|\bgenerators?\b|\bcompan(y|ies)\b|\bfirms?\b|\bhospitals?\b|\bschools?\b|\bplots?\b|\bincidents?\b|\bpolygons?\b|\bvector\b|\bpoles?\b|"
              r"\bsensors?\b|\bgauges?\b|\bbuses\b|\bbus\b|\bfeeders?\b|\bcustomers?\b|\bsegments?\b|\blanes?\b|\bstops?\b|\broutes?\b|\btrips?\b|\bflights?\b|\bterminals?\b|\bexact\b"),
    ("local_units", r"watersheds?|\bhuc\d*|dissemination areas?|communities|p-codes|citywide|demand areas|municipal|count(y|ies)|district|tract|\bblocks?\b|postcode|post code|zip code|postal|zones?\b|\bwards?\b|lsoa|msoa|\boas?\b|output areas?|commun(e|es)|"
                    r"parish|\bcit(y|ies)\b|\blocal\b|nuts ?3|\blau\b|census areas?|sub-?district|neighbo|council|borough|catchments?|basins?|grid cells?|\bgrid\b|\btowns?\b|"
                    r"villages?|urban areas?|metropolitan|\bmsa\b|\bcbsa\b|\btaz\b|traffic zones?|\bsa[1-4]\b|\bdzs?\b|\bdivisions?\b|\bmunicipios?\b|\bgemeinde|\bkreis|"
                    r"\bprefectural? cities\b|\bsub-?national\b|\badmin(istrative)?[- ]?(level )?[2-5]\b|\badm ?[2-5]\b|small areas?|\bhex(agon)?s?\b|\bh3\b|\bsquares?\b|\bpixels?\b|\blocalit"),
    ("regional_units", r"\bstates?\b|provinc|region|nuts ?[12]\b|territor|prefecture|länder|\bland\b|oblast|department|\badmin(istrative)?[- ]?(level )?1\b|\badm ?1\b|\bcantons?\b|\bemirates?\b|governorate|\bcounties and states\b|sub-?national"),
    ("national", r"\beu level|national|countr(y|ies)|\bnations?\b|operators?\b|borders?\b|\bsystems?\b|\bglobal\b|continental|\beurope\b|\bworld\b|bidding zones?|markets?\b|economy|"
                 r"\bnuts ?0\b|\badm ?0\b|\biso\b|\bstate-?level\b|whole|entire|aggregate|\bplatforms?\b|\bnetworks?\b|\butilit(y|ies)\b|\bregions of the world\b"),
]


def metres_to_class(m: float) -> str:
    if m < 10:
        return "under_10m"
    if m < 100:
        return "10m_to_100m"
    if m < 1000:
        return "100m_to_1km"
    if m < 10_000:
        return "1km_to_10km"
    return "over_10km"


def classify_spatial(raw: str) -> tuple[list[str], str]:
    text = _norm(raw)
    if not text or NOT_STATED_START.search(text):
        return ["not_stated"], "not_stated"
    match = NUMBER_UNIT.search(text)
    if match:
        number = float(match.group(1).replace(",", "."))
        unit = match.group(2)
        for pattern, factor in UNIT_METRES:
            if re.fullmatch(pattern, unit):
                return [metres_to_class(number * factor)], "number"
    scale = SCALE.search(text)
    if scale:
        denominator = float(re.sub(r"[,. ]", "", scale.group(1)))
        return [metres_to_class(denominator / 2000)], "map_scale"
    if NOT_STATED.search(text):
        return ["not_stated"], "not_stated"
    value = _first(text, SPATIAL_KEYWORDS)
    if value:
        return [value], "keyword"
    if re.split(r"[;(]", text)[0].strip() in country_names():
        return ["national"], "country_name"
    return ["other"], FALLBACK


@lru_cache(maxsize=1)
def country_names() -> frozenset[str]:
    """Lower-case country names, for resolutions given only as a country ("Germany")."""
    names = {"england", "scotland", "wales", "northern ireland", "united states", "usa", "uk", "eu", "european union"}
    try:
        import pycountry
    except ImportError:  # pragma: no cover
        return frozenset(names)
    for c in pycountry.countries:
        for attr in ("name", "common_name", "official_name"):
            if getattr(c, attr, None):
                names.add(getattr(c, attr).lower())
    return frozenset(names)


# Programming language, interfaces, deployment ------------------------------ #

LANGUAGE_TABLE: list[tuple[str, str]] = [
    ("python", r"python|cython|jupyter|pyomo|ipynb|\.py\b|\bpypi\b|\bpip\b|\bconda\b"),
    ("r", r"(?<![\w.#+-])r(?![\w#+-])|\brstats\b|\bshiny\b|\bcran\b"),
    ("julia", r"\bjulia\b|\bjump\b"),
    ("matlab", r"matlab|simulink|octave"),
    ("c_cpp", r"c\+\+|(?<![\w#+/-])c(?![\w#+-])|\bcuda\b|opencl|\bcpp\b|\bopenmp\b|\bmpi\b"),
    ("java", r"\bjava\b(?!script)|\bscala\b|\bkotlin\b|\bjvm\b|\bgroovy\b|\bjava-based\b"),
    ("javascript", r"javascript|typescript|node\.?js|\bjs\b|\breact\b|\bangular\b|\bvue\b|\bd3\b"),
    ("fortran", r"fortran"),
    ("dotnet", r"c#|\.net\b|visual basic|vb\.?net|\bf#"),
    ("rust_go", r"\brust\b|\bgo\b|golang"),
    ("modelica", r"modelica"),
    ("optimisation_language", r"\bgams\b|\bampl\b|\bgmpl\b|\bmathprog\b|\bopl\b|\bmosel\b|\blingo\b|\baimms\b|\bxpress\b"),
    ("agent_based_language", r"netlogo|\bgaml\b|\bgama\b|repast|anylogic|\bmason\b"),
    ("spreadsheet", r"excel|\bvba\b|spreadsheet"),
    ("other", r"\bsql\b|\bshell\b|\bbash\b|\byaml\b|snakemake|\bidl\b|\bperl\b|\bphp\b|\bruby\b|\blua\b|haskell|\blisp\b|prolog|delphi|pascal|\bada\b|cobol|"
              r"\bstata\b|\bsas\b|\bgauss\b|vensim|stella|powersim|\bidf\b|html|\bcss\b|\bxml\b|\bswift\b|objective-c|\bperl\b|\bdart\b|\bsolidity\b|\bmaple\b|"
              r"mathematica|wolfram|\bgml\b|\bdsl\b|\bocaml\b|\berlang\b|\belixir\b|\bclojure\b|\bscheme\b|\bassembly\b|\bverilog\b|\bvhdl\b|\bplc\b|\bladder\b|"
              r"\bomnet\b|\bned\b|\bns-?3\b|\bsystem dynamics\b|\bgrasshopper\b|\bdynamo\b|\blabview\b|\bgo lang\b|\bmakefile\b|\bcmake\b|\bdocker\b"),
    ("not_stated", r"application|executable|software|windows|desktop|\bweb\b|\bgui\b|compiled|binary|proprietary|closed|\bn/?a\b|not applicable|guidelines?|pdf|method|tool\b"),
]

INTERFACE_TABLE: list[tuple[str, str]] = [
    ("cosimulation", r"\bfmi\b|\bfmus?\b|helics|\bhla\b|mosaik|co-?simulation|functional mock-?up|\bptolemy\b|\bhardware[- ]in[- ]the[- ]loop\b|\bhil\b|\bopal-?rt\b|\bdcp\b|\bcosim"),
    ("web_api", r"\b(rest(ful)?|http|web|json|remote|graphql|cloud) ?apis?\b|fastapi|openeo|\bmcp\b|\bcsw\b|3gpp|corba|\brest(ful)?\b|\bhttps?\b|graphql|\bmqtt\b|websockets?|web ?api|web ?services?|\bgrpc\b|zeromq|\bzmq\b|\btcp\b|\budp\b|opc[- ]?ua|modbus|\bdnp3\b|"
                r"iec[- ]?61850|\bsoap\b|\bodata\b|\bogc\b|\bwms\b|\bwfs\b|\bamqp\b|\bkafka\b|\bsocket\b|\bmodbus\b|\bbacnet\b|\bopenadr\b|\bocpp\b|\bapi endpoint|\bremote api\b|\bjson-?rpc\b|\bxml-?rpc\b"),
    ("web_app", r"web[- ]?(ui|gui|interface|application|app|browser|client|front[- ]?end|portal|dashboard|platform|tool|viewer|map|service)s?|\bbrowser\b|\bonline\b|"
                r"dashboard|^web$|\bwebsite\b|\bweb-based\b|\bjupyterhub\b|\bstreamlit\b|\bdash app\b|\bshiny\b|\bportal\b|\bweb\b"),
    ("desktop_gui", r"mobile|android|\bios\b|\bapps?\b|3d (viewer|visuali[sz]ation|modelling)|\bgis\b|arcgis|arcmap|hec-?ras|blender|cityengine|\bgui\b|graphical|desktop|windows (application|program|software)|user interface|\bui\b|visual (editor|interface)|qgis|arcgis (pro|desktop)|"
                    r"\bexcel\b|add-?in|\bplugin for\b|drag[- ]and[- ]drop|\bide\b|point[- ]and[- ]click|\beditor\b|\bunity\b|\bunreal\b|\bvr\b|\bmenu"),
    ("command_line", r"command[- ]?line|\bcli\b|\bterminal\b|\bconsole\b|\bshell\b|\bbatch\b|\bexecutable\b|\bbinary\b|\bheadless\b|\bmakefile\b|\bsnakemake\b|\bworkflow manager\b"),
    ("code_library", r"python|(?<![\w.#+-])r(?![\w#+-])|\bjulia\b|\bjava\b|c\+\+|matlab|\bapis?\b|librar(y|ies)|packages?|modules?|\bsdk\b|notebooks?|jupyter|scripts?|"
                     r"fortran|\brust\b|javascript|modelica|\bc#|netlogo|\bgams\b|toolbox|bindings?|programmatic|plug-?ins?|\bpyomo\b|\bpandas\b|\bnumpy\b|\bcode\b|"
                     r"\bfunctions?\b|\bclasses\b|\bscripting\b|\boctave\b|\bsimulink\b|\bgaml\b|\bdll\b|\bopenmodelica\b|\bcomponents?\b|\bmethods?\b|\bpyth\b|(?<![\w#+/-])c(?![\w#+-])|"
                     r"omnet|\binet\b|traci|gymnasium|pytorch|tensorflow|xarray|\bros\b|\.net\b|node\.?js|\bphp\b|\bidl\b|maven|conda|_api\b|\bbmi\b|brightway|spark|airflow|ansible|open data cube|cape-open|cobia"),
    ("file_exchange", r"\bcsv\b|\bjson\b|\byaml\b|\bxml\b|config|input files?|\bfiles?\b|spreadsheets?|geojson|shapefiles?|\btext\b|\binp\b|\bidf\b|\btoml\b|\bini\b|"
                      r"netcdf|\bhdf5?\b|\bdatabase\b|\bsql\b|postgres|sqlite|\bpng\b|\bcgmes\b|\bxlsx?\b|\bparquet\b|\bgeotiff\b|\bgtfs\b|\bosm\b|\bcim\b|\bmatpower\b|\bformats?\b|\bimport\b|\bexport\b|templates?"),
    ("other", r"docker|containers?|kubernetes|cloud|\bhpc\b|\bmpi\b|\bgpu\b|\bvirtual machine\b|\bplatform\b|\bengine\b|\bmodel\b|\bsimulator\b|\bservice\b"),
]

DEPLOYMENT_TABLE: list[tuple[str, str]] = [
    ("mobile_embedded", r"research vehicles|field counters|plant interface|android|\bios\b|mobile|phones?|tablets?|\bedge\b|embedded|\biot\b|raspberry|arduino|headsets?|\bquest\b|\bvr\b|\bar\b|microcontroller|\bplc\b|\bfpga\b|on-?board|in-?vehicle|drones?"),
    ("own_server", r"on[_ -]?prem|ubuntu|bare metal|openshift|openstack|backend|postgres|\bservers?\b|self-?hosted|on-?prem(ise|ises)?|docker|containers?|kubernetes|\bhpc\b|clusters?|supercomput|distributed|virtual machines?|\bvm\b|grid computing|"
                   r"\bprivate\b[^;]{0,20}network|node\.js|\bjvm\b|institutional|data ?cent(er|re)|\bnetwork\b|workstation cluster|\bslurm\b|\bmpi\b|\bparallel\b|testbed|laborator"),
    ("hosted_service", r"cloud|\bweb\b|browser|\bhosted\b|\bsaas\b|\bonline\b|\baws\b|amazon|azure|google (earth engine|cloud)|\bgee\b|remote|\bservices?\b|internet|\bportal\b|"
                       r"\bsaas\b|\bpaas\b|hosted service|\bwebsite\b|\bapi\b|\bjupyterhub\b|colab|\bbinder\b"),
    ("desktop", r"desktop|\blocal\b|locally|windows|\bmac(os)?\b|\blinux\b|laptop|workstation|\bpcs?\b|personal computer|python environment|installed|offline|standalone|"
                r"stand-alone|downloaded|librar(y|ies)|packages?|\br environment\b|matlab|\bexcel\b|\bunix\b|single machine|\bcomputer\b|\bgui\b|executable|"
                r"\binstall(s|ed)?\b|\bpip\b|\bconda\b|\bcran\b|\bnpm\b|install\.packages|"
                r"on (a|your|the user's) (own )?(machine|computer)|\bqgis\b|\barcgis\b|\bjupyter\b|\bnotebook\b|runtime|\bpython\b|environment|github|numpy|pandas|"
                r"compiler|\bgpu\b|\bcuda\b|openfast|modelica|powerfactory|fmus?\b"),
    ("not_stated", r"not applicable|\bn/?a\b"),
]

MATURITY_MAP = {"active": "active", "maintained": "active", "stale": "stale", "archived": "archived", "unknown": "not_stated"}

# Decided 2026-09-29 (user, delegated): a dated paper, report or data deposit with no upkeep is "stale" when its last
# release or update is more than two years old, otherwise "active". Applied only where the record states no maturity and
# has a last_updated date; a partial date counts as its last day, so the doubt goes to "active". The date below is the
# fixed reference for "two years": move it when the records are rewritten.
MATURITY_AS_OF = datetime.date(2026, 9, 29)


def maturity_from_date(last_updated: Any) -> str | None:
    """``active`` or ``stale`` from a record's ``last_updated`` (year, year-month or ISO date), else None."""
    m = re.match(r"^\s*(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(last_updated or ""))
    if not m:
        return None
    year, month, day = int(m.group(1)), m.group(2), m.group(3)
    try:
        if day:
            when = datetime.date(year, int(month), int(day))
        else:
            last_month = int(month) if month else 12
            when = (datetime.date(year + (last_month == 12), last_month % 12 + 1, 1) - datetime.timedelta(days=1))
    except ValueError:
        return None
    limit = MATURITY_AS_OF.replace(year=MATURITY_AS_OF.year - 2)
    return "stale" if when < limit else "active"


def classify_multi(raw: str, table: list[tuple[str, str]], fallback_other: bool = True) -> tuple[list[str], str]:
    text = _norm(raw)
    if not text or NOT_STATED_START.search(text) or re.fullmatch(r"(n/?a|none|-|null)\.?", text):
        return ["not_stated"], "not_stated"
    found = _find_all(text, table)
    if len(found) > 1 and "not_stated" in found:
        found.remove("not_stated")
    if len(found) > 1 and "other" in found:
        found.remove("other")
    if found:
        return found, "keyword"
    if NOT_STATED.search(text):
        return ["not_stated"], "not_stated"
    return ["other"], FALLBACK


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #

def classify(name: str, raw: str) -> tuple[list[str], str]:
    """Rule-based values for one raw value of vocabulary ``name``, plus the rule that fired."""
    raw = str(raw)
    if name == "licence":
        types, _, rule = classify_licence(raw)
        return types, rule
    if name == "licence_name":
        _, names, rule = classify_licence(raw)
        return names, rule if names else "no_standard_licence"
    if name == "formats":
        return classify_formats(raw)
    if name == "update_frequency":
        return classify_scalar(raw, FREQ_TABLE)
    if name == "temporal_resolution":
        return classify_scalar(raw, TIMESTEP_TABLE)
    if name == "spatial_resolution":
        return classify_spatial(raw)
    if name == "language":
        return classify_multi(raw, LANGUAGE_TABLE)
    if name == "interfaces":
        return classify_multi(raw, INTERFACE_TABLE)
    if name == "deployment":
        return classify_multi(raw, DEPLOYMENT_TABLE)
    if name == "maturity":
        mapped = MATURITY_MAP.get(_norm(raw))
        return ([mapped], "maturity_map") if mapped else ([UNMAPPED], "unmapped")
    raise KeyError(name)


def raw_values(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field)
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(v) for v in items if isinstance(v, (str, int, float)) and not isinstance(v, bool)]


def lookup(name: str, raw: str, vocab_dir: Path = VOCAB_DIR) -> tuple[list[str], str]:
    """Values for one raw value: vocabulary value itself, else the CSV, else the rules. ``?`` when none."""
    vocabulary = load_vocabulary(vocab_dir)[name]
    if raw in vocabulary["values"]:
        return [raw], "vocabulary"
    table = load_tables(vocab_dir).get(name, {})
    if raw in table:
        mapped = table[raw]
        return ([UNMAPPED], "csv") if mapped is None else (list(mapped), "csv")
    return classify(name, raw)


def normalised(record: dict[str, Any], vocab_dir: Path = VOCAB_DIR) -> dict[str, list[str]]:
    """``{target field: vocabulary values}`` for every filter vocabulary, for one record.

    A value already stored in the target field (other than the raw field itself) wins. Unplaced raw values
    become ``other`` where the vocabulary has it; ``licence_name`` simply has no value for them.
    """
    out: dict[str, list[str]] = {}
    for name, spec in load_vocabulary(vocab_dir).items():
        source, target = spec["record_field"], spec["target"]
        values: list[str] = []
        stored = raw_values(record, target) if target != source else []
        if stored:
            values = [v for v in stored]
        else:
            for raw in raw_values(record, source):
                mapped, _ = lookup(name, raw, vocab_dir)
                for v in mapped:
                    if v == UNMAPPED:
                        v = "other" if "other" in spec["values"] else ""
                    if v and v not in values:
                        values.append(v)
        if len(values) > 1 and "not_stated" in values:
            values.remove("not_stated")
        if name == "maturity" and values == ["not_stated"]:
            values = [maturity_from_date(record.get("last_updated")) or "not_stated"]
        if source in record or stored:
            out[target] = values
    return out


def apply_to_record(record: dict[str, Any], vocab_dir: Path = VOCAB_DIR) -> dict[str, Any]:
    """A copy of ``record`` whose filter fields hold vocabulary values (the build's view; files untouched).

    Multi-valued vocabularies give lists; single-valued ones give a string (the first value).
    """
    out = copy.copy(record)
    vocab = load_vocabulary(vocab_dir)
    targets = {spec["target"]: spec for spec in vocab.values()}
    for target, values in normalised(record, vocab_dir).items():
        spec = targets[target]
        if spec.get("multi"):
            out[target] = values
        elif values:
            out[target] = values[0]
        else:
            out.pop(target, None)
    return out


# --------------------------------------------------------------------------- #
# Records on disk
# --------------------------------------------------------------------------- #

def iter_record_files(project: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    for rtype in RECORD_TYPES:
        for path in sorted((project / "catalog" / rtype).glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("type", rtype)
                yield path, data


def load_record_versions(project: Path, extra: list[Path]) -> list[dict[str, Any]]:
    """Records on disk plus every record in the extra JSON lists, keeping each version (the same id can differ by branch)."""
    out = [data for _, data in iter_record_files(project)]
    for path in extra:
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


def load_all_records(project: Path, extra: list[Path]) -> list[dict[str, Any]]:
    """Records on disk plus extra JSON lists (for example records from open branches), unique by id."""
    by_id: dict[str, dict[str, Any]] = {}
    for _, data in iter_record_files(project):
        by_id[str(data.get("id"))] = data
    for path in extra:
        for data in json.loads(path.read_text(encoding="utf-8")):
            by_id[str(data.get("id"))] = data
    return list(by_id.values())


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

CSV_COLUMNS = ["raw_value", "records", "mapped", "rule"]


def cmd_refresh(project: Path, extra: list[Path], vocab_dir: Path) -> int:
    records = load_record_versions(project, extra)
    vocab = load_vocabulary(vocab_dir)
    decisions: list[dict[str, Any]] = []
    for name, spec in vocab.items():
        ids: dict[str, set[str]] = defaultdict(set)
        for r in records:
            for raw in raw_values(r, spec["record_field"]):
                ids[raw].add(str(r.get("id")))
        counts = Counter({raw: len(v) for raw, v in ids.items()})
        path = vocab_dir / f"{name}.csv"
        manual = {row["raw_value"]: row for row in read_csv_rows(path) if row.get("rule") == "manual"}
        rows = []
        for raw, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            if raw in manual:
                rows.append({"raw_value": raw, "records": n, "mapped": manual[raw]["mapped"], "rule": "manual"})
                continue
            values, rule = classify(name, raw)
            rows.append({"raw_value": raw, "records": n, "mapped": "|".join(values), "rule": rule})
        for raw, row in manual.items():  # keep hand decisions for values no longer present
            if raw not in counts:
                rows.append({**row, "records": 0})
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        waiting = [row for row in rows if UNMAPPED in row["mapped"].split("|") or row["rule"] == FALLBACK]
        for row in waiting:
            decisions.append({"vocabulary": name, "raw_value": row["raw_value"], "records": row["records"], "placed_in": row["mapped"]})
        print(f"{name}: {len(rows)} raw values -> {len({v for row in rows for v in row['mapped'].split('|') if v and v != UNMAPPED})} vocabulary values; "
              f"{len(waiting)} values ({sum(int(row['records']) for row in waiting)} records) placed in 'other' or waiting for a decision")
    with (vocab_dir / "decisions.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vocabulary", "raw_value", "records", "placed_in"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(decisions, key=lambda d: (d["vocabulary"], -int(d["records"]), d["raw_value"])))
    load_tables.cache_clear()
    return 0


def issues(records: Iterable[dict[str, Any]], vocab_dir: Path = VOCAB_DIR) -> list[tuple[str, str, str, str]]:
    """``(record id, field, value, problem)`` for values outside the vocabulary or not yet mapped."""
    vocab = load_vocabulary(vocab_dir)
    tables = load_tables(vocab_dir)
    out: list[tuple[str, str, str, str]] = []
    for r in records:
        rid = str(r.get("id"))
        for name, spec in vocab.items():
            source, target = spec["record_field"], spec["target"]
            if target != source:
                for v in raw_values(r, target):
                    if v not in spec["values"]:
                        out.append((rid, target, v, "not a vocabulary value"))
            for raw in raw_values(r, source):
                if raw in spec["values"] or (target != source and raw_values(r, target)):
                    continue
                if raw not in tables.get(name, {}):
                    out.append((rid, source, raw, f"not in vocab/{name}.csv"))
                elif tables[name][raw] is None:
                    out.append((rid, source, raw, f"waiting for a decision in vocab/{name}.csv"))
    return out


def cmd_check(project: Path, extra: list[Path], vocab_dir: Path) -> int:
    found = issues(load_all_records(project, extra), vocab_dir)
    by_problem = Counter((f, p) for _, f, _, p in found)
    for (field, problem), n in sorted(by_problem.items()):
        print(f"{field}: {n} values {problem}")
    print(f"vocab check: {len(found)} values outside the filter vocabularies or the mapping")
    return 1 if found else 0


def cmd_rewrite(project: Path, vocab_dir: Path, apply: bool) -> int:
    """Write normalised values into the record files. Text that carries detail is kept (licence, resolutions)."""
    vocab = load_vocabulary(vocab_dir)
    changed = 0
    for path, data in iter_record_files(project):
        view = normalised(data, vocab_dir)
        new = dict(data)
        for name, spec in vocab.items():
            target = spec["target"]
            if name == "licence_name" or target not in view:
                continue  # the standard licence is read from the licence text at build time
            values = view[target]
            if spec.get("multi"):
                new[target] = values
            elif values:
                new[target] = values[0]
        if "type" in new and path.parent.name == new.get("type") and "type" not in json.loads(path.read_text(encoding="utf-8")):
            new.pop("type")
        if new != data:
            changed += 1
            if apply:
                path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rewrite: {changed} record files {'rewritten' if apply else 'would change (dry run; add --apply)'}")
    return 0


def before_after(records: list[dict[str, Any]], vocab_dir: Path = VOCAB_DIR) -> list[dict[str, Any]]:
    vocab = load_vocabulary(vocab_dir)
    rows = []
    for name, spec in vocab.items():
        before = {raw for r in records for raw in raw_values(r, spec["record_field"])}
        after: Counter[str] = Counter()
        for r in records:
            for v in set(normalised(r, vocab_dir).get(spec["target"], [])):
                after[v] += 1
        rows.append({"vocabulary": name, "label": spec["label"], "before": len(before), "after": len(after), "counts": dict(after.most_common())})
    return rows


#: Fields that the dashboard used to offer as automatic "Other" filters and no longer does (build.py EXCLUDED_FIELDS):
#: prose, names or record references with mostly one-off values. They stay in the record detail view.
REMOVED_FILTERS = {
    "tags": "Tags", "inputs": "Inputs", "outputs": "Outputs", "outcomes": "Outcomes", "resources_used": "Resources used",
    "hosted_models": "Hosted models", "runs_on": "Runs on", "validated_on": "Validated on", "organisations": "Organisations",
    "study_period": "Study period", "temporal_coverage": "Temporal coverage", "interoperability": "Interoperability", "crs": "Coordinate system",
}

RULES_TEXT = """One word per meaning, the same in every filter:

- **Not stated**: the value was looked for and the source does not give it, or the source could not be read. It replaces
  "unknown", "unclear", "not established", "not specified", "not read", "none stated", blanks and every "not stated on the page ..." variant.
- **Varies**: the source gives different values for different parts (per dataset, per layer) and none for the whole.
- **Other**: a clear value that fits no listed value. Values that land here are listed in `vocab/decisions.csv`; a value that lands there
  often is a reason to add a vocabulary value.
- A field that does not apply is simply absent. Only two filters name that case, because it is a useful fact there:
  spatial resolution ("Not spatial") and time step ("Snapshot")."""


def cmd_report(project: Path, extra: list[Path], vocab_dir: Path, out: Path) -> int:
    records = load_all_records(project, extra)
    vocab = load_vocabulary(vocab_dir)
    lines = [f"# Proposed filter vocabulary ({len(records):,} records)", "",
             "Counts cover every record on main (13,279 records on 2026-09-29, after the round 2 wave 1 merge).",
             "The dashboard applies it when it is built; the record files keep their text until `vocab_map.py rewrite --apply` runs.", "",
             "## Filters before and after", "",
             "| Filter | Values before | Values after |", "|---|---:|---:|"]
    rows = before_after(records, vocab_dir)
    for row in rows:
        lines.append(f"| {row['label']} | {row['before']:,} | {row['after']} |")
    for field, label in REMOVED_FILTERS.items():
        before = len({v for r in records for v in raw_values(r, field)})
        if before:
            lines.append(f"| {label} | {before:,} | removed as a filter (shown in the record) |")
    lines += ["", "## Rule for missing values", "", RULES_TEXT]
    for row in rows:
        spec = vocab[row["vocabulary"]]
        lines += ["", f"## {row['label']}", "", "| Value | Records | Meaning |", "|---|---:|---|"]
        for value, meta in spec["values"].items():
            lines.append(f"| {meta['label']} | {row['counts'].get(value, 0):,} | {meta['definition']} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("command", choices=["refresh", "check", "rewrite", "report"])
    parser.add_argument("--project", default=str(HERE.parent), help="project directory holding catalog/ (default: the real project)")
    parser.add_argument("--vocab-dir", default=str(VOCAB_DIR), help="directory holding vocabulary.yaml and the mapping CSVs")
    parser.add_argument("--extra", action="append", default=[], help="JSON list of further records to include (refresh, check, report)")
    parser.add_argument("--apply", action="store_true", help="rewrite: write the files (default: dry run)")
    parser.add_argument("--out", default=None, help="report: output Markdown file")
    args = parser.parse_args(argv)
    project, vocab_dir, extra = Path(args.project).resolve(), Path(args.vocab_dir).resolve(), [Path(p) for p in args.extra]
    if args.command == "refresh":
        return cmd_refresh(project, extra, vocab_dir)
    if args.command == "check":
        return cmd_check(project, extra, vocab_dir)
    if args.command == "rewrite":
        return cmd_rewrite(project, vocab_dir, args.apply)
    return cmd_report(project, extra, vocab_dir, Path(args.out or vocab_dir / "report.md"))


if __name__ == "__main__":
    sys.exit(main())
