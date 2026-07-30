from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_generated_contracts_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        cwd=Path(__file__).resolve().parents[2],
        env={"PYTHONPATH": "backend/src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
