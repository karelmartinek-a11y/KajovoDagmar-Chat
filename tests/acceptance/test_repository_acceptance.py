from __future__ import annotations

import json
from pathlib import Path


def test_required_repository_structure() -> None:
    for path in [
        "backend",
        "web",
        "migrations",
        "tests",
        "deployment",
        "scripts",
        "docs",
        "Makefile",
        "GENERATION_MANIFEST.json",
    ]:
        assert Path(path).exists(), path


def test_all_chapters_are_traceable() -> None:
    data = json.loads(Path("docs/traceability/requirements.json").read_text())
    assert {item["id"].split(".")[0] for item in data} == {str(i) for i in range(21)}
    assert all(item["status"] == "implemented_verified" for item in data)


def test_release_check_is_not_optional() -> None:
    makefile = Path("Makefile").read_text()
    assert "release-check:" in makefile
    script = Path("scripts/release_check.sh").read_text()
    for gate in [
        "toolchain",
        "bootstrap",
        "source",
        "lint",
        "typecheck",
        "unit",
        "integration",
        "security",
        "image_build",
        "restore",
        "sbom",
        "acceptance",
    ]:
        assert gate in script
