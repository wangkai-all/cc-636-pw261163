from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Keep test data inside the repository's temp area.
os.environ.setdefault("INTAKE_DATA_DIR", str(ROOT / "backend" / "tests" / ".data"))


@pytest.fixture(scope="session", autouse=True)
def _samples() -> None:
    if not (ROOT / "samples" / "demo_intake.sav").exists():
        os.system(f"{sys.executable} {ROOT / 'scripts' / 'build_samples.py'}")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INTAKE_DATA_DIR", str(tmp_path / "data"))
    # config.DATA_DIR is resolved at import time; patch it for this process.
    from app import config, storage

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
