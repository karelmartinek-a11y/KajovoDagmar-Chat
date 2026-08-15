"""Persist the canonical request hash for conversation idempotency."""

revision = "0006_conversation_request_hash"
down_revision = ("0005_model_catalog_policy", "0003_search_embedding_current")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The canonical baseline already contains this nullable compatibility column.
    # Keep this revision as the merge point for the pre-existing migration heads.
    pass


def downgrade() -> None:
    pass
