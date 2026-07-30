"""Record the setting-history schema included by the canonical baseline.

Revision ID: 0003_setting_history
Revises: 0002_search_audit
"""

from __future__ import annotations

from alembic import op

revision = "0003_setting_history"
down_revision = "0002_search_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO schema_migration (revision, checksum, application_version)
        VALUES (
          '0003_setting_history',
          '7b845ff50867027983b4de6aa8c04f4b2777f933669d89d39e2e08a5147bb807',
          '1.0.0'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM schema_migration WHERE revision = '0003_setting_history'")
