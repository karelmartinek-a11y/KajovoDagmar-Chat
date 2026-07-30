"""Record the orchestration schema included by the canonical baseline.

Revision ID: 0004_orchestration_actions
Revises: 0003_setting_history
"""

from __future__ import annotations

from alembic import op

revision = "0004_orchestration_actions"
down_revision = "0003_setting_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO schema_migration (revision, checksum, application_version)
        VALUES (
          '0004_orchestration_actions',
          '61448bd715d0705471337825438569b73928134450609321137e874b53e53f24',
          '1.0.0'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM schema_migration WHERE revision = '0004_orchestration_actions'"
    )
