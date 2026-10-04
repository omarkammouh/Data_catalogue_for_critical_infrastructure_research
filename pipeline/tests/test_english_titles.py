"""English display titles preserve source names across catalogue formats."""
import json
import sqlite3
from pathlib import Path

from common import Paths, RecordFile, load_vocab
from compile import write_json, write_sqlite


def test_titles_survive_json_and_sqlite_without_changing_original_name(tmp_path):
    data = {
        'id': 'data-title-example', 'type': 'data',
        'name': 'Beispiel Hochwassergefahrenkarten',
        'title_en': 'Flood-hazard maps for Germany',
        'provider': 'Example agency', 'sectors': [],
    }
    record = RecordFile(tmp_path / 'data-title-example.json', 'data', data)
    vocab = load_vocab(Paths.from_args())
    write_json([record], vocab, '2026-10-03', tmp_path / 'catalog.json')
    write_sqlite([record], vocab, '2026-10-03', tmp_path / 'catalog.sqlite')
    stored = json.loads((tmp_path / 'catalog.json').read_text())['records'][0]
    assert stored['name'] == data['name']
    assert stored['title_en'] == data['title_en']
    with sqlite3.connect(tmp_path / 'catalog.sqlite') as con:
        name, title, raw = con.execute('SELECT name, title_en, json FROM records').fetchone()
    assert (name, title) == (data['name'], data['title_en'])
    assert json.loads(raw) == data
