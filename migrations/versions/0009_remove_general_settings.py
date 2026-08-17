"""Remove the obsolete general settings area."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0009_remove_general_settings"
down_revision = "0008_voice_service_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            """
            DELETE FROM application_setting_revision
            WHERE setting_id IN (
                SELECT id FROM application_setting WHERE area = 'general'
            )
            """
        )
    )
    bind.execute(text("DELETE FROM application_setting WHERE area = 'general'"))


def downgrade() -> None:
    # Removed settings are intentionally not recreated; the application is Czech-only.
    pass
