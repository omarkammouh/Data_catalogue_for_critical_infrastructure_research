#!/usr/bin/env python3
"""Check public metadata, links between records, and publication hygiene."""
import json,re,sys,os
from pathlib import Path
import yaml
from credential_guard import contains_credential
ROOT=Path(__file__).resolve().parents[1]
errors=[]
IGNORE={'.git','.local','.venv','node_modules','__pycache__','.pytest_cache','dist','dist-test','build','test-results','playwright-report'}
def public_files():
    for directory, folders, files in os.walk(ROOT):
        folders[:] = [x for x in folders if x not in IGNORE]
        for name in files:yield Path(directory)/name
for p in public_files():
    if p.stat().st_size>99_000_000:errors.append(f'{p.relative_to(ROOT)}: exceeds Git file limit')
    if p.suffix in {'.png','.jpg','.woff2'}:continue
    text=p.read_text(errors='replace')
    if contains_credential(text):errors.append(f'{p.relative_to(ROOT)}: possible credential')
    if re.search(r'/(?:Users|home)/[A-Za-z0-9_.-]+/', re.sub(r'https?://[^\s\"<>]+', '', text)):errors.append(f'{p.relative_to(ROOT)}: local user path')
meta=json.loads((ROOT/'.zenodo.json').read_text());citation=yaml.safe_load((ROOT/'CITATION.cff').read_text())
if meta['title']!=citation['title'] or meta['version']!=citation['version']:errors.append('Citation metadata disagree')
if citation['version']!=json.loads((ROOT/'catalog/snapshot.json').read_text())['version']:errors.append('Snapshot version disagrees')
if errors:print('\n'.join(errors));sys.exit(1)
print('Public metadata and file checks passed')
