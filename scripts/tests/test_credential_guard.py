import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from credential_guard import contains_credential
from import_snapshot import read_records, run, transform
from package_release import build


def keyed_record():
    # Construct a synthetic match so the fixture contains no complete key.
    return {'id': 'data-example', 'type': 'data',
            'access_links': [{'url': 'https://example.org/feed?key=' + 'AI' + 'za' + 'x' * 35}]}


def test_credential_in_nested_source_field_is_rejected_without_echo():
    record = keyed_record()
    value = record['access_links'][0]['url']
    with pytest.raises(ValueError) as error:
        transform(record, {})
    assert value not in str(error.value)
    assert contains_credential(json.dumps(record))
    assert not contains_credential('https://example.org/dataset?id=42')


def test_import_and_release_refuse_keys_before_writing_records_or_exports(tmp_path):
    for kind in ('data', 'model', 'platform', 'case_study'):
        (tmp_path / 'catalog' / kind).mkdir(parents=True)
    source = tmp_path / 'catalog/data/data-example.json'
    source.write_text(json.dumps(keyed_record()))
    destination = tmp_path / 'public'
    with pytest.raises(ValueError, match='possible credential'):
        run(tmp_path, destination, {}, apply=True)
    assert not destination.exists()
    with pytest.raises(ValueError, match='possible credential'):
        build(tmp_path)
    assert not (tmp_path / 'build').exists()
