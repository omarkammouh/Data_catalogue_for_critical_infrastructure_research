"""Classify data resources without confusing a catalogue with its members."""
from __future__ import annotations

DATASET_KINDS = frozenset({
    'asset_inventory', 'network_topology', 'time_series', 'raster', 'tabular',
    'survey', 'event_record', 'stream', 'imagery',
})
INFORMATION_FAMILIES = frozenset({
    'catalogues_registries', 'standards_ontologies', 'planning_regulatory_documents',
})
RESOURCE_TYPES = frozenset({'dataset', 'data_catalogue', 'information_source', 'unknown'})


def add_data_resource_types(records):
    """Return copied records; explicit source classifications take priority.

    A structured representation supports a dataset label only if the record is
    not also a document or a catalogue/standards/planning information source.
    Membership, hostnames and provider names never determine this classification.
    """
    output = []
    for record in records:
        result = dict(record)
        if record.get('type') == 'data':
            explicit = record.get('data_resource_type')
            if explicit is not None:
                if explicit not in RESOURCE_TYPES:
                    raise ValueError(f"Invalid data resource type: {explicit!r}")
                category, basis = explicit, 'Explicit source-record classification'
            else:
                kinds = set(record.get('data_kind') or [])
                families = set(record.get('data_family') or [])
                if kinds and kinds <= DATASET_KINDS and not families & INFORMATION_FAMILIES:
                    category, basis = 'dataset', 'Saved data_kind establishes a structured data representation'
                elif kinds == {'document'} and 'catalogues_registries' not in families:
                    category, basis = 'information_source', 'Saved data_kind is document only'
                else:
                    category, basis = 'unknown', 'Saved metadata does not establish a dataset or data catalogue classification'
            result['data_resource_type'] = category
            result['data_resource_type_basis'] = basis
        output.append(result)
    return output
