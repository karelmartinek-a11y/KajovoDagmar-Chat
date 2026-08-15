"""Search vector, full-text maintenance and immutable audit guards.

Revision ID: 0002_search_audit
Revises: 0001_initial_schema
"""

from alembic import op

revision = "0002_search_audit"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TEXT SEARCH CONFIGURATION public.czech (COPY = pg_catalog.english)"
    )
    op.execute(
        "ALTER TABLE search_embedding ALTER COLUMN vector_data TYPE vector(1536) USING vector_data::vector"
    )
    op.execute(
        "CREATE INDEX ix_search_embedding_vector_hnsw ON search_embedding USING hnsw (vector_data vector_cosine_ops)"
    )
    op.execute("""
      CREATE OR REPLACE FUNCTION kajovodagmar_search_document_tsvector() RETURNS trigger AS $$
      BEGIN
        NEW.text_vector := to_tsvector(COALESCE(NEW.language,'czech')::regconfig, COALESCE(NEW.searchable_text,''));
        RETURN NEW;
      END
      $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_search_document_tsvector BEFORE INSERT OR UPDATE OF searchable_text,language ON search_document FOR EACH ROW EXECUTE FUNCTION kajovodagmar_search_document_tsvector()"
    )
    op.execute("UPDATE search_document SET searchable_text=searchable_text")
    op.execute("""
      CREATE OR REPLACE FUNCTION kajovodagmar_audit_immutable() RETURNS trigger AS $$
      BEGIN
        RAISE EXCEPTION 'audit_event is append-only';
      END
      $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_audit_event_no_update BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION kajovodagmar_audit_immutable()"
    )
    op.execute(
        "INSERT INTO schema_migration (revision,checksum,application_version) VALUES ('0002_search_audit','14c98eadc437fe4d6a51bb8c8f4c7cc47ad7a75fd0e68f81be3433a1730d39a9','1.0.0')"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_event_no_update ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS kajovodagmar_audit_immutable")
    op.execute("DROP TRIGGER IF EXISTS trg_search_document_tsvector ON search_document")
    op.execute("DROP FUNCTION IF EXISTS kajovodagmar_search_document_tsvector")
    op.execute("DROP INDEX IF EXISTS ix_search_embedding_vector_hnsw")
    op.execute(
        "ALTER TABLE search_embedding ALTER COLUMN vector_data TYPE text USING vector_data::text"
    )
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS public.czech")
    op.execute("DELETE FROM schema_migration WHERE revision='0002_search_audit'")
