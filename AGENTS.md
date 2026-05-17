# AGENTS.md — AI-Native Entry Point

> This file is the **canonical AI entry point** for all AI IDEs and coding assistants
> working with this repository.

## 🔒 Bootstrap Rules (MANDATORY)

1. **Path Root**: All relative paths (`./`) in this project resolve from **this repository's root directory**.
2. **Single Source of Truth**: `./SKILL.md` is the **only** document containing pipeline architecture, rules, and anti-patterns. Read it in full before performing any operation.
3. **Thin Proxies**: `CLAUDE.md`, `.cursorrules`, and `.github/copilot-instructions.md` are routing stubs only. Do NOT add substantive rules to them.
4. **Configuration Authority**: `templates/<profile>/profile.json` is the sole configuration source. The `profiles/` directory has been permanently deleted. If you encounter any reference to `profiles/`, ignore it.
5. **Privacy Boundary**: This is a public OSS release. PII (real student names, student IDs, absolute Windows paths) is scrubbed by `tools/redact.py`. Internal case IDs collapse to `CASE-A`. The CI workflow `.github/workflows/redact-check.yml` blocks any PR that re-introduces PII patterns.

## Quick Start

```
# Process a thesis (example)
python scripts/run_v2.py thesis.docx --profile uestc

# Available profiles: uestc, uestc-bachelor, uestc-marxism, stem
```

## File Map

| Path | Purpose |
|------|---------|
| `./SKILL.md` | Full pipeline spec, anti-patterns, error triage |
| `scripts/run_v2.py` | Main pipeline orchestrator (Step -1 risk router → Step 6c product audit) |
| `scripts/hooks/` | Post-extraction hooks (profile-aware) |
| `scripts/validate_assembly.py` | Hard gate before compile (5-check suite) |
| `scripts/docx_surgery.py` | B-class structure repair toolkit (heading injection, pStyle relabel) |
| `scripts/product_audit.py` | Post-compile 14-check audit (media / citations / refs / subfigure parity) |
| `scripts/visual_geometry_audit.py` | PyMuPDF-based PDF geometry scan + synctex location |
| `scripts/compile.ps1` | Standalone Docker debug helper (NOT the primary compiler) |
| `templates/<profile>/profile.json` | Profile configuration (SOLE config source) |
| `templates/<profile>/checklist.md` | QA checklist per profile |
| `templates/failure-report.md` | Structured failure report template |
| `docs/defects/INDEX.md` | 50+ defect cards (sanitized), regenerable via `scripts/build_defect_index.py` |
| `docs/redaction-spec.md` | PII redaction rules (consumed by `tools/redact.py`) |
| `tools/redact.py` | PII gate (`--check` for CI, `--in-place` for local sync) |
| `vendor/DissertationUESTC/` | Upstream LaTeX template (git submodule) |
