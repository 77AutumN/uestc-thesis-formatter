"""Smoke tests for Phase 0 issue schema loader + validator.

Lightweight: pure pytest, hits the real ``references/issue_contracts/``
shipped in this repo (the 3 Day-3 contracts). Adds synthetic instances
to cover the validator branches.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Resolve scripts/ on path without depending on package install
_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import audit_issue_schema as ais  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: minimum-valid instance for each P0 contract Day 3 ships
# ---------------------------------------------------------------------------


def _valid_large_gap_instance():
    return {
        "schema_version": "0.1",
        "issue_id": "VIS-GAP-0001",
        "issue_code": "large_vertical_gap",
        "severity": "P0",
        "confidence": 0.95,
        "risk_class": "B",
        "repairability": "deterministic",
        "source": {"audit": "visual_geometry_audit", "check": "gap_between_blocks"},
        "location": {"pdf_page": 9},
        "evidence": {
            "gap_pt": 103.4, "threshold_pt": 50,
            "prev_block_text": "...", "next_block_text": "图1-2 LoRA低秩分解示意图",
        },
        "suggested_repair": {"repairer": "float_policy_repair", "strategy": "global_htbp_floatbarrier"},
    }


def _valid_split_page_instance():
    return {
        "schema_version": "0.1",
        "issue_id": "VIS-SPLIT-0001",
        "issue_code": "image_caption_split_page",
        "severity": "P0",
        "confidence": 0.97,
        "risk_class": "B",
        "repairability": "deterministic",
        "source": {"audit": "visual_geometry_audit"},
        "location": {"pdf_page": 47},
        "evidence": {
            "image_page": 47, "caption_page": 48,
            "caption_text": "图4-7 重复 caption", "image_filename": "media/image21.png",
        },
    }


def _valid_orphan_heading_instance():
    return {
        "schema_version": "0.1",
        "issue_id": "VIS-ORPH-0001",
        "issue_code": "orphan_heading_at_page_bottom",
        "severity": "P0",
        "risk_class": "B",
        "repairability": "deterministic",
        "source": {"audit": "visual_geometry_audit"},
        "location": {"pdf_page": 12},
        "evidence": {
            "heading_text": "1.2.2 LoRA微调", "heading_level": 3,
            "body_lines_following": 0,
            "page_bottom_y": 800.0, "heading_y": 780.0,
        },
    }


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_load_all_contracts_finds_phase0_batch():
    contracts = ais.load_all_contracts()
    # First batch (Day 3)
    assert "large_vertical_gap" in contracts
    assert "image_caption_split_page" in contracts
    assert "orphan_heading_at_page_bottom" in contracts
    # Second batch (Day 4)
    assert "caption_not_centered" in contracts
    assert "equation_tag_missing" in contracts
    assert "duplicate_figure" in contracts
    assert "header_chapter_mismatch" in contracts


def test_diagnostic_repairability_is_valid_enum():
    """Day 4: drift / observation-only issues use 'diagnostic' repairability."""
    assert "diagnostic" in ais.VALID_REPAIRABILITIES


def test_validate_diagnostic_repairability_instance():
    """Synthesise a hypothetical pdf_baseline_drift_high contract on the fly,
    verify a diagnostic instance passes validation."""
    contract = ais.Contract(
        issue_code="pdf_baseline_drift_high",
        schema_version="0.1",
        severity="P1",
        risk_class="B",
        repairability="diagnostic",
        required_evidence=["fraction_changed"],
        required_location=["pdf_page"],
        allowed_repairers=[],   # diagnostic → no repairer
        source_audits=["visual_pdf_diff"],
    )
    instance = {
        "schema_version": "0.1",
        "issue_id": "PDF-DRIFT-CASE-X-007",
        "issue_code": "pdf_baseline_drift_high",
        "severity": "P1",
        "risk_class": "B",
        "repairability": "diagnostic",
        "source": {"audit": "visual_pdf_diff"},
        "location": {"pdf_page": 7},
        "evidence": {"fraction_changed": 0.157},
    }
    errors = ais.validate_instance(instance, contract)
    assert errors == [], f"expected zero errors, got {[str(e) for e in errors]}"


def test_second_batch_contracts_have_consistent_severity():
    contracts = ais.load_all_contracts()
    # Per Day 4 design: caption_not_centered starts at P1, others P0
    assert contracts["caption_not_centered"].severity == "P1"
    assert contracts["equation_tag_missing"].severity == "P0"
    assert contracts["duplicate_figure"].severity == "P0"
    assert contracts["header_chapter_mismatch"].severity == "P0"
    # All B-class (structure/format, not customer content)
    for code in ["caption_not_centered", "equation_tag_missing",
                 "duplicate_figure", "header_chapter_mismatch"]:
        assert contracts[code].risk_class == "B"


def test_load_contract_round_trip():
    c = ais.load_contract("large_vertical_gap")
    assert c.issue_code == "large_vertical_gap"
    assert c.severity == "P0"
    assert c.risk_class == "B"
    assert c.repairability == "deterministic"
    assert "gap_pt" in c.required_evidence
    assert "pdf_page" in c.required_location
    assert "float_policy_repair" in c.allowed_repairers


def test_load_contract_unknown_raises():
    with pytest.raises(FileNotFoundError):
        ais.load_contract("does_not_exist_xyz")


# ---------------------------------------------------------------------------
# Validator: happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("instance_factory", [
    _valid_large_gap_instance,
    _valid_split_page_instance,
    _valid_orphan_heading_instance,
])
def test_valid_instance_passes(instance_factory):
    inst = instance_factory()
    contract = ais.load_contract(inst["issue_code"])
    errors = ais.validate_instance(inst, contract)
    assert errors == [], f"expected zero errors, got {[str(e) for e in errors]}"


def test_validate_collection_mixed_results():
    contracts = ais.load_all_contracts()
    instances = [
        _valid_large_gap_instance(),
        {"issue_code": "no_such_code_in_contracts", "issue_id": "X-1"},
        _valid_split_page_instance(),
    ]
    results = ais.validate_instances(instances, contracts)
    assert len(results) == 3
    assert results[0]["errors"] == []
    assert any("no_contract" in e for e in results[1]["errors"])
    assert results[2]["errors"] == []


# ---------------------------------------------------------------------------
# Validator: failure paths
# ---------------------------------------------------------------------------


def test_missing_required_evidence_field():
    inst = _valid_large_gap_instance()
    del inst["evidence"]["gap_pt"]
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "evidence.gap_pt" and e.code == "missing_field"
               for e in errors)


def test_missing_required_location_field():
    inst = _valid_large_gap_instance()
    del inst["location"]["pdf_page"]
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "location.pdf_page" and e.code == "missing_field"
               for e in errors)


def test_severity_must_be_p0_p1_p2():
    inst = _valid_large_gap_instance()
    inst["severity"] = "P3"  # invalid
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "severity" and e.code == "bad_enum" for e in errors)


def test_issue_code_mismatch():
    inst = _valid_large_gap_instance()
    inst["issue_code"] = "image_caption_split_page"
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.code == "code_mismatch" for e in errors)


def test_repairer_not_in_allowed_list():
    inst = _valid_large_gap_instance()
    inst["suggested_repair"] = {"repairer": "totally_made_up_repair"}
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "suggested_repair.repairer" and e.code == "not_allowed"
               for e in errors)


def test_confidence_out_of_range():
    inst = _valid_large_gap_instance()
    inst["confidence"] = 1.7
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "confidence" and e.code == "out_of_range"
               for e in errors)


def test_top_level_required_field_missing():
    inst = _valid_large_gap_instance()
    del inst["source"]
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance(inst, c)
    assert any(e.field_path == "source" and e.code == "missing_field" for e in errors)


def test_non_dict_instance_returns_root_error():
    c = ais.load_contract("large_vertical_gap")
    errors = ais.validate_instance("not a dict", c)
    assert len(errors) == 1
    assert errors[0].code == "wrong_type"
