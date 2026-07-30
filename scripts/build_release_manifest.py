from __future__ import annotations
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(args: list[str], default: str) -> str:
    p = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    return p.stdout.strip() if p.returncode == 0 else default


image = os.getenv("APP_IMAGE_DIGEST", "")
if not image.startswith("sha256:") or len(image) != 71:
    raise SystemExit("APP_IMAGE_DIGEST s neměnným SHA-256 digestem je povinný.")
evidence = root / "release/evidence/generated"
artifacts = [
    {"name": str(p.relative_to(root)), "sha256": sha(p)}
    for p in sorted(evidence.rglob("*"))
    if p.is_file()
]
checks = json.loads((evidence / "release-check-results.json").read_text())
manifest = {
    "schema_version": "1.0.0",
    "version": os.getenv("RELEASE_VERSION", "1.0.0"),
    "commit": git(["rev-parse", "HEAD"], "uncommitted-source"),
    "ssot_sha256": json.loads((root / "GENERATION_MANIFEST.json").read_text())[
        "source"
    ]["sha256"],
    "image_digest": image,
    "database_schema": "0004_orchestration_actions",
    "artifacts": artifacts,
    "checks": checks,
    "created_at": datetime.now(timezone.utc).isoformat(),
}
(root / "release/RELEASE_MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
)
