"""Catalogue membership must distinguish evidence from names and general relations."""
import csv
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalogues import add_catalogues
from build import build_facets


def config(tmp_path, mappings=()):
    definitions = tmp_path / 'catalogues.json'
    definitions.write_text(json.dumps([
        {'id': 'mobility-database', 'label': 'Mobility Database', 'sources': ['mobilitydatabase.org-feeds_v2.csv']},
        {'id': 'hdx', 'label': 'HDX', 'sources': ['hdx', 'data.humdata.org']},
    ]))
    memberships = tmp_path / 'memberships.csv'
    with memberships.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['record_id', 'catalogue_id', 'basis', 'evidence'])
        w.writeheader(); w.writerows(mappings)
    return definitions, memberships


def test_multimembership_aliases_and_unassigned_records(tmp_path):
    records = [
        {'id': 'a', 'discovery_routes': [{'source': 'mobilitydatabase.org-feeds_v2.csv'}, {'source': 'HDX'}, {'source': 'data.humdata.org-ckan-api'}]},
        {'id': 'b', 'provider': 'Mobility Database', 'related_ids': ['a'], 'sources': [{'url': 'https://mobilitydatabase.org/'}], 'discovery_routes': [{'source': 'google-search'}]},
    ]
    before = deepcopy(records)
    out, labels, stats = add_catalogues(records, *config(tmp_path))
    assert records == before
    assert out[0]['catalogues'] == ['hdx', 'mobility-database']
    assert out[1]['catalogues'] == []
    assert stats == {'assigned_records': 1, 'unassigned_records': 1, 'catalogue_count': 2}
    facet = next(f for f in build_facets(out, {}, catalogue_labels=labels) if f['id'] == 'catalogues')
    assert facet['multi_valued'] is True
    assert {v['label']: v['count'] for v in facet['values']} == {'HDX': 1, 'Mobility Database': 1}


def test_reviewed_cross_catalogue_member_and_removed_record(tmp_path):
    mappings = [dict(record_id=rid, catalogue_id='mobility-database', basis='current_french_dataset_mapping', evidence='https://mobilitydatabase.org/feeds/gtfs/tdg-1') for rid in ('french-feed', 'removed-feed')]
    out, _, stats = add_catalogues([{'id': 'french-feed', 'discovery_routes': []}], *config(tmp_path, mappings))
    assert out[0]['catalogues'] == ['mobility-database']
    assert stats['assigned_records'] == 1


def test_uncertain_audit_mapping_is_rejected(tmp_path):
    mappings = [dict(record_id='x', catalogue_id='mobility-database', basis='provider_group_only', evidence='operator name')]
    with pytest.raises(ValueError, match='Unconfirmed'):
        add_catalogues([{'id': 'x'}], *config(tmp_path, mappings))


def test_reviewed_experiment_memberships_preserve_multiple_catalogues(tmp_path):
    mappings = [
        dict(record_id='a', catalogue_id='hdx', basis='exact_doi_identity', evidence='https://doi.org/10.1234/example'),
        dict(record_id='b', catalogue_id='hdx', basis='provider_experiment_equivalence', evidence='https://example.org/experiment/35'),
    ]
    records = [{'id': 'a', 'discovery_routes': [{'source': 'mobilitydatabase.org-feeds_v2.csv'}]}, {'id': 'b'}]
    out, _, _ = add_catalogues(records, *config(tmp_path, mappings))
    assert out[0]['catalogues'] == ['hdx', 'mobility-database']
    assert out[1]['catalogues'] == ['hdx']
    assert out[1]['catalogue_membership_evidence']['hdx'] == ['provider_experiment_equivalence: https://example.org/experiment/35']


def test_portal_suffixes_keep_catalogues_separate_and_labels_stable(tmp_path):
    records = [{'id': 'a', 'discovery_routes': [{'source': 'city.example.org-via-socrata-discovery-api'}, {'source': 'other.example.org-ods-api'}, {'source': 'ckan-unknown-ckan-catalogue'}]}]
    out, labels, _ = add_catalogues(records, *config(tmp_path))
    assert len(out[0]['catalogues']) == 2
    assert set(labels.values()) == {'city.example.org', 'other.example.org'}
    assert add_catalogues(records, *config(tmp_path))[0] == out


def test_native_catalogue_member_requires_confirmed_evidence(tmp_path):
    record = {'id': 'native-member', 'discovery_routes': [{'source': 'hdx'}]}
    mapping = dict(record_id='native-member', catalogue_id='mobility-database',
                   basis='exact_native_catalogue_identifier', evidence='https://example.org/csw?request=GetRecords')
    out, _, _ = add_catalogues([record], *config(tmp_path, [mapping]))
    assert out[0]['catalogues'] == ['hdx', 'mobility-database']
    mapping['basis'] = 'aggregator_declared_parent_only'
    with pytest.raises(ValueError, match='Unconfirmed'):
        add_catalogues([record], *config(tmp_path, [mapping]))


def test_reviewed_list_member_does_not_authorize_shared_homepage_match(tmp_path):
    mapping = dict(record_id='listed-package', catalogue_id='hdx',
                   basis='reviewed_catalogue_member_identity', evidence='audit/edge-decisions.csv:4')
    records = [{'id': 'listed-package'}, {'id': 'umbrella-project'}]
    out, _, _ = add_catalogues(records, *config(tmp_path, [mapping]))
    assert out[0]['catalogues'] == ['hdx']
    assert out[1]['catalogues'] == []
    uncertain = dict(mapping, record_id='umbrella-project', basis='shared_page_identity_pending')
    with pytest.raises(ValueError, match='Unconfirmed'):
        add_catalogues(records, *config(tmp_path, [mapping, uncertain]))


def test_large_group_evidence_is_preserved_and_reader_limit_restored(tmp_path):
    evidence = 'https://example.org/member/123 ; ' * 6000
    mapping = dict(record_id='group', catalogue_id='hdx',
                   basis='reviewed_catalogue_member_identity', evidence=evidence)
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(131072)
        out, _, _ = add_catalogues([{'id': 'group'}], *config(tmp_path, [mapping]))
        assert out[0]['catalogue_membership_evidence']['hdx'] == [
            'reviewed_catalogue_member_identity: ' + evidence]
        assert csv.field_size_limit() == 131072
    finally:
        csv.field_size_limit(previous_limit)


def test_nested_catalogue_row_does_not_inherit_host_community_membership(tmp_path):
    definitions, memberships = config(tmp_path, [
        dict(record_id='restricted-input', catalogue_id='hdx',
             basis='reviewed_nested_catalogue_metadata_row',
             evidence='catalogue.csv:DS1; reviewed exact row identity'),
    ])
    records = [
        {'id': 'restricted-input', 'sources': [{'url': 'https://example.org/catalogue'}]},
        {'id': 'host-member', 'discovery_routes': [{'source': 'mobilitydatabase.org-feeds_v2.csv'}]},
        {'id': 'held-software', 'sources': [{'url': 'https://example.org/catalogue'}]},
    ]
    out, _, stats = add_catalogues(records, definitions, memberships)
    assert out[0]['catalogues'] == ['hdx']
    assert out[1]['catalogues'] == ['mobility-database']
    assert out[2]['catalogues'] == []
    assert out[0]['catalogue_membership_evidence']['hdx'] == [
        'reviewed_nested_catalogue_metadata_row: catalogue.csv:DS1; reviewed exact row identity']
    assert stats['unassigned_records'] == 1
