# D40 Mutant Pilot

This fixture is the smallest docx-level regression for D40.

## What it contains

- one `Heading 1` chapter anchor
- one trigger paragraph: `"$v = at$ (1-2)"`
- one control paragraph with inline math but no trailing equation number

## What it checks

- the trigger paragraph becomes a LaTeX equation block
- `\tag{1-2}` appears at least once
- the literal `(1-2)` marker does not survive in emitted chapter `.tex`
- the control paragraph text still survives

## Regenerate

```powershell
python .\generate_d40_min_docx.py
```

## Pilot rule

If this pilot does not stay stable under `pandoc_ast_extract.py`, do not expand to D23 / D12 / D49 fixtures. Keep the scope at one pilot and revisit the fixture framework first.
