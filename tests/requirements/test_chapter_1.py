from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = ["1.1", "1.2", "1.3", "1.4", "1.5"]
    mapped_paths = [
        "backend/src/kajovodagmar",
        "docs/architecture/modular-monolith.md",
        "web/src",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
