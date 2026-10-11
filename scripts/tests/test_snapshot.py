import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snapshot import snapshot_path


def test_current_dashboard_metadata_does_not_replace_archived_release(tmp_path):
    catalog = tmp_path / 'catalog'
    catalog.mkdir()
    release = catalog / 'snapshot.json'
    release.write_text(json.dumps({'version': '1.0.0', 'records': 10}))
    assert snapshot_path(tmp_path) == release
    current = catalog / 'dashboard-snapshot.json'
    current.write_text(json.dumps({'snapshot_kind': 'current_main', 'records': 12}))
    assert snapshot_path(tmp_path) == current
    assert json.loads(release.read_text()) == {'version': '1.0.0', 'records': 10}
