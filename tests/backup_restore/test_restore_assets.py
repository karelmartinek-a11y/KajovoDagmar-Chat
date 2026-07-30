from pathlib import Path


def test_backup_and_restore_assets_are_complete() -> None:
    required = [
        "deployment/pgbackrest/pgbackrest.conf",
        "scripts/backup.sh",
        "scripts/restore_check.sh",
        "deployment/compose.restore-check.yaml",
    ]
    for item in required:
        assert Path(item).is_file(), item
    assert "archive_timeout = 900" in Path("deployment/postgresql.conf").read_text()
