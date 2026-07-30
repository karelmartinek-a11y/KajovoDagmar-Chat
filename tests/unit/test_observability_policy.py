from __future__ import annotations

import json
from pathlib import Path

from prometheus_client import REGISTRY


def test_slo_catalog_references_exported_bounded_metrics() -> None:
    catalog = json.loads(
        Path("deployment/observability/slo.json").read_text(encoding="utf-8")
    )
    assert catalog["window_days"] == 30
    assert {item["id"] for item in catalog["services"]} == {
        "http-availability",
        "http-latency",
        "voice-first-response",
    }
    exported = {family.name for family in REGISTRY.collect()}
    assert {
        "kajovodagmar_http_requests",
        "kajovodagmar_http_request_duration_seconds",
        "kajovodagmar_speech_first_audio_seconds",
    } <= exported
    for service in catalog["services"]:
        assert 0 < service["objective"] < 1
        query = service.get("promql_error_ratio") or service.get("promql_success_ratio")
        assert query.startswith("sum(rate(kajovodagmar_")
        assert "conversation_id" not in query
        assert "account_id" not in query


def test_alert_rules_have_severity_runbook_and_no_private_labels() -> None:
    rules = Path("deployment/observability/prometheus-rules.yaml").read_text(
        encoding="utf-8"
    )
    assert rules.count("- alert: KajovoDagmar") == 5
    assert rules.count("severity:") == 5
    assert rules.count("runbook:") == 5
    for forbidden in ["conversation_id", "account_id", "transcript", "content"]:
        assert forbidden not in rules
