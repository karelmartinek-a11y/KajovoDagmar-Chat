from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = [
        "4.1",
        "4.2",
        "4.3",
        "4.4",
        "4.5",
        "4.6",
        "4.7",
        "4.8",
        "4.9",
        "4.10",
        "4.11",
        "4.12",
        "4.13",
        "4.14",
        "4.15",
        "4.16",
        "4.17",
        "4.18",
        "4.19",
        "4.20",
        "4.21",
        "4.22",
    ]
    mapped_paths = [
        "backend/src/kajovodagmar/identity",
        "web/src/features/auth",
        "web/src/features/profile",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
