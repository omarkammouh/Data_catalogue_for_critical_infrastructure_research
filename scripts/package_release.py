#!/usr/bin/env python3
"""Create reproducible compressed metadata downloads and SHA-256 checksums."""
import csv,gzip,hashlib,io,json
from pathlib import Path
from import_snapshot import read_records
ROOT=Path(__file__).resolve().parents[1]
def build(root=ROOT):
    records,_=read_records(root); rows=[records[k] for k in sorted(records)]
    out=root/'build/release';out.mkdir(parents=True,exist_ok=True)
    fields=['id','type','title_en','name','provider','description','homepage','repository','licence','cost','access_restrictions','sectors','countries','simulation_uses','date_catalogued','date_verified','sources','access_links']
    stream=io.StringIO(newline='');w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
    for r in rows:
        row={k:json.dumps(r[k],ensure_ascii=False) if isinstance(r.get(k),(dict,list)) else r.get(k,'') for k in fields}
        # Prevent spreadsheet formula execution when opening CSV exports.
        row={k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()}
        w.writerow(row)
    payloads={'catalogue.json.gz':json.dumps({'snapshot':json.loads((root/'catalog/snapshot.json').read_text()),'records':rows},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode(),'catalogue.csv.gz':stream.getvalue().encode()}
    for name,data in payloads.items():(out/name).write_bytes(gzip.compress(data,mtime=0))
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256((out/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in sorted(payloads)))
    print(f'Packaged {len(rows)} records in {out}')
if __name__=='__main__':build()
