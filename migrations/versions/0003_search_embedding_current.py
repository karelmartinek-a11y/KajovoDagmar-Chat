"""Enforce one current embedding per document and model.

Revision ID: 0003_search_embedding_current
Revises: 0002_search_audit
"""

from alembic import op

revision = "0003_search_embedding_current"
down_revision = "0002_search_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM search_embedding old
        USING search_embedding newer
        WHERE old.document_id = newer.document_id
          AND old.model_id = newer.model_id
          AND old.id <> newer.id
          AND (old.updated_at, old.id) < (newer.updated_at, newer.id)
    """)
    op.create_unique_constraint(
        "uq_search_embedding_document_model",
        "search_embedding",
        ["document_id", "model_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_search_embedding_document_model", "search_embedding", type_="unique"
    )
