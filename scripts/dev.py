"""One command to run the intake desk locally (FastAPI + Vite dev server)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
FRONTEND = ROOT / "frontend"
BACKEND_PORT = os.environ.get("INTAKE_BACKEND_PORT", "8000")
FRONTEND_PORT = os.environ.get("INTAKE_FRONTEND_PORT", "5173")


def _python() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _require_samples() -> None:
    if not (ROOT / "samples" / "demo_intake.sav").exists():
        subprocess.run([_python(), str(ROOT / "scripts" / "build_samples.py")], check=True)


def main() -> int:
    if not (FRONTEND / "node_modules").exists():
        print("frontend/node_modules 不存在，请先运行：cd frontend && npm install", file=sys.stderr)
        return 1
    _require_samples()

    backend = subprocess.Popen(
        [
            _python(),
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(ROOT / "backend"),
            "--host",
            "127.0.0.1",
            "--port",
            BACKEND_PORT,
        ],
        cwd=ROOT,
    )
    vite = shutil.which("npm") or "npm"
    frontend = subprocess.Popen(
        [vite, "run", "dev", "--", "--host", "127.0.0.1", "--port", FRONTEND_PORT],
        cwd=FRONTEND,
    )

    def _stop(*_: object) -> None:
        for process in (frontend, backend):
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 5
        for process in (frontend, backend):
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if process.poll() is None:
                process.kill()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"后端  http://127.0.0.1:{BACKEND_PORT}/api/health")
    print(f"前端  http://127.0.0.1:{FRONTEND_PORT}/")
    try:
        while True:
            for process in (backend, frontend):
                code = process.poll()
                if code is not None:
                    _stop()
                    return code
            time.sleep(0.5)
    finally:
        _stop()


if __name__ == "__main__":
    raise SystemExit(main())
