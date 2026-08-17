"""Ensure existing installations have a usable default speech voice."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0012_seed_default_voice"
down_revision = "0011_add_message_request_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not overwrite an explicit user choice. This repairs databases created
    # before the voice setting was persisted, so realtime synthesis can use the
    # same default shown by the frontend.
    op.get_bind().execute(
        text(
            """
            INSERT INTO application_setting
                (id, area, key, value, schema_version, effect_boundary, changed_by)
            SELECT gen_random_uuid(), 'voice', 'voice_id', '{"value": "marin"}'::jsonb,
                   '1.0.0', 'immediate', NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM application_setting
                WHERE area = 'voice' AND key = 'voice_id'
            )
            """
        )
    )


def downgrade() -> None:
    # The row may have been changed by an administrator after migration; never
    # delete a live user setting during downgrade.
    pass
