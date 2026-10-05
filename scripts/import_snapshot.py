#!/usr/bin/env python3
"""Stage catalogue updates without overwriting community changes.

The source must contain catalog/<type>/*.json or be that catalog directory.
A local JSON policy can supply reviewed text replacements and excluded source URLs.
The default is a dry run. Apply only a conflict-free report with --apply.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone
from credential_guard import check_record
TYPES = ('data', 'model', 'platform', 'case_study')
ROOT = Path(__file__).resolve().parents[1]

def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()

def transform(record, policy):
    check_record(record)
    record = copy.deepcopy(record)
    def walk(value, field):
        if isinstance(value, str):
            if value.startswith(('https://', 'http://')):
                if policy.get('strip_tracking_parameters'):
                    from urllib.parse import urlsplit, urlunsplit
                    parts=urlsplit(value)
                    query='&'.join(p for p in parts.query.split('&') if not p.split('=',1)[0].lower().startswith('utm_'))
                    return urlunsplit((parts.scheme,parts.netloc,parts.path,query,parts.fragment))
                return value
            for rule in policy.get('replacements', []):
                if field in rule.get('fields', [field]):
                    value = re.sub(rule['pattern'], rule['replacement'], value, flags=re.I)
            return value
        if isinstance(value, list): return [walk(v, field) for v in value]
        if isinstance(value, dict): return {k: walk(v, field) for k,v in value.items()}
        return value
    if policy.get('tag_patterns'):
        record['tags'] = [t for t in record.get('tags', []) if not any(re.search(p,t,re.I) for p in policy['tag_patterns'])]
    for field in record: record[field] = walk(record[field], field)
    prefixes = policy.get('excluded_source_prefixes', [])
    if prefixes:
        record['sources'] = [s for s in record.get('sources', []) if not any(s.get('url','').startswith(p) for p in prefixes)]
        if not record['sources']: raise ValueError(f"{record['id']}: no public source remains")
    if policy.get('tag_patterns'):
        record['tags'] = [t for t in record.get('tags', []) if not any(re.search(p,t,re.I) for p in policy['tag_patterns'])]
    return record

def read_records(source, policy=None):
    base = source / 'catalog' if (source / 'catalog').is_dir() else source
    records={}; raw_hashes={}
    for kind in TYPES:
        if not (base/kind).is_dir(): raise ValueError(f'Missing record directory: {base/kind}')
        for path in sorted((base/kind).glob('*.json')):
            raw = path.read_bytes(); record=json.loads(raw)
            rid=record['id']
            if rid in records: raise ValueError(f'Duplicate ID: {rid}')
            if record['type'] != kind or path.stem != rid or not re.fullmatch(r'(data|model|platform|case_study)-[a-z0-9]+(?:-[a-z0-9]+)*',rid):
                raise ValueError(f'Invalid identity or path: {path}')
            records[rid]=transform(record,policy or {})
            raw_hashes[str(path.relative_to(base))]=hashlib.sha256(raw).hexdigest()
    if not records: raise ValueError('Empty source refused')
    return records,raw_hashes

def stable_records(source,policy):
    for _ in range(5):
        incoming,before=read_records(source,policy)
        base=source/'catalog' if (source/'catalog').is_dir() else source
        after={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for kind in TYPES for p in sorted((base/kind).glob('*.json'))}
        if before==after:return incoming,before
    raise ValueError('Source changed during capture; retry when saved files are stable')

def classify(baseline,current,incoming):
    changes=[]; conflicts=[]; preserved=[]
    for rid in sorted(set(baseline)|set(current)|set(incoming)):
        old=baseline.get(rid); local=digest(current[rid]) if rid in current else None
        new=digest(incoming[rid]) if rid in incoming else None
        if new==old:
            if local!=old:preserved.append(rid)
            continue
        if local==new:continue
        if local!=old:
            conflicts.append(rid);continue
        changes.append({'id':rid,'action':'remove' if new is None else ('add' if old is None else 'modify')})
    return changes,conflicts,preserved

def run(source,destination,policy,apply=False):
    incoming,raw=stable_records(source,policy)
    baseline_path=destination/'catalog/import-baseline.json'
    baseline=json.loads(baseline_path.read_text())['records'] if baseline_path.exists() else {}
    current,_=read_records(destination) if any((destination/'catalog'/k).is_dir() for k in TYPES) else ({},{})
    changes,conflicts,preserved=classify(baseline,current,incoming)
    stage=destination/'.local/import';stage.mkdir(parents=True,exist_ok=True)
    report={'captured_at':datetime.now(timezone.utc).isoformat(),'changes':changes,'conflicts':conflicts,'preserved_community_edits':preserved,
            'incoming_records':len(incoming),'source_sha256':raw,'incoming_hashes':{rid:digest(r) for rid,r in sorted(incoming.items())}}
    (stage/'report.json').write_bytes(encode(report))
    if apply:
        if conflicts:raise ValueError(f'{len(conflicts)} conflicts; no catalogue changes applied. See .local/import/report.json')
        # Validate all proposed records and references before changing any catalogue file.
        import sys
        sys.path.insert(0,str(ROOT/'pipeline'))
        from common import Paths, load_vocab
        from validate import Validator
        import tempfile
        with tempfile.TemporaryDirectory(dir=stage) as temporary:
            trial=Path(temporary)
            proposed=dict(current)
            for change in changes:
                rid=change['id']
                if change['action']=='remove':proposed.pop(rid,None)
                else:proposed[rid]=incoming[rid]
            for record in proposed.values():
                p=trial/'catalog'/record['type']/(record['id']+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encode(record))
            paths=Paths.from_args(trial,destination/'schema')
            validator=Validator(paths, strict_description=True)
            validator.run()
            if any(x.level=='error' for x in validator.issues):raise ValueError('Proposed catalogue failed validation: ' + '; '.join(str(x) for x in validator.issues if x.level=='error'))
        current_after,_=read_records(destination) if current else ({},{})
        if {k:digest(v) for k,v in current_after.items()} != {k:digest(v) for k,v in current.items()}:
            raise ValueError('Public records changed during validation; apply refused')
        for change in changes:
            rid=change['id'];kind=rid.split('-',1)[0];path=destination/'catalog'/kind/(rid+'.json')
            if change['action']=='remove':path.unlink()
            else:
                path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_bytes(encode(incoming[rid]));tmp.replace(path)
        baseline_path.write_bytes(encode({'records':report['incoming_hashes']}))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=ROOT)
    parser.add_argument('--policy',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    policy=json.loads(args.policy.read_text()) if args.policy else {}
    try:
        r=run(args.source.resolve(),args.destination.resolve(),policy,args.apply)
    except (ValueError,KeyError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps({k:len(r[k]) for k in ('changes','conflicts','preserved_community_edits')},indent=2))
    if r['conflicts']:raise SystemExit(1)
