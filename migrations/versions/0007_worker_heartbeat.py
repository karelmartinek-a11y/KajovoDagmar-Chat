"""Store durable worker liveness heartbeats."""

revision = "0007_worker_heartbeat"
down_revision = "0006_conversation_request_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The canonical baseline creates this table from the SSOT models.
    pass


def downgrade() -> None:
    pass
