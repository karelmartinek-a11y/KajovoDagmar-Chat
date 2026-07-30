from __future__ import annotations
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
excluded = {
    "KajovoDagmar_SSOT_v0021.docx",
    "docs_ssot_extracted.txt",
    "check_forbidden.py",
    "requirements.json",
}
patterns = {
    "unfinished_marker": re.compile(r"\b(?:T[O]DO|F[I]XME|N[O]TIMPLEMENTED)\b", re.I),
    "empty_python_body": re.compile(
        r"^\s*(?:async\s+)?def\s+\w+\([^\n]*\):\s*\n\s+pass\s*$", re.M
    ),
    "not_implemented_error": re.compile(r"NotImplementedError"),
    "fake_runtime": re.compile(
        r"\b(?:mock|demo|fake)[_-]?(?:provider|runtime|response)\b", re.I
    ),
}
violations = []
for path in root.rglob("*"):
    if (
        not path.is_file()
        or path.name in excluded
        or any(
            part
            in {
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                "coverage",
                "node_modules",
                "dist",
                ".venv",
                "runtime",
            }
            for part in path.parts
        )
    ):
        continue
    if path.suffix.lower() not in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".sh",
        ".toml",
        ".ini",
        ".css",
        ".html",
        ".mako",
        "",
    }:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for label, pattern in patterns.items():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(root)}:{line}: {label}")
if violations:
    print("\n".join(violations))
    raise SystemExit(1)
print("Zakázané neimplementované konstrukce nebyly nalezeny.")
