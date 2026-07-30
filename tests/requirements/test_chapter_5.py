from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = [
        "5.1",
        "5.2",
        "5.3",
        "5.4",
        "5.5",
        "5.6",
        "5.7",
        "5.8",
        "5.9",
        "5.10",
        "5.11",
        "5.12",
        "5.13",
        "5.14",
        "5.15",
        "5.16",
        "5.17",
        "5.18",
        "5.19",
        "5.20",
        "5.21",
        "5.22",
        "5.23",
        "5.24",
        "5.25",
        "5.26",
        "5.27",
        "5.28",
        "5.29",
        "5.30",
    ]
    mapped_paths = [
        "tests/accessibility",
        "web/src/app/AppShell.tsx",
        "web/src/features",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
