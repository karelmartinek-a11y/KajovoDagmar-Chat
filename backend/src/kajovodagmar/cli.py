from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import sys
from pathlib import Path

import typer
from sqlalchemy import select

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.config import get_settings
from kajovodagmar.db.models import (
    ApplicationSetting,
    ModelCatalogEntry,
    ProviderConfiguration,
    SystemInstance,
)
from kajovodagmar.db.session import Database
from kajovodagmar.errors import DomainError
from kajovodagmar.identity.service import IdentityService
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


@app.command("synchronize-deployment-password")
def synchronize_deployment_password() -> None:
    password = sys.stdin.read()

    async def run() -> None:
        settings = get_settings()
        db = Database(settings)
        try:
            async with db.session() as session:
                synchronized = await IdentityService(
                    AuditService()
                ).synchronize_deployment_password(
                    session,
                    password,
                    AuditContext("deployment", correlation_id="github-actions-production"),
                )
                typer.echo(
                    json.dumps(
                        {
                            "synchronized": synchronized,
                            "reason": None if synchronized else "account_not_initialized",
                        }
                    )
                )
        finally:
            await db.dispose()

    try:
        asyncio.run(run())
    except DomainError as exc:
        # This command is called with stdout redirected to protected deployment
        # evidence.  Return a machine-readable, secret-free failure so CI can
        # identify the failed gate without printing the supplied password.
        typer.echo(
            json.dumps(
                {
                    "synchronized": False,
                    "reason": exc.code,
                    "message": exc.message,
                },
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=1) from exc


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


@app.command("diagnostics-voice-live-probe")
def diagnostics_voice_live_probe() -> None:  # pragma: no cover - subprocess entrypoint
    """Run redacted live provider probes using the server-side encrypted configuration."""
    from kajovodagmar.diagnostics.voice_live_probe import main

    raise typer.Exit(main())


@app.command("voice-forensics")
def voice_forensics() -> None:  # pragma: no cover - subprocess entrypoint
    """Run the real realtime voice path with synthetic PCM, without a microphone."""
    from kajovodagmar.diagnostics.voice_forensics import main

    raise typer.Exit(main())


@app.command("acceptance-seed-provider")
def acceptance_seed_provider() -> None:  # pragma: no cover - subprocess entrypoint
    """Seed only the deterministic provider in a test database."""

    async def run() -> None:
        settings = get_settings()
        if settings.environment != "test":
            raise RuntimeError(
                "Deterministický provider lze seedovat pouze v testovacím prostředí."
            )
        db = Database(settings)
        try:
            async with db.session() as session:
                provider = await session.scalar(
                    select(ProviderConfiguration).where(
                        ProviderConfiguration.provider_type == "deterministic"
                    )
                )
                if provider is None:
                    provider = ProviderConfiguration(
                        provider_type="deterministic",
                        display_name="Isolated synthetic acceptance provider",
                        base_url="http://synthetic.invalid",
                        enabled=True,
                        verification_state="verified",
                        catalog_state="ready",
                    )
                    session.add(provider)
                    await session.flush()
                for role, suffix, capabilities in (
                    (
                        "conversation_model",
                        "conversation",
                        {"responses": True, "structured_outputs": True, "chat": True},
                    ),
                    ("transcription_model", "transcription", {"transcriptions": True}),
                    ("speech_model", "speech", {"speech": True}),
                    ("embedding_model", "embedding", {"embeddings": True}),
                ):
                    external_id = f"synthetic-acceptance-{suffix}"
                    model = await session.scalar(
                        select(ModelCatalogEntry).where(
                            ModelCatalogEntry.provider_id == provider.id,
                            ModelCatalogEntry.external_id == external_id,
                            ModelCatalogEntry.role == role,
                        )
                    )
                    if model is None:
                        model = ModelCatalogEntry(
                            provider_id=provider.id,
                            external_id=external_id,
                            display_name=f"Synthetic {role}",
                            role=role,
                            capabilities=capabilities,
                            available=True,
                        )
                        session.add(model)
                        await session.flush()
                    setting = await session.scalar(
                        select(ApplicationSetting).where(
                            ApplicationSetting.area == "models", ApplicationSetting.key == role
                        )
                    )
                    if setting is None:
                        session.add(
                            ApplicationSetting(
                                area="models",
                                key=role,
                                value={"value": str(model.id)},
                                effect_boundary="immediate",
                            )
                        )
                    else:
                        setting.value = {"value": str(model.id)}
                voice = await session.scalar(
                    select(ApplicationSetting).where(
                        ApplicationSetting.area == "voice", ApplicationSetting.key == "voice_id"
                    )
                )
                if voice is None:
                    session.add(
                        ApplicationSetting(
                            area="voice",
                            key="voice_id",
                            value={"value": "synthetic"},
                            effect_boundary="immediate",
                        )
                    )
        finally:
            await db.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    app()
