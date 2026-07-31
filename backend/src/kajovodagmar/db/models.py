from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from kajovodagmar.db.base import Base


class TimestampVersionMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class SystemInstance(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "system_instance"
    singleton_key: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, default="primary"
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="uninitialized")
    specification_revision: Mapped[str] = mapped_column(String(32), nullable=False, default="v0021")
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initialization_secret_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    initialization_secret_consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")


class AdministratorAccount(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "administrator_account"
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, default="Karmar78"
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    restricted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdministratorProfile(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "administrator_profile"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Karel")
    email: Mapped[str | None] = mapped_column(String(320))
    pending_email: Mapped[str | None] = mapped_column(String(320))
    email_state: Mapped[str] = mapped_column(String(40), nullable=False, default="not_set")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="cs-CZ")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Prague")


class AccountCredential(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "account_credential"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="argon2id")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "auth_session"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    secret_digest: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(80))
    network_prefix: Mapped[str | None] = mapped_column(String(128))
    user_agent_summary: Mapped[str | None] = mapped_column(String(200))
    device_label: Mapped[str | None] = mapped_column(String(160))
    active_voice_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    __table_args__ = (
        Index("ix_auth_session_account_active", "account_id", "revoked_at", "expires_at"),
    )


class SecurityToken(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "security_token"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(48), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    target_digest: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProviderConfiguration(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "provider_configuration"
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="not_verified"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_state: Mapped[str] = mapped_column(String(40), nullable=False, default="not_loaded")
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    secret_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("encrypted_secret.id", ondelete="SET NULL")
    )
    __table_args__ = (UniqueConstraint("provider_type", "display_name"),)


class EncryptedSecret(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "encrypted_secret"
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    masked_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationSetting(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "application_setting"
    area: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    effect_boundary: Mapped[str] = mapped_column(String(40), nullable=False, default="immediate")
    changed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="SET NULL")
    )
    __table_args__ = (UniqueConstraint("area", "key"),)


class ApplicationSettingRevision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "application_setting_revision"
    setting_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_setting.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    effect_boundary: Mapped[str] = mapped_column(String(40), nullable=False)
    changed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (
        UniqueConstraint("setting_id", "revision_number"),
        Index("ix_setting_revision_history", "setting_id", "revision_number"),
    )


class ModelCatalogEntry(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "model_catalog_entry"
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configuration.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(48), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (UniqueConstraint("provider_id", "external_id", "role"),)


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "conversation"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    input_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="voice")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="cs")
    title: Mapped[str | None] = mapped_column(String(240))
    title_source: Mapped[str] = mapped_column(String(24), nullable=False, default="automatic")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_source: Mapped[str] = mapped_column(String(24), nullable=False, default="automatic")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    end_reason: Mapped[str | None] = mapped_column(String(80))
    continuation_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_summary: Mapped[str | None] = mapped_column(Text)
    context_summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (Index("ix_conversation_account_activity", "account_id", "last_activity_at"),)


class ConversationMessage(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "conversation_message"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    input_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="final")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    response_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audio_played_until_ms: Mapped[int | None] = mapped_column(Integer)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_message_conversation_sequence",
        ),
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_conversation_message_conversation_idempotency",
        ),
        CheckConstraint("sequence > 0", name="message_sequence_positive"),
    )


class OrchestrationRun(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "orchestration_run"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    source_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_message.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    response_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_message.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    intent: Mapped[str | None] = mapped_column(String(64))
    orchestration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_configuration.id", ondelete="SET NULL")
    )
    model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_catalog_entry.id", ondelete="SET NULL")
    )
    context_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        Index("ix_orchestration_conversation_started", "conversation_id", "started_at"),
    )


class OrchestrationAttempt(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "orchestration_attempt"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_run.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configuration.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_catalog_entry.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("run_id", "attempt_number"),)


class ToolAction(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "tool_action"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_run.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expected_target_version: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (Index("ix_tool_action_run_state", "run_id", "state"),)


class MessageRevision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "message_revision"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_message.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    revised_content: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="RESTRICT"), nullable=False
    )
    __table_args__ = (UniqueConstraint("message_id", "revision_number"),)


class ConversationLink(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "conversation_link"
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation"),)


class ConversationSummary(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "conversation_summary"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (UniqueConstraint("conversation_id", "revision_number"),)


class MemoryItem(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "memory_item"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_confirmation")
    origin_type: Mapped[str] = mapped_column(String(40), nullable=False)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_expression: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, default=list)
    merged_into_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_item.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_memory_account_state", "account_id", "state"),)


class MemoryVersion(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "memory_version"
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_item.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    change_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    changed_by: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (UniqueConstraint("memory_id", "version_number"),)


class MemorySource(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "memory_source"
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_item.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_message.id", ondelete="SET NULL")
    )
    manual_reference: Mapped[str | None] = mapped_column(String(240))
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SearchDocument(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "search_document"
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_vector: Mapped[Any] = mapped_column(TSVECTOR)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="czech")
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id"),
        Index("ix_search_document_vector", "text_vector", postgresql_using="gin"),
    )


class SearchEmbedding(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "search_embedding"
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("search_document.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Alembic converts this to vector(1536). Text keeps metadata importable
    # without requiring the pgvector Python package.
    vector_data: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "model_id", "source_hash"),)


class IdempotencyRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "idempotency_record"
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("scope", "key"),)


class BackgroundJob(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "background_job"
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (Index("ix_background_job_claim", "state", "available_at", "priority"),)


class OutboxEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_event"
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        UniqueConstraint("aggregate_type", "aggregate_id", "sequence"),
        Index("ix_outbox_unpublished", "published_at", "created_at"),
    )


class NotificationDelivery(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "notification_delivery"
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    safe_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    network_context: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (Index("ix_audit_time_type", "occurred_at", "event_type"),)


class BackupRecord(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "backup_record"
    backup_type: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repository_name: Mapped[str] = mapped_column(String(120), nullable=False)
    stanza: Mapped[str] = mapped_column(String(80), nullable=False)
    backup_label: Mapped[str | None] = mapped_column(String(200))
    manifest_digest: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(100))


class ExportRecord(Base, UUIDPrimaryKeyMixin, TimestampVersionMixin):
    __tablename__ = "export_record"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrator_account.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(512))
    file_digest: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class SchemaMigration(Base):
    __tablename__ = "schema_migration"
    revision: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    application_version: Mapped[str] = mapped_column(String(32), nullable=False)
