"""Create the durable worker liveness heartbeat table."""

from __future__ import annotations

from alembic import op

from kajovodagmar.db import models

revision = "0010_create_worker_heartbeat"
down_revision = "0009_remove_general_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``0007`` was historically a compatibility no-op.  Use the model's
    # canonical table definition and checkfirst so this repairs older
    # installations without affecting databases where it already exists.
    models.WorkerHeartbeat.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    models.WorkerHeartbeat.__table__.drop(bind=op.get_bind(), checkfirst=True)
