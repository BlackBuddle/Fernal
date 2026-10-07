# Fernal

Desktop overlay that grows a procedural 3D plant. Python 3.14 + PySide6 (Qt Quick 3D scene, Qt Widgets UI) + numpy.

## Commands

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m fernal                      # run the overlay
.venv/Scripts/python -m fernal --screenshot out.png --theme erdtree --age 300 --seed 7 --hour 14
.venv/Scripts/python -m pytest -q                   # tests
.venv/Scripts/python scripts/make_textures.py       # regenerate fernal/assets/*.png
```

## Rules

- Language: code, comments, docs, commit messages and agent prompts in English. Chat replies to the user in Korean.
- Only `fernal/qml/Scene.qml` and its shaders are QML. All other UI is Qt Widgets in Python. UI copy is Korean.
- Runtime deps: PySide6, numpy only. No new dependencies without asking.
- Models: visual tasks (scene, materials, textures, shaders, panel design) on Opus; logic on Sonnet; Fable only with explicit user approval.
- Spec: `docs/superpowers/specs/2026-10-07-fernal-design.md`. Plan: `docs/superpowers/plans/2026-10-07-fernal-plan.md`. Follow the interface contracts in the plan.
- Budget: two days, 16 hours. Cut order if late: particles -> wind shader -> falling leaf -> fruits.
