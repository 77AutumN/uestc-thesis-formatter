"""Issue contract loader + instance validator (Phase 0 minimum closed loop).

A *contract* is a YAML file under ``references/issue_contracts/<issue_code>.yaml``
that declares the required shape of an audit-emitted *issue instance*.

Day 3 scope:
- Load contracts by ``issue_code``
- Validate a single issue instance dict against its contract
- Validate a collection (the JSON array a future ``audit_issues.json`` will hold)
- No deep schema (no JSON Schema / pydantic) — just stdlib + PyYAML

Failure mode: validator returns a list of ``ValidationError`` (no raise on
first failure). Empty list = valid. Caller decides what to do.

Compatibility goal: an instance produced by a *future* audit MUST still load
under a 0.1 validator if it carries ``schema_version: "0.1"`` and only added
optional keys. Removing required keys requires a contract major bump.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

def _default_contracts_dir() -> Path:
    """Path to the contract dir co-located with this script's skill repo.

    Layout assumption (stable across the skill):
      <skill_root>/scripts/audit_issue_schema.py
      <skill_root>/references/issue_contracts/*.yaml

    Resolved as ``Path(__file__).parent.parent / "references" / "issue_contracts"``.
    Note: deliberately uses the un-resolved ``__file__`` so a Windows junction
    on ``thesis/.agents`` (which points to ``Open claw/.agent`` in this
    checkout) does not warp us out of the project tree. ``.resolve()`` would
    follow the junction and break.

    The CLI's ``--contracts-dir`` flag overrides this for ad-hoc use.
    """
    return Path(__file__).parent.parent / "references" / "issue_contracts"


CONTRACTS_DIR = _default_contracts_dir()
SCHEMA_VERSION = "0.1"

VALID_SEVERITIES = {"P0", "P1", "P2"}
VALID_RISK_CLASSES = {"B", "C", "D"}
# repairability semantics:
#   deterministic - automatic fix is well-defined and safe to apply
#   trial         - tentative fix; rolled back if rerun audit doesn't pass
#   manual        - fix exists but a human must do it (e.g. C-class content)
#   diagnostic    - signal/observation only; no actionable repair (Day 4)
VALID_REPAIRABILITIES = {"deterministic", "trial", "manual", "diagnostic"}


@dataclass
class ValidationError:
    field_path: str        # dotted path, e.g. "evidence.gap_pt"
    code: str              # short token, e.g. "missing_field"
    message: str           # human-friendly reason

    def __str__(self):
        return f"[{self.code}] {self.field_path}: {self.message}"


@dataclass
class Contract:
    issue_code: str
    schema_version: str
    severity: str
    risk_class: str
    repairability: str
    required_evidence: List[str] = field(default_factory=list)
    required_location: List[str] = field(default_factory=list)
    allowed_repairers: List[str] = field(default_factory=list)
    source_audits: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contract":
        return cls(
            issue_code=data["issue_code"],
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            severity=data["severity"],
            risk_class=data["risk_class"],
            repairability=data["repairability"],
            required_evidence=list(data.get("required_evidence") or []),
            required_location=list(data.get("required_location") or []),
            allowed_repairers=list(data.get("allowed_repairers") or []),
            source_audits=list(data.get("source_audits") or []),
            raw=data,
        )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _resolve_contract_path(issue_code: str, contracts_dir: Optional[Path] = None) -> Path:
    base = Path(contracts_dir) if contracts_dir else CONTRACTS_DIR
    return base / f"{issue_code}.yaml"


def load_contract(issue_code: str, contracts_dir: Optional[Path] = None) -> Contract:
    """Load one contract by issue_code. Raises FileNotFoundError or ValueError."""
    path = _resolve_contract_path(issue_code, contracts_dir)
    if not path.is_file():
        raise FileNotFoundError(f"contract not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"contract {path} is not a YAML mapping")
    if data.get("issue_code") != issue_code:
        raise ValueError(
            f"contract {path} has issue_code={data.get('issue_code')!r}, "
            f"expected {issue_code!r}"
        )
    # Spot-check enum fields at load time (fail-fast for typos in YAML)
    if data.get("severity") not in VALID_SEVERITIES:
        raise ValueError(f"contract {issue_code}: severity={data.get('severity')!r} not in {VALID_SEVERITIES}")
    if data.get("risk_class") not in VALID_RISK_CLASSES:
        raise ValueError(f"contract {issue_code}: risk_class={data.get('risk_class')!r} not in {VALID_RISK_CLASSES}")
    if data.get("repairability") not in VALID_REPAIRABILITIES:
        raise ValueError(f"contract {issue_code}: repairability={data.get('repairability')!r} not in {VALID_REPAIRABILITIES}")
    return Contract.from_dict(data)


def load_all_contracts(contracts_dir: Optional[Path] = None) -> Dict[str, Contract]:
    base = Path(contracts_dir) if contracts_dir else CONTRACTS_DIR
    if not base.is_dir():
        return {}
    out: Dict[str, Contract] = {}
    for path in sorted(base.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict) or "issue_code" not in data:
            continue
        out[data["issue_code"]] = load_contract(data["issue_code"], contracts_dir=base)
    return out


# ---------------------------------------------------------------------------
# Instance validation
# ---------------------------------------------------------------------------

_INSTANCE_TOP_LEVEL_REQUIRED = {
    "schema_version", "issue_id", "issue_code",
    "severity", "risk_class", "repairability",
    "source", "location", "evidence",
}


def validate_instance(
    instance: Dict[str, Any],
    contract: Contract,
) -> List[ValidationError]:
    """Validate one issue instance against its contract.

    Returns a list of ValidationError (empty = valid). Never raises on
    instance-shape problems; only raises on programming errors (e.g. wrong
    type for ``contract``).
    """
    errors: List[ValidationError] = []

    if not isinstance(instance, dict):
        return [ValidationError("<root>", "wrong_type",
                                f"instance must be dict, got {type(instance).__name__}")]

    # Top-level required keys
    for key in _INSTANCE_TOP_LEVEL_REQUIRED:
        if key not in instance:
            errors.append(ValidationError(key, "missing_field",
                                          "required top-level field absent"))

    # issue_code must match contract
    if instance.get("issue_code") != contract.issue_code:
        errors.append(ValidationError(
            "issue_code", "code_mismatch",
            f"instance.issue_code={instance.get('issue_code')!r} but "
            f"contract.issue_code={contract.issue_code!r}"))

    # schema_version present and parseable
    sv = instance.get("schema_version")
    if sv is not None and not isinstance(sv, str):
        errors.append(ValidationError("schema_version", "wrong_type",
                                      f"must be str, got {type(sv).__name__}"))

    # Enum integrity (let instance override contract defaults but stay in enum)
    if instance.get("severity") not in VALID_SEVERITIES:
        errors.append(ValidationError(
            "severity", "bad_enum",
            f"{instance.get('severity')!r} not in {sorted(VALID_SEVERITIES)}"))
    if instance.get("risk_class") not in VALID_RISK_CLASSES:
        errors.append(ValidationError(
            "risk_class", "bad_enum",
            f"{instance.get('risk_class')!r} not in {sorted(VALID_RISK_CLASSES)}"))
    if instance.get("repairability") not in VALID_REPAIRABILITIES:
        errors.append(ValidationError(
            "repairability", "bad_enum",
            f"{instance.get('repairability')!r} not in {sorted(VALID_REPAIRABILITIES)}"))

    # confidence (optional but if present must be 0..1)
    conf = instance.get("confidence")
    if conf is not None:
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            errors.append(ValidationError("confidence", "out_of_range",
                                          f"{conf!r} must be a number in [0,1]"))

    # required_evidence
    evidence = instance.get("evidence") or {}
    if not isinstance(evidence, dict):
        errors.append(ValidationError("evidence", "wrong_type",
                                      f"must be dict, got {type(evidence).__name__}"))
    else:
        for fname in contract.required_evidence:
            if fname not in evidence:
                errors.append(ValidationError(f"evidence.{fname}", "missing_field",
                                              "required by contract"))

    # required_location
    location = instance.get("location") or {}
    if not isinstance(location, dict):
        errors.append(ValidationError("location", "wrong_type",
                                      f"must be dict, got {type(location).__name__}"))
    else:
        for fname in contract.required_location:
            if fname not in location:
                errors.append(ValidationError(f"location.{fname}", "missing_field",
                                              "required by contract"))

    # suggested_repair (optional) — if present, repairer must be in allow-list
    suggested = instance.get("suggested_repair") or {}
    if suggested and contract.allowed_repairers:
        repairer = suggested.get("repairer")
        if repairer is not None and repairer not in contract.allowed_repairers:
            errors.append(ValidationError(
                "suggested_repair.repairer", "not_allowed",
                f"{repairer!r} not in contract.allowed_repairers="
                f"{contract.allowed_repairers}"))

    # source.audit (optional, but if present must be in contract.source_audits when contract declares any)
    src = instance.get("source") or {}
    if isinstance(src, dict) and contract.source_audits:
        audit_name = src.get("audit")
        if audit_name is not None and audit_name not in contract.source_audits:
            errors.append(ValidationError(
                "source.audit", "not_allowed",
                f"{audit_name!r} not in contract.source_audits="
                f"{contract.source_audits}"))

    return errors


def validate_instances(
    instances: Iterable[Dict[str, Any]],
    contracts: Dict[str, Contract],
) -> List[Dict[str, Any]]:
    """Validate a collection. Returns list of {issue_id, issue_code, errors[]}."""
    out = []
    for inst in instances:
        if not isinstance(inst, dict):
            out.append({"issue_id": None, "issue_code": None,
                        "errors": [str(ValidationError("<root>", "wrong_type",
                                                       "instance is not a dict"))]})
            continue
        code = inst.get("issue_code")
        contract = contracts.get(code) if code else None
        if contract is None:
            out.append({"issue_id": inst.get("issue_id"), "issue_code": code,
                        "errors": [str(ValidationError("issue_code", "no_contract",
                                                       f"no loaded contract for {code!r}"))]})
            continue
        errs = validate_instance(inst, contract)
        out.append({
            "issue_id": inst.get("issue_id"),
            "issue_code": code,
            "errors": [str(e) for e in errs],
        })
    return out


# ---------------------------------------------------------------------------
# CLI: load + validate a JSON file of issue instances against contracts dir
# ---------------------------------------------------------------------------


def _cli(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Issue contract loader + instance validator (Phase 0)")
    p.add_argument("--instances", help="Path to a JSON array of issue instances")
    p.add_argument("--contracts-dir", default=str(CONTRACTS_DIR),
                   help="Directory of <issue_code>.yaml contracts")
    p.add_argument("--list-contracts", action="store_true",
                   help="Just list loaded contracts and exit")
    args = p.parse_args(argv)

    cdir = Path(args.contracts_dir)
    contracts = load_all_contracts(cdir)
    print(f"loaded {len(contracts)} contract(s) from {cdir}")
    for code, c in sorted(contracts.items()):
        print(f"  - {code}: severity={c.severity} risk_class={c.risk_class} "
              f"repairability={c.repairability}")
    if args.list_contracts:
        return 0

    if not args.instances:
        return 0

    inst_path = Path(args.instances)
    if not inst_path.is_file():
        print(f"instances file not found: {inst_path}")
        return 1
    payload = json.loads(inst_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        print("instances file must be a JSON array")
        return 1

    results = validate_instances(payload, contracts)
    bad = [r for r in results if r["errors"]]
    print(f"\nvalidated {len(results)} instance(s); {len(bad)} with errors")
    for r in results:
        tag = "OK" if not r["errors"] else "FAIL"
        print(f"  [{tag}] issue_id={r['issue_id']} code={r['issue_code']}")
        for e in r["errors"]:
            print(f"        - {e}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
