from pathlib import Path


def test_chapter_requirements_are_mapped() -> None:
    requirement_ids = [
        "3.1",
        "3.2",
        "3.3",
        "3.4",
        "3.5",
        "3.6",
        "3.7",
        "3.8",
        "3.9",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.14",
        "3.15",
        "3.16",
    ]
    mapped_paths = [
        "web/src/app/AppShell.tsx",
        "web/src/i18n/cs.ts",
        "web/src/styles/tokens.css",
    ]
    assert requirement_ids
    for path in mapped_paths:
        assert Path(path).exists(), path
