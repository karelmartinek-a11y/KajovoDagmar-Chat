from __future__ import annotations

import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).parents[2]
PRODUCTION = ROOT / "deployment" / "production"


def test_production_compose_is_isolated_on_loopback() -> None:
    source = (PRODUCTION / "compose.yaml").read_text()
    parsed = yaml.safe_load(source)
    assert parsed["services"]["caddy"]["profiles"] == ["embedded-edge"]
    assert parsed["services"]["web"]["ports"] == [
        "127.0.0.1:${APP_LOOPBACK_PORT:?Loopback port is required}:8000"
    ]
    assert parsed["services"]["web"]["networks"] == ["app", "edge"]
    assert "ports" not in parsed["services"]["db"]
    assert parsed["volumes"]["backup_repository"]["driver_opts"]["device"].startswith(
        "${BACKUP_REPOSITORY_DIR"
    )


def test_deployment_requires_exact_sha_and_protected_ssh() -> None:
    deploy = (PRODUCTION / "deploy-kajovodagmar-chat").read_text()
    assert re.search(r"\^\[0-9a-f\]\{40\}\$", deploy)
    assert "flock -n" in deploy
    assert "StrictHostKeyChecking=yes" in deploy
    assert "git pull" not in deploy
    assert " latest" not in deploy
    for required_gate in [
        "sbom-image.cdx.json",
        "grype-image.json",
        "jq -er",
        'docker tag "$app_image" "$vex_image"',
        'docker image inspect "$vex_image"',
        "pre-migration-backup.json",
        "alembic upgrade head",
        "internal-health.json",
        "public-health.json",
        "synchronize-deployment-password",
        "password-synchronization.json",
        "password_synchronization",
        "Deployment failed during stage",
        ".synchronized == true",
        "--retry-all-errors",
        "restore_previous_release",
    ]:
        assert required_gate in deploy


def test_production_workflow_is_post_release_and_secret_scoped() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = workflow["jobs"]["deploy-production"]
    assert job["needs"] == "release-gate"
    assert job["environment"] == {
        "name": "production",
        "url": "https://chat.hcasc.cz",
    }
    assert "github.event_name != 'pull_request'" in job["if"]
    deploy_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Deploy exact verified commit"
    )
    assert "${{ github.sha }}" in deploy_step["run"]
    assert "StrictHostKeyChecking=yes" in deploy_step["run"]
    assert deploy_step["env"]["PASS"] == "${{ secrets.PASS }}"
    assert "base64 --wrap=0 | ssh" in deploy_step["run"]
    voice_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Verify production login and voice chat"
    )
    assert voice_step["env"]["E2E_PASSWORD"] == "${{ secrets.PASS }}"
    assert voice_step["env"]["E2E_BASE_URL"] == "https://chat.hcasc.cz"
    assert "production-voice.spec.ts" in voice_step["run"]
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_nginx_vhost_is_domain_scoped_and_websocket_aware() -> None:
    nginx = (PRODUCTION / "chat.hcasc.cz.nginx.conf").read_text()
    assert nginx.count("server_name chat.hcasc.cz;") == 2
    assert "dagmar.hcasc.cz" not in nginx
    assert "proxy_pass http://127.0.0.1:18180;" in nginx
    assert "proxy_set_header Upgrade $http_upgrade;" in nginx
    assert "Strict-Transport-Security" in nginx
    assert 'add_header Cache-Control "private, no-store" always;' in nginx
