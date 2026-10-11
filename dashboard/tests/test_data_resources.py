"""A catalogue link and catalogue membership are independent facts."""
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_resources import add_data_resource_types
from build import build_facets


def test_parent_and_member_keep_different_classifications_without_mutation():
    records = [
        {'id': 'parent', 'type': 'data', 'data_resource_type': 'data_catalogue', 'data_kind': ['tabular']},
        {'id': 'member', 'type': 'data', 'data_kind': ['network_topology'], 'catalogues': ['parent']},
        {'id': 'standalone', 'type': 'data', 'data_kind': ['time_series'], 'catalogues': []},
        {'id': 'model', 'type': 'model'},
    ]
    before = deepcopy(records)
    out = add_data_resource_types(records)
    assert records == before
    assert [r.get('data_resource_type') for r in out] == ['data_catalogue', 'dataset', 'dataset', None]
    assert out[2]['catalogues'] == []


@pytest.mark.parametrize('kinds,families,expected', [
    (['document'], [], 'information_source'),
    (['document', 'tabular'], [], 'unknown'),
    (['tabular'], ['catalogues_registries'], 'unknown'),
    (['tabular'], ['standards_ontologies'], 'unknown'),
    (['unknown'], [], 'unknown'),
    ([], [], 'unknown'),
    (['stream'], ['demand_operation'], 'dataset'),
])
def test_saved_metadata_preserves_information_and_uncertainty(kinds, families, expected):
    out = add_data_resource_types([{'id': 'x', 'type': 'data', 'data_kind': kinds, 'data_family': families}])
    assert out[0]['data_resource_type'] == expected


def test_unknown_explicit_category_is_rejected():
    with pytest.raises(ValueError, match='Invalid'):
        add_data_resource_types([{'type': 'data', 'data_resource_type': 'portalish'}])


def test_filter_exposes_all_categories_with_counts():
    rs = add_data_resource_types([
        {'id': 'a', 'type': 'data', 'data_resource_type': 'data_catalogue'},
        {'id': 'b', 'type': 'data', 'data_kind': ['tabular']},
        {'id': 'c', 'type': 'data', 'data_kind': ['document']},
        {'id': 'd', 'type': 'data'},
    ])
    vocab = {'data_resource_types': ['dataset', 'data_catalogue', 'information_source', 'unknown']}
    f = next(f for f in build_facets(rs, vocab) if f['id'] == 'data_resource_type')
    assert {v['value']: v['count'] for v in f['values']} == {k: 1 for k in vocab['data_resource_types']}
    assert not any(f['id'] == 'data_resource_type_basis' for f in build_facets(rs, vocab))


def test_catalogue_record_preserves_unknown_verification_and_languages():
    import json
    import jsonschema
    project = Path(__file__).resolve().parents[2]
    schema = json.loads((project / 'schema/record.schema.json').read_text())
    record = json.loads((project / 'catalog/data/data-catalogue-taltech-repository.json').read_text())
    assert record['date_verified'] is None
    assert record['languages'] == []
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER).validate(record)
    record['data_resource_type'] = 'portalish'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(record)
