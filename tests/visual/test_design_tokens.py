from pathlib import Path


def test_single_font_and_design_token_source() -> None:
    tokens = Path("web/src/styles/tokens.css").read_text()
    source = "\n".join(path.read_text() for path in Path("web/src").rglob("*.css"))
    assert "'Montserrat'" in tokens
    assert "font-family" not in source.replace(tokens, "")
