"""Initial canonical schema for SSOT v0021.

Revision ID: 0001_initial_schema
Revises: None
"""

from __future__ import annotations

import os
from alembic import op
from sqlalchemy import text

from kajovodagmar.db.base import Base
from kajovodagmar.db import models  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    Base.metadata.create_all(bind=bind, checkfirst=False)
    digest = os.environ.get("KAJOVODAGMAR_INITIALIZATION_SECRET_HASH")
    if not digest:
        raise RuntimeError(
            "KAJOVODAGMAR_INITIALIZATION_SECRET_HASH je povinný pro bezpečnou první migraci."
        )
    bind.execute(
        text("""
        INSERT INTO system_instance
          (id,singleton_key,state,specification_revision,initialization_secret_digest,schema_version,created_at,updated_at,version)
        VALUES
          (gen_random_uuid(),'primary','uninitialized','v0021',:digest,'1.0.0',now(),now(),1)
    """),
        {"digest": digest},
    )
    bind.execute(
        text(
            "INSERT INTO schema_migration (revision,checksum,application_version) VALUES ('0001_initial_schema','7f4cba59e19e2134fd3326711070f84f21f71be147998a223b43678186d6cefa','1.0.0')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=False)
    op.execute("DROP EXTENSION IF EXISTS vector")
