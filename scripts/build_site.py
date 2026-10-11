#!/usr/bin/env python3
"""Build only the site files needed for static hosting."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
from snapshot import snapshot_path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--date');a=p.parse_args()
subprocess.run([sys.executable,str(ROOT/'scripts/check_public.py')],check=True,cwd=ROOT)
out=ROOT/'dashboard/dist'
if out.exists():shutil.rmtree(out)
cmd=[sys.executable,str(ROOT/'dashboard/build.py'),'--project',str(ROOT),'--out',str(out/'index.html'),'--data-file','catalogue-data','--no-bundle']
if a.date:cmd+=['--date',a.date]
# Always build from record files, so a previous compilation cannot hide edits.
compiled=ROOT/'catalog/catalog.json'
if compiled.exists():compiled.unlink()
subprocess.run(cmd,check=True,cwd=ROOT)
(out/'.nojekyll').write_text('')
shutil.copyfile(snapshot_path(ROOT),out/'snapshot.json')
size=sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
if size>=1_000_000_000:raise SystemExit('Site exceeds the 1 GB Pages size limit')
print(json.dumps({'site_bytes':size,'files':len(list(out.iterdir()))}))
