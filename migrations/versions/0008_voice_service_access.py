"""Add the long-lived, revocable voice service key metadata and notices."""

from __future__ import annotations

from alembic import op

from kajovodagmar.db import models  # noqa: F401
from kajovodagmar.db.base import Base

revision = "0008_voice_service_access"
down_revision = "0007_worker_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[
            models.VoiceServiceApiKey.__table__,
            models.ServiceAccessNotice.__table__,
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    models.ServiceAccessNotice.__table__.drop(bind, checkfirst=True)
    models.VoiceServiceApiKey.__table__.drop(bind, checkfirst=True)
