from kajovodagmar.providers.model_roles import classify_model, recommendation_rank


def test_roles_are_exclusive_for_specialized_families() -> None:
    assert classify_model("gpt-4o-transcribe", "Transcribe", set()).roles == {
        "transcription_model"
    }
    assert classify_model("gpt-4o-mini-tts", "TTS", set()).roles == {"speech_model"}
    assert classify_model("text-embedding-3-large", "Embeddings", set()).roles == {
        "embedding_model"
    }
    assert classify_model("gpt-5-mini", "GPT-5 mini", set()).roles == {
        "conversation_model",
        "summary_model",
    }


def test_denylist_blocks_non_runtime_families() -> None:
    for model_id in (
        "gpt-4o-realtime-preview",
        "codex-mini",
        "sora-2",
        "omni-moderation-latest",
    ):
        assert not classify_model(model_id, model_id, {"chat"}).roles


def test_recommendation_rank_is_deterministic_and_snapshot_friendly() -> None:
    assert recommendation_rank("conversation_model", "gpt-5-mini")[0] == 0
    assert recommendation_rank("conversation_model", "gpt-5-mini-2026-01-01")[0] == 10
    assert recommendation_rank("conversation_model", "another-model")[0] == 1000
