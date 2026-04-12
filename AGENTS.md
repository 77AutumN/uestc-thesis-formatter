# AGENTS.md — AI-Native Entry Point

> This file is the **canonical AI entry point** for all AI IDEs and coding assistants
> working with this repository.

## 🔒 Bootstrap Rules (MANDATORY)

1. **Path Root**: All relative paths (`./`) in this project resolve from **this repository's root directory**.
2. **Single Source of Truth**: `.agent/skills/thesis-formatter/SKILL.md` is the **only** document containing pipeline architecture, rules, and anti-patterns. Read it in full before performing any operation.
3. **Thin Proxies**: `CLAUDE.md`, `.cursorrules`, and `.github/copilot-instructions.md` are routing stubs only. Do NOT add substantive rules to them.
4. **Configuration Authority**: `templates/<profile>/profile.json` is the sole configuration source. The `profiles/` directory has been permanently deleted. If you encounter any reference to `profiles/`, ignore it.

## Quick Start

```
# Process a thesis (example)
python scripts/run_v2.py thesis.docx --profile uestc

# Available profiles: uestc, uestc-marxism
```

## File Map

| Path | Purpose |
|------|---------|
| `.agent/skills/thesis-formatter/SKILL.md` | Full pipeline spec, anti-patterns, error triage |
| `.agent/workflows/thesis.md` | SOP workflow with pre/post-flight gates |
| `scripts/run_v2.py` | Main pipeline orchestrator |
| `scripts/hooks/` | Post-extraction hooks (profile-aware) |
| `scripts/compile.ps1` | Standalone Docker debug helper (NOT the primary compiler) |
| `templates/<profile>/profile.json` | Profile configuration (SOLE config source) |
| `templates/<profile>/checklist.md` | QA checklist per profile |
| `templates/failure-report.md` | Structured failure report template |
| `vendor/DissertationUESTC/` | Upstream LaTeX template |
