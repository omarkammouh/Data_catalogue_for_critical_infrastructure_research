"""Select current dashboard metadata while preserving archived release metadata."""
from pathlib import Path


def snapshot_path(root):
    current = Path(root) / 'catalog/dashboard-snapshot.json'
    return current if current.exists() else Path(root) / 'catalog/snapshot.json'
