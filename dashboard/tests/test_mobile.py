"""Compact mode must preserve identities, every facet, and fuzzy search scores."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from mobile import compact_bundle, normalise


def test_compact_equivalence(tmp_path):
    subprocess.run([sys.executable, str(HERE / 'build.py'), '--project',
                    str(HERE / 'tests/fixtures'), '--out', str(tmp_path / 'index.html'),
                    '--date', '2026-09-24'], check=True, capture_output=True)
    bundle = json.loads((tmp_path / 'bundle.json').read_text())
    spec = importlib.util.spec_from_file_location('dashboard_build', HERE / 'build.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    # Include repeated letters/trigrams, long tokens, non-ASCII, punctuation,
    # and a fuzzy match whose evidence is split across different words.
    bundle['records'][0]['notes'] = 'Électricité İstanbul Straße 漢字 αβγ aaaaa xabc bcdx café cafe\u0301 ' + 'a' * 45
    compact, parts, names = compact_bundle(copy.deepcopy(bundle), build.TEXT_FIELDS, build.extract, 'data')
    assert len(compact['records']) == len(bundle['records'])
    details = [r for name, text in parts if name not in names for r in json.loads(text)]
    assert details == bundle['records']
    for full, row in zip(bundle['records'], compact['records']):
        assert full['id'] == row['id']
        for f in bundle['facets']:
            if f['kind'] == 'text': continue
            col = next(i for i, x in enumerate(compact['facets']) if x['id'] == f['id'])
            values = row['_facets'][col]
            decoded = values if f['kind'] == 'range' else [str(compact['facets'][col]['values'][v]['value']) for v in values]
            assert decoded == build.extract(full, f)
    data = tmp_path / 'compare.json'
    queries = ['électricité', 'istanbul', 'straße', '漢字', 'αβγ', 'aa', 'aaaaaa', 'abcd',
               'a' * 45, 'cafe', 'electricity water', 'grid', 'pandapowr', 'synth', 'distribution']
    queries += [r['name'] for r in bundle['records']]
    wire = [json.loads(text) for name, text in parts if name in names]
    data.write_text(json.dumps(dict(full=bundle, compact=compact, wire=wire, queries=queries), ensure_ascii=False))
    script = r"""
const fs=require('fs'),assert=require('assert'),E=require(process.argv[1]);
const d=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const full=E.createEngine(d.full.records,d.full.facets,{textFields:d.full.meta.text_fields});
const compact=E.createEngine(d.compact.records,d.compact.facets,{searchWords:d.compact.search_words});
const header=d.wire[0], rows=d.wire.flatMap(p=>E.decodeCompactPart(p,header));
const packed=E.createEngine(rows,header.facets,{searchWords:header.search_words});
assert.strictEqual(packed.textIndexReady(),true);
for(const text of d.queries)for(const sort of Object.keys(E.SORTS)){
 const state={text,facets:{},sort};
 const a=full.query(state);
 for(const engine of [compact,packed])for(const key of ['ids','scores','counts','ranges'])assert.deepStrictEqual(engine.query(state)[key],a[key],text+' '+key);
}
for(const facet of d.full.facets)for(const value of (facet.values||[])){
 const state={facets:{[facet.id]:{values:[value.value],all:true}},sort:'name'};
 const a=full.query(state);
 for(const engine of [compact,packed])for(const key of ['ids','counts','ranges'])assert.deepStrictEqual(engine.query(state)[key],a[key],facet.id);
}
for(const word of d.compact.search_words)assert.strictEqual(E.normalise(word),word);
assert.throws(()=>E.decodeCompactPart({...header,word_codes:header.word_codes.slice(4)},header));
"""
    subprocess.run(['node', '-e', script, str(HERE / 'src/engine.js'), str(data)], check=True)
