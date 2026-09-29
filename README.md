# ocode — smart, Odoo-aware code editor for the terminal

> PRD: [`ocode-requirements.md`](ocode-requirements.md) · License: MIT · Status: M0 foundations

## Install (dev)

```bash
pip install -e ".[dev]"
ocode --help
ocode .
```

## Layout

```
src/ocode/
  __main__.py   # CLI entry
  app.py        # Textual App shell
  core/         # event bus, config, commands, tasks, logging
  engines/      # SMN/OMLS/OSS/OTE/OPD/OKI/OSG/OSH/GIT (stubs after M0)
  ui/           # screens, widgets, themes
  templates/    # Jinja2 scaffolding templates (M5)
  data/versions/# per-Odoo-version profiles
  utils/
tests/
```

## M0 scope

Empty app shell + core services + `doctor`/`init` stubs. See PRD §10.
