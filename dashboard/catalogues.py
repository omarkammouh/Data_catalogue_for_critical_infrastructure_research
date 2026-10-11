"""Derive catalogue memberships from recorded discovery sources and reviewed mappings."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# These suffixes identify catalogue harvests in the saved discovery metadata.
# General web searches, provider names, citations and related_ids are not membership evidence.
SUFFIXES = (
    '-via-socrata-discovery-api', '-via-data.opendatasoft.com',
    '-socrata-catalog-api', '-opendatasoft-catalogue', '-ckan-catalogue',
    '-arcgis-hub-dcat', '-publications-api', '-catalogue-api',
    '-ckan-api', '-ods-api', '-csw', '-dcat',
)


def key(value):
    return ' '.join(value.casefold().split())


def add_catalogues(records, definitions=None, memberships=None):
    """Return copied records, labels and counts. Never modify source record dictionaries.

    Unrecognised sources remain unassigned. Reviewed memberships apply only to IDs
    still present; a record can belong to several catalogues. Evidence is exported
    with each derived record without being exposed as an additional filter.
    """
    definitions = definitions or HERE / 'catalogues.json'
    memberships = memberships or HERE / 'catalogue-memberships.csv'
    config = json.loads(Path(definitions).read_text(encoding='utf-8'))
    labels, aliases = {}, {}
    for definition in config:
        cid = definition['id']
        if cid in labels:
            raise ValueError(f'Duplicate catalogue ID: {cid}')
        labels[cid] = definition['label']
        for alias in definition['sources']:
            alias = key(alias)
            if alias in aliases and aliases[alias] != cid:
                raise ValueError(f'Ambiguous catalogue source: {alias}')
            aliases[alias] = cid

    def classify(source):
        source_key = key(source)
        if source_key in aliases:
            return aliases[source_key]
        for suffix in SUFFIXES:
            if source_key.endswith(suffix):
                stem = source.strip()[:-len(suffix)].strip()
                if key(stem) in aliases:
                    return aliases[key(stem)]
                # Unlabelled harvester codes are not useful catalogue names.
                if not stem or stem.lower().startswith(('ckan-', 'ods-')):
                    return None
                stem_key = key(stem)
                slug = re.sub(r'[^a-z0-9]+', '-', stem_key).strip('-')[:65]
                cid = 'source-' + slug + '-' + hashlib.sha256(stem_key.encode()).hexdigest()[:8]
                labels[cid] = min(labels.get(cid, stem), stem)
                return cid
        return None

    reviewed = defaultdict(list)
    previous_limit = csv.field_size_limit()
    try:
        # Grouped resources retain individual evidence for hundreds of members.
        csv.field_size_limit(max(previous_limit, 10_000_000))
        with Path(memberships).open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['catalogue_id'] not in labels:
                    raise ValueError(f"Unknown reviewed catalogue: {row['catalogue_id']}")
                if not row['evidence'] or not row['basis']:
                    raise ValueError('Catalogue membership lacks evidence')
                if row['basis'] not in {'explicit_feed_identity', 'current_french_dataset_mapping', 'historical_feed_mapping', 'exact_doi_identity', 'provider_experiment_equivalence', 'exact_native_catalogue_identifier', 'reviewed_catalogue_member_identity', 'reviewed_nested_catalogue_metadata_row'}:
                    raise ValueError(f"Unconfirmed catalogue membership: {row['basis']}")
                reviewed[row['record_id']].append(row)
    finally:
        csv.field_size_limit(previous_limit)

    output, assigned, used = [], 0, set()
    for record in records:
        evidence = defaultdict(set)
        for route in record.get('discovery_routes', []):
            source = route.get('source')
            if isinstance(source, str):
                cid = classify(source)
                if cid:
                    evidence[cid].add('Discovery source: ' + source)
        for row in reviewed.get(record['id'], []):
            evidence[row['catalogue_id']].add(row['basis'] + ': ' + row['evidence'])
        result = dict(record)
        result['catalogues'] = sorted(evidence)
        result['catalogue_membership_evidence'] = {cid: sorted(evidence[cid]) for cid in sorted(evidence)}
        output.append(result)
        used.update(evidence)
        assigned += bool(evidence)
    return output, {cid: labels[cid] for cid in sorted(used)}, {
        'assigned_records': assigned, 'unassigned_records': len(records) - assigned,
        'catalogue_count': len(used),
    }
