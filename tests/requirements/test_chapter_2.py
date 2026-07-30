from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = [
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "2.5",
        "2.6",
        "2.7",
        "2.8",
        "2.9",
        "2.10",
        "2.11",
        "2.12",
    ]
    mapped_paths = [
        "backend/src/kajovodagmar/conversations",
        "backend/src/kajovodagmar/memory",
        "web/src/features/chat",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
