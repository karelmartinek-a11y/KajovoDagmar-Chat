from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.db.models import ApplicationSetting, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import CapabilityUnavailableError
from kajovodagmar.providers.service import ProviderService


class HybridSearchService:
    def __init__(self, providers: ProviderService) -> None:
        self.providers = providers

    async def ranked_owner_ids(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        owner_type: str,
        query: str,
        limit: int,
    ) -> list[UUID]:
        normalized = query.strip()
        if not normalized:
            return []
        vector, model_id = await self._query_embedding(session, normalized)
        if vector is None or model_id is None:
            rows = await session.execute(
                text(
                    """
                    SELECT owner_id
                    FROM search_document
                    WHERE account_id = :account_id
                      AND owner_type = :owner_type
                      AND stale = false
                      AND text_vector @@ websearch_to_tsquery('simple', :query)
                    ORDER BY ts_rank_cd(text_vector, websearch_to_tsquery('simple', :query)) DESC,
                             owner_id ASC
                    LIMIT :limit
                    """
                ),
                {
                    "account_id": account_id,
                    "owner_type": owner_type,
                    "query": normalized,
                    "limit": limit,
                },
            )
            return [row.owner_id for row in rows]
        serialized = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
        rows = await session.execute(
            text(
                """
                WITH text_hits AS (
                    SELECT owner_id,
                           row_number() OVER (
                             ORDER BY ts_rank_cd(
                               text_vector,
                               websearch_to_tsquery('simple', :query)
                             ) DESC,
                                      owner_id ASC
                           ) AS rank_position
                    FROM search_document
                    WHERE account_id = :account_id
                      AND owner_type = :owner_type
                      AND stale = false
                      AND text_vector @@ websearch_to_tsquery('simple', :query)
                    LIMIT :candidate_limit
                ),
                semantic_hits AS (
                    SELECT sd.owner_id,
                           row_number() OVER (
                             ORDER BY se.vector_data <=> CAST(:vector AS vector), sd.owner_id ASC
                           ) AS rank_position
                    FROM search_document sd
                    JOIN search_embedding se ON se.document_id = sd.id
                    WHERE sd.account_id = :account_id
                      AND sd.owner_type = :owner_type
                      AND sd.stale = false
                      AND se.model_id = :model_id
                    LIMIT :candidate_limit
                ),
                fused AS (
                    SELECT owner_id, SUM(score) AS score
                    FROM (
                        SELECT owner_id, 1.0 / (60.0 + rank_position) AS score FROM text_hits
                        UNION ALL
                        SELECT owner_id, 1.0 / (60.0 + rank_position) AS score FROM semantic_hits
                    ) ranked
                    GROUP BY owner_id
                )
                SELECT owner_id
                FROM fused
                ORDER BY score DESC, owner_id ASC
                LIMIT :limit
                """
            ),
            {
                "account_id": account_id,
                "owner_type": owner_type,
                "query": normalized,
                "vector": serialized,
                "model_id": model_id,
                "candidate_limit": max(limit * 4, 40),
                "limit": limit,
            },
        )
        return [row.owner_id for row in rows]

    async def _query_embedding(
        self, session: AsyncSession, query: str
    ) -> tuple[list[float] | None, str | None]:
        setting = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == "models",
                ApplicationSetting.key == "embedding_model",
            )
        )
        if setting is None or not setting.value.get("value"):
            return None, None
        try:
            model_uuid = UUID(str(setting.value["value"]))
        except ValueError:
            return None, None
        model = await session.get(ModelCatalogEntry, model_uuid)
        if model is None or not model.available or not model.capabilities.get("embeddings", False):
            return None, None
        provider = await session.get(ProviderConfiguration, model.provider_id)
        if provider is None or not provider.enabled or provider.verification_state != "verified":
            return None, None
        try:
            runtime = await self.providers.runtime(session, provider)
            vectors = await runtime.embed([query], model=model.external_id)
        except CapabilityUnavailableError:
            return None, None
        if len(vectors) != 1 or not vectors[0]:
            return None, None
        return vectors[0], model.external_id
