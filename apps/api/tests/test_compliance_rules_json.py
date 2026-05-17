"""Sanity checks on the externalized compliance rule set."""

import json
from pathlib import Path

from app.services.compliance import CHECKS, RULES_FILE, load_rules, run_all
from tests.factories import ZONES_FULL, make_component, make_connection, make_result
from app.services.classifier import classify_flows


def test_rules_json_exists_and_parses():
    assert RULES_FILE.exists(), "compliance_rules.json must ship with the package"
    data = json.loads(RULES_FILE.read_text())
    assert "rules" in data
    assert len(data["rules"]) >= 1


def test_every_rule_references_a_known_check():
    rules = load_rules()
    for r in rules:
        assert r["check"] in CHECKS, f"Rule {r['id']!r} uses unknown check {r['check']!r}"


def test_every_rule_has_required_fields():
    rules = load_rules()
    required = {"id", "title", "severity", "check"}
    for r in rules:
        missing = required - set(r.keys())
        assert not missing, f"Rule {r.get('id')} missing fields {missing}"


def test_disabled_rules_are_skipped(tmp_path: Path, monkeypatch):
    # Swap the rules file with a single disabled rule and verify it's skipped
    fake = tmp_path / "rules.json"
    fake.write_text(json.dumps({
        "version": 1,
        "rules": [
            {
                "id": "TEST_DISABLED",
                "title": "Disabled rule",
                "enabled": False,
                "severity": "info",
                "check": "at_least_one_component_of_type",
                "params": {"required_service_types": ["identity"]},
                "pass_message": "should never appear",
                "fail_message": "should never appear",
            },
            {
                "id": "TEST_ENABLED",
                "title": "Enabled rule",
                "enabled": True,
                "severity": "low",
                "fail_status": "warn",
                "check": "at_least_one_component_of_type",
                "params": {"required_service_types": ["identity"]},
                "pass_message": "ok",
                "fail_message": "missing identity",
            }
        ],
    }))
    monkeypatch.setattr("app.services.compliance.RULES_FILE", fake)
    # bust the lru_cache
    from app.services.compliance import _load_rules_cached
    _load_rules_cached.cache_clear()

    result = classify_flows(make_result(
        components=[make_component("a", "App", "compute_vm", trust_zone="tz-int")],
        connections=[],
        trust_zones=ZONES_FULL,
    ))
    findings = run_all(result)
    rule_ids = [f.rule for f in findings]
    assert "TEST_DISABLED" not in rule_ids
    assert "TEST_ENABLED" in rule_ids


def test_unknown_check_yields_not_applicable(tmp_path: Path, monkeypatch):
    fake = tmp_path / "rules.json"
    fake.write_text(json.dumps({
        "version": 1,
        "rules": [{
            "id": "TEST_BAD_CHECK",
            "title": "Bad check",
            "enabled": True,
            "severity": "low",
            "check": "does_not_exist",
            "params": {},
        }],
    }))
    monkeypatch.setattr("app.services.compliance.RULES_FILE", fake)
    from app.services.compliance import _load_rules_cached
    _load_rules_cached.cache_clear()

    result = classify_flows(make_result([], [], ZONES_FULL))
    findings = run_all(result)
    assert findings[0].rule == "TEST_BAD_CHECK"
    assert findings[0].status == "not_applicable"
    assert "Unknown check" in findings[0].message
