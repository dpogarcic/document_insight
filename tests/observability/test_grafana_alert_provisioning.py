"""Guard the Grafana-owned alert provisioning contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "observability/grafana/provisioning/alerting/document-insight-rules.json"
DASHBOARD_PATH = ROOT / "observability/grafana/provisioning/dashboards/document-insight-alerts.json"


def test_alert_rules_are_provisioned_in_grafana() -> None:
    """All operational rules should be Grafana-managed Prometheus queries."""
    provisioned = json.loads(RULES_PATH.read_text())
    groups = provisioned["groups"]
    assert len(groups) == 1
    rules = groups[0]["rules"]
    assert len(rules) == 18
    assert len({rule["uid"] for rule in rules}) == len(rules)
    assert all(rule["condition"] == "B" for rule in rules)
    assert all(rule["data"][0]["datasourceUid"] == "prometheus" for rule in rules)
    assert all(rule["data"][1]["datasourceUid"] == "__expr__" for rule in rules)
    assert all(rule["data"][1]["model"]["expression"] == "$A > 0" for rule in rules)
    assert all(rule["labels"]["severity"] in {"warning", "critical"} for rule in rules)
    expressions = {rule["title"]: rule["data"][0]["model"]["expr"] for rule in rules}
    assert (
        "absent(document_insight_ingestion_worker_last_heartbeat_unixtime)"
        in expressions["DocumentInsightWorkerHeartbeatStale"]
    )
    assert (
        "absent(document_insight_ingestion_reconciler_last_success_unixtime)"
        in expressions["DocumentInsightReconcilerStale"]
    )
    assert (
        "document_insight_processing_oldest_in_flight_age_seconds"
        in expressions["DocumentInsightProcessingStalled"]
    )


def test_alert_dashboard_uses_grafana_alert_list() -> None:
    """The dashboard must show Grafana alert state, not Prometheus ALERTS series."""
    dashboard = json.loads(DASHBOARD_PATH.read_text())
    assert dashboard["panels"][0]["type"] == "alertlist"
    assert "ALERTS{" not in DASHBOARD_PATH.read_text()
