"""Add the request hash used for message idempotency checks."""

from __future__ import annotations

from alembic import op

revision = "0011_add_message_request_hash"
down_revision = "0010_create_worker_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The earlier compatibility revision was a no-op on legacy databases.
    # Keep this repair safe for installations that already have the column.
    op.execute(
        "ALTER TABLE conversation_message ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversation_message DROP COLUMN IF EXISTS request_hash")
