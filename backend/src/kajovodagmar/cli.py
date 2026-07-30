from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from pathlib import Path

import typer
from sqlalchemy import select

from kajovodagmar.config import get_settings
from kajovodagmar.db.models import SystemInstance
from kajovodagmar.db.session import Database
from kajovodagmar.security.crypto import generate_token, token_digest

app = typer.Typer(help="Provozní CLI KájovoDagmar")


@app.command("generate-root-key")
def generate_root_key() -> None:
    typer.echo(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))


@app.command("generate-initialization-secret")
def generate_initialization_secret() -> None:
    token = generate_token(24)
    typer.echo(
        json.dumps(
            {"secret": token, "digest": token_digest(token, "initialization")}, ensure_ascii=False
        )
    )


@app.command("bootstrap-instance")
def bootstrap_instance() -> None:
    async def run() -> None:
        settings = get_settings()
        db = Database(settings)
        try:
            async with db.session() as session:
                existing = await session.scalar(
                    select(SystemInstance)
                    .where(SystemInstance.singleton_key == "primary")
                    .with_for_update()
                )
                if existing:
                    typer.echo(json.dumps({"state": existing.state, "created": False}))
                    return
                row = SystemInstance(
                    singleton_key="primary",
                    state="uninitialized",
                    initialization_secret_digest=settings.initialization_secret_hash.get_secret_value(),
                    specification_revision="v0021",
                    schema_version="1.0.0",
                )
                session.add(row)
                typer.echo(json.dumps({"state": "uninitialized", "created": True}))
        finally:
            await db.dispose()

    asyncio.run(run())


@app.command("integrity-check")
def integrity_check() -> None:
    async def run() -> None:
        from sqlalchemy import text

        settings = get_settings()
        db = Database(settings)
        try:
            async with db.session() as session:
                version = await session.scalar(text("SHOW server_version"))
                vector = await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                )
                typer.echo(
                    json.dumps(
                        {
                            "database": "ok",
                            "postgresql": version,
                            "pgvector": vector,
                            "specification": "v0021",
                        }
                    )
                )
        finally:
            await db.dispose()

    asyncio.run(run())


@app.command("hash-file")
def hash_file(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    typer.echo(digest)


if __name__ == "__main__":
    app()
