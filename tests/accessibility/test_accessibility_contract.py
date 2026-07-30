from pathlib import Path


def test_state_is_not_color_only() -> None:
    orb = Path("web/src/features/chat/Orb.tsx").read_text()
    chat = Path("web/src/features/chat/ChatPage.tsx").read_text()
    assert "aria-label" in orb
    assert "stateMessage" in chat
    assert "aria-live" in chat


def test_navigation_and_forms_have_accessible_names() -> None:
    source = "\n".join(path.read_text() for path in Path("web/src").rglob("*.tsx"))
    assert 'aria-label="Hlavní navigace"' in source
    assert "<label" in source
