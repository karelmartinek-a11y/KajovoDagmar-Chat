from __future__ import annotations

import pytest

from kajovodagmar.settings.catalog import BY_KEY, validate_value


def test_session_idle_range() -> None:
    definition = BY_KEY[("security", "session_idle_minutes")]
    assert validate_value(definition, 30) == 30
    with pytest.raises(ValueError):
        validate_value(definition, 9)
    with pytest.raises(ValueError):
        validate_value(definition, 121)


def test_model_roles_are_explicit_and_unconfigured_by_default() -> None:
    for key in [
        "conversation_model",
        "transcription_model",
        "speech_model",
        "summary_model",
        "embedding_model",
    ]:
        definition = BY_KEY[("models", key)]
        assert definition.default == ""
