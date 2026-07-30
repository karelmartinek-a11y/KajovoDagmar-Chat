from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

DATABASE_DSN = os.environ["BACKUP_AGENT_DATABASE_DSN"]
STANZA = os.environ.get("PGBACKREST_STANZA", "kajovodagmar")
RESTORE_ROOT = Path("/var/lib/postgresql/restore-test")
POLL_SECONDS = 2
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def command(*arguments: str, timeout: int = 1800) -> str:
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout


def backrest_info() -> dict[str, Any]:
    data = json.loads(
        command("pgbackrest", f"--stanza={STANZA}", "info", "--output=json")
    )
    if not isinstance(data, list) or not data:
        raise RuntimeError("pgBackRest nevrátil stav stanza.")
    return data[0]


def backup_by_label(info: dict[str, Any], label: str | None) -> dict[str, Any]:
    backups = info.get("backup", [])
    if label:
        matching = [item for item in backups if item.get("label") == label]
    else:
        matching = backups[-1:]
    if not matching:
        raise RuntimeError("Požadovaná záloha není v repository dostupná.")
    return matching[-1]


def claim(connection: psycopg.Connection[Any]) -> dict[str, Any] | None:
    with connection.transaction():
        return connection.execute(
            """
            WITH candidate AS (
              SELECT id
              FROM background_job
              WHERE state = 'queued'
                AND available_at <= now()
                AND kind IN ('backup_create', 'backup_verify', 'backup_restore_test')
              ORDER BY priority, available_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE background_job AS job
            SET state = 'running',
                locked_at = now(),
                locked_by = 'backup-agent',
                attempts = attempts + 1,
                updated_at = now()
            FROM candidate
            WHERE job.id = candidate.id
            RETURNING job.id, job.kind, job.payload, job.attempts,
                      job.max_attempts, job.correlation_id
            """
        ).fetchone()


def append_audit(
    connection: psycopg.Connection[Any],
    *,
    event_type: str,
    result: str,
    target_id: UUID,
    correlation_id: str | None,
    details: dict[str, Any],
) -> None:
    previous = connection.execute(
        "SELECT event_hash FROM audit_event ORDER BY id DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else None
    occurred_at = datetime.now(UTC)
    canonical = json.dumps(
        {
            "occurred_at": occurred_at.isoformat(),
            "actor_type": "system",
            "actor_id": None,
            "session_id": None,
            "event_type": event_type,
            "target_type": "backup_record",
            "target_id": str(target_id),
            "result": result,
            "network_context": None,
            "correlation_id": correlation_id,
            "details": details,
            "previous_hash": previous_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    event_hash = hashlib.sha256(canonical.encode()).hexdigest()
    connection.execute(
        """
        INSERT INTO audit_event (
          occurred_at, actor_type, event_type, target_type, target_id, result,
          correlation_id, details, previous_hash, event_hash
        ) VALUES (%s, 'system', %s, 'backup_record', %s, %s, %s, %s, %s, %s)
        """,
        (
            occurred_at,
            event_type,
            target_id,
            result,
            correlation_id,
            json.dumps(details),
            previous_hash,
            event_hash,
        ),
    )


def create_backup(
    connection: psycopg.Connection[Any], record_id: UUID
) -> dict[str, Any]:
    record = connection.execute(
        "SELECT started_at, state FROM backup_record WHERE id = %s FOR UPDATE",
        (record_id,),
    ).fetchone()
    if record is None:
        raise RuntimeError("Záznam zálohy neexistuje.")
    connection.execute(
        "UPDATE backup_record SET state = 'running', error_code = NULL, updated_at = now() "
        "WHERE id = %s",
        (record_id,),
    )
    connection.commit()
    info = backrest_info()
    candidates = [
        item
        for item in info.get("backup", [])
        if datetime.fromtimestamp(item["timestamp"]["start"], UTC)
        >= record["started_at"] - timedelta(seconds=5)
    ]
    if candidates:
        backup = candidates[-1]
    else:
        command("pgbackrest", f"--stanza={STANZA}", "stanza-create")
        command("pgbackrest", f"--stanza={STANZA}", "--type=full", "backup")
        backup = backup_by_label(backrest_info(), None)
    command("pgbackrest", f"--stanza={STANZA}", "check")
    manifest = command(
        "pgbackrest",
        f"--stanza={STANZA}",
        f"--set={backup['label']}",
        "info",
        "--output=json",
    ).encode()
    digest = hashlib.sha256(manifest).hexdigest()
    connection.execute(
        """
        UPDATE backup_record
        SET state = 'completed', completed_at = now(), verified_at = now(),
            backup_label = %s, manifest_digest = %s, size_bytes = %s,
            error_code = NULL, version = version + 1, updated_at = now()
        WHERE id = %s
        """,
        (backup["label"], digest, backup["info"]["size"], record_id),
    )
    return {"label": backup["label"], "size_bytes": backup["info"]["size"]}


def verify_backup(
    connection: psycopg.Connection[Any], record_id: UUID
) -> dict[str, Any]:
    record = connection.execute(
        "SELECT backup_label FROM backup_record WHERE id = %s FOR UPDATE", (record_id,)
    ).fetchone()
    if record is None or not record["backup_label"]:
        raise RuntimeError("Záloha nemá dokončený identifikátor.")
    command("pgbackrest", f"--stanza={STANZA}", "check")
    backup_by_label(backrest_info(), record["backup_label"])
    connection.execute(
        "UPDATE backup_record SET state = 'completed', verified_at = now(), "
        "error_code = NULL, "
        "version = version + 1, updated_at = now() WHERE id = %s",
        (record_id,),
    )
    return {"label": record["backup_label"]}


def restore_test(
    connection: psycopg.Connection[Any], record_id: UUID
) -> dict[str, Any]:
    record = connection.execute(
        "SELECT backup_label FROM backup_record WHERE id = %s FOR UPDATE", (record_id,)
    ).fetchone()
    if record is None or not record["backup_label"]:
        raise RuntimeError("Záloha nemá dokončený identifikátor.")
    label = record["backup_label"]
    backup_by_label(backrest_info(), label)
    RESTORE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    for child in RESTORE_ROOT.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    command(
        "pgbackrest",
        f"--stanza={STANZA}",
        f"--set={label}",
        f"--pg1-path={RESTORE_ROOT}",
        "restore",
    )
    socket_dir = RESTORE_ROOT / "socket"
    socket_dir.mkdir(mode=0o700)
    started = False
    try:
        command(
            "pg_ctl",
            "-D",
            str(RESTORE_ROOT),
            "-l",
            "/tmp/kajovodagmar-restore-test-postgres.log",
            "-o",
            f"-p 55434 -k {socket_dir} -c listen_addresses=''",
            "-W",
            "start",
            timeout=30,
        )
        started = True
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            ready = subprocess.run(
                (
                    "pg_isready",
                    "-h",
                    str(socket_dir),
                    "-p",
                    "55434",
                    "-U",
                    "kajovodagmar",
                    "-d",
                    "kajovodagmar",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Obnovená databáze nebyla do 180 sekund připravena.")
        result = command(
            "psql",
            "-h",
            str(socket_dir),
            "-p",
            "55434",
            "-U",
            "kajovodagmar",
            "-d",
            "kajovodagmar",
            "-At",
            "-c",
            "SELECT specification_revision || ':' || state FROM system_instance "
            "WHERE singleton_key='primary'",
            timeout=60,
        ).strip()
        if not result.startswith("v0021:"):
            raise RuntimeError(
                "Obnovená databáze neprošla kontrolou identity instance."
            )
    finally:
        if started:
            command(
                "pg_ctl",
                "-D",
                str(RESTORE_ROOT),
                "-m",
                "fast",
                "-w",
                "stop",
                timeout=180,
            )
    connection.execute(
        "UPDATE backup_record SET state = 'completed', restore_tested_at = now(), "
        "error_code = NULL, "
        "version = version + 1, updated_at = now() WHERE id = %s",
        (record_id,),
    )
    return {"label": label, "instance": result}


def complete(
    connection: psycopg.Connection[Any],
    job: dict[str, Any],
    record_id: UUID,
    details: dict[str, Any],
) -> None:
    connection.execute(
        "UPDATE background_job SET state='completed', completed_at=now(), "
        "locked_at=NULL, locked_by=NULL, updated_at=now() WHERE id=%s",
        (job["id"],),
    )
    append_audit(
        connection,
        event_type=f"{job['kind']}.completed",
        result="success",
        target_id=record_id,
        correlation_id=job["correlation_id"],
        details=details,
    )
    connection.commit()


def fail(
    connection: psycopg.Connection[Any],
    job: dict[str, Any],
    record_id: UUID,
    error: Exception,
) -> None:
    code = error.__class__.__name__
    terminal = job["attempts"] >= job["max_attempts"]
    connection.execute(
        """
        UPDATE background_job
        SET state = %s, available_at = now() + (%s * interval '1 second'),
            locked_at = NULL, locked_by = NULL, last_error_code = %s, updated_at = now()
        WHERE id = %s
        """,
        (
            "failed" if terminal else "queued",
            min(3600, 2 ** job["attempts"] * 10),
            code,
            job["id"],
        ),
    )
    connection.execute(
        """
        UPDATE backup_record
        SET state = CASE
              WHEN %s = 'backup_create'
              THEN %s
              ELSE state
            END,
            error_code=%s, version=version+1, updated_at=now()
        WHERE id=%s
        """,
        (
            job["kind"],
            "failed" if terminal else "queued",
            code,
            record_id,
        ),
    )
    append_audit(
        connection,
        event_type=f"{job['kind']}.failed",
        result="failure",
        target_id=record_id,
        correlation_id=job["correlation_id"],
        details={"error_code": code, "terminal": terminal},
    )
    connection.commit()


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            with psycopg.connect(
                DATABASE_DSN, autocommit=False, row_factory=dict_row
            ) as connection:
                while running:
                    job = claim(connection)
                    if job is None:
                        time.sleep(POLL_SECONDS)
                        continue
                    record_id = UUID(job["payload"]["backup_record_id"])
                    try:
                        if job["kind"] == "backup_create":
                            details = create_backup(connection, record_id)
                        elif job["kind"] == "backup_verify":
                            details = verify_backup(connection, record_id)
                        else:
                            details = restore_test(connection, record_id)
                        complete(connection, job, record_id, details)
                    except Exception as error:
                        print(
                            json.dumps(
                                {
                                    "event": "backup_job_failed",
                                    "job_id": str(job["id"]),
                                    "kind": job["kind"],
                                    "error_code": error.__class__.__name__,
                                    "detail": str(error),
                                },
                                ensure_ascii=False,
                            ),
                            file=sys.stderr,
                            flush=True,
                        )
                        connection.rollback()
                        fail(connection, job, record_id, error)
        except psycopg.Error as error:
            print(
                json.dumps(
                    {
                        "event": "backup_agent_database_error",
                        "error_code": error.__class__.__name__,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
