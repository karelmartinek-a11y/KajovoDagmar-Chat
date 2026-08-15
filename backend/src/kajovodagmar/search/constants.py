from __future__ import annotations

SEARCH_VECTOR_DIMENSIONS = 1536


def validate_vector_dimensions(vector: list[float]) -> None:
    if len(vector) != SEARCH_VECTOR_DIMENSIONS:
        raise ValueError(
            f"Search vector must have {SEARCH_VECTOR_DIMENSIONS} dimensions, got {len(vector)}."
        )
