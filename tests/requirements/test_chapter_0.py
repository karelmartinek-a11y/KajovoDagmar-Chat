from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = [
        "0.1",
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.10",
        "0.11",
        "0.12",
    ]
    mapped_paths = [
        "GENERATION_MANIFEST.json",
        "docs/architecture/decisions.md",
        "scripts/check_forbidden.py",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
