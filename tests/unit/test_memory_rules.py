from kajovodagmar.memory.service import contains_secret_instruction


def test_secret_like_content_is_detected() -> None:
    assert contains_secret_instruction("Zapamatuj si moje heslo abc")
    assert contains_secret_instruction("API klíč je citlivý")


def test_normal_preference_is_not_secret() -> None:
    assert not contains_secret_instruction("Nemám rád česnek v jídle")
