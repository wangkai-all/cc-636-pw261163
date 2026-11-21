from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("INTAKE_DATA_DIR", ROOT / "data"))
SAMPLES_DIR = Path(os.environ.get("INTAKE_SAMPLES_DIR", ROOT / "samples"))
MAX_UPLOAD_BYTES = int(os.environ.get("INTAKE_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))

SUPPORTED_SUFFIXES = {".sav": "sav", ".dta": "dta"}
