"""Track verified catalog freshness and model-role policy metadata.

Revision ID: 0005_model_catalog_policy
Revises: 0004_orchestration_actions
"""

from alembic import op

revision = "0005_model_catalog_policy"
down_revision = "0004_orchestration_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE provider_configuration ADD COLUMN IF NOT EXISTS catalog_refreshed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE provider_configuration ADD COLUMN IF NOT EXISTS catalog_state VARCHAR(40) NOT NULL DEFAULT 'not_loaded'"
    )
    op.execute(
        """
        INSERT INTO schema_migration (revision, checksum, application_version)
        VALUES ('0005_model_catalog_policy', 'model-role-policy-v1', '1.0.0')
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM schema_migration WHERE revision = '0005_model_catalog_policy'"
    )
    op.execute("ALTER TABLE provider_configuration DROP COLUMN catalog_state")
    op.execute("ALTER TABLE provider_configuration DROP COLUMN catalog_refreshed_at")
