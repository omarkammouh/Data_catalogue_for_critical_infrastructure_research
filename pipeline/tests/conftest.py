"""Test scaffolding for the pipeline: import path and a temporary project directory.

Tests run against the real ``schema`` (vocabularies and record schema) and a
throw-away project directory built per test, so nothing under ``project/`` is written.
Run with ``make -C pipeline test`` or ``python3 -m pytest pipeline/tests``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An empty project-shaped directory (``catalog/<type>``, ``sources``, ``docs``)."""
    for sub in ("catalog/data", "catalog/model", "catalog/platform", "catalog/case_study", "sources/candidates", "docs"):
        (tmp_path / sub).mkdir(parents=True)
    return tmp_path


def write_record(project: Path, record: dict[str, Any]) -> Path:
    """Write one record file under ``catalog/<type>/<id>.json`` and return its path."""
    path = project / "catalog" / record["type"] / f"{record['id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    """Write a CSV with proper quoting (country names such as ``Bolivia, Plurinational State of`` contain commas)."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path
