import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from import_snapshot import classify,digest,transform,read_records
import pytest

def row(value):return {'id':'data-example','type':'data','name':value}
def test_community_edit_survives_unchanged_import():
 a,b=row('old'),row('community');assert classify({'data-example':digest(a)},{'data-example':b},{'data-example':a})==([],[],['data-example'])
def test_upstream_change_applies_when_public_unchanged():
 a,b=row('old'),row('new');changes,conflicts,_=classify({'data-example':digest(a)},{'data-example':a},{'data-example':b});assert changes==[{'id':'data-example','action':'modify'}];assert not conflicts

def test_both_changed_conflicts():
 a,b,c=row('old'),row('community'),row('incoming');assert classify({'data-example':digest(a)},{'data-example':b},{'data-example':c})[1]==['data-example']
def test_deletion_conflicts_with_community_edit():
 a,b=row('old'),row('community');assert classify({'data-example':digest(a)},{'data-example':b},{})[1]==['data-example']
def test_new_community_record_is_preserved():
 assert classify({}, {'data-example':row('new')},{})==([],[],['data-example'])
def test_matching_edits_converge():
 a,b=row('old'),row('same');assert classify({'data-example':digest(a)},{'data-example':b},{'data-example':b})==([],[],[])
def test_new_incoming_record_and_unmodified_deletion():
 a=row('new');assert classify({}, {},{'data-example':a})[0][0]['action']=='add'
 assert classify({'data-example':digest(a)},{'data-example':a},{})[0][0]['action']=='remove'
def test_public_deletion_is_not_silently_undone():
 a,b=row('old'),row('new');assert classify({'data-example':digest(a)},{},{'data-example':b})[1]==['data-example']
def test_transformation_preserves_original_and_rejects_loss_of_sources():
 a={'id':'data-example','name':'Original','notes':'private-label','sources':[{'url':'https://example.org'}]}
 b=transform(a,{'replacements':[{'pattern':'private-label','replacement':'metadata review','fields':['notes']}]})
 assert a['notes']=='private-label' and b['name']=='Original' and b['notes']=='metadata review'
 with pytest.raises(ValueError):transform(a,{'excluded_source_prefixes':['https://example.org']})
def test_empty_source_is_refused(tmp_path):
 with pytest.raises(ValueError):read_records(tmp_path)

def test_apply_updates_record_and_baseline_and_preserves_community(tmp_path):
 import json,shutil
 from import_snapshot import run,encode
 root=Path(__file__).resolve().parents[2]
 dest=tmp_path/'public';source=tmp_path/'incoming'
 shutil.copytree(root/'dashboard/tests/fixtures/catalog',dest/'catalog')
 shutil.copytree(root/'dashboard/tests/fixtures/catalog',source/'catalog')
 shutil.copytree(root/'schema',dest/'schema');shutil.copyfile(root/'schema.md',dest/'schema.md')
 for base in (dest,source):
  for p in (base/'catalog').glob('*/*.json'):
   value=json.loads(p.read_text());value.setdefault('description_checked','2026-09-24');p.write_bytes(encode(value))
 current,_=read_records(dest)
 (dest/'catalog/import-baseline.json').write_bytes(encode({'records':{k:digest(v) for k,v in current.items()}}))
 ids=sorted(current); first,second=ids[:2]
 def change(base,rid,name):
  r=dict(current[rid]);r['provider']=name;p=base/'catalog'/r['type']/(rid+'.json');p.write_bytes(encode(r));return p
 changed=change(source,first,'Updated provider metadata')
 community=change(dest,second,'Community correction')
 before=community.read_bytes()
 r=run(source,dest,{},True)
 assert r['conflicts']==[] and second in r['preserved_community_edits']
 assert (dest/'catalog'/current[first]['type']/(first+'.json')).read_bytes()==changed.read_bytes()
 assert community.read_bytes()==before
 assert run(source,dest,{},False)['changes']==[]

def test_conflicted_apply_writes_no_record(tmp_path):
 import shutil
 from import_snapshot import run,encode
 root=Path(__file__).resolve().parents[2];dest=tmp_path/'public';source=tmp_path/'incoming'
 shutil.copytree(root/'dashboard/tests/fixtures/catalog',dest/'catalog');shutil.copytree(root/'dashboard/tests/fixtures/catalog',source/'catalog')
 current,_=read_records(dest);rid=next(iter(current));original=current[rid]
 (dest/'catalog/import-baseline.json').write_bytes(encode({'records':{k:digest(v) for k,v in current.items()}}))
 path=Path('catalog')/original['type']/(rid+'.json')
 (dest/path).write_bytes(encode(dict(original,provider='Public change')))
 (source/path).write_bytes(encode(dict(original,provider='Different source change')))
 before=(dest/path).read_bytes()
 with pytest.raises(ValueError,match='conflicts'):run(source,dest,{},True)
 assert (dest/path).read_bytes()==before

def test_urls_keep_resource_identity_while_tracking_is_removed():
 a={'id':'data-example','sources':[{'url':'https://example.org/sandbox/test?resource=2&utm_source=ref#section'}]}
 assert transform(a,{'strip_tracking_parameters':True})['sources'][0]['url']=='https://example.org/sandbox/test?resource=2#section'

def test_internal_health_references_are_omitted_without_changing_provider_outcomes():
 original={'id':'data-example','link_health':{'dead':['https://example.org/internal/review','https://provider.org/resource'],'checked':'2026-10-11'}}
 public=transform(original,{'excluded_link_health_prefixes':['https://example.org/internal/']})
 assert public['link_health']=={'dead':['https://provider.org/resource'],'checked':'2026-10-11'}
 assert len(original['link_health']['dead'])==2
