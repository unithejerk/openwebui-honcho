# Contributing

## Setup

```bash
git clone <repo-url>
cd openwebui-honcho/repo
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install pre-commit
pre-commit install
```

## Branching

- `main` is the stable branch — always deployable
- Create a feature branch for every change: `git checkout -b feature/my-change`
- Branch names: `feature/*`, `fix/*`, `docs/*`, `chore/*`
- Never commit directly to `main`

## Pull requests

1. Push your branch and open a PR against `main`
2. CI must pass: `generate_plugins.py --check` and `pytest`
3. At least one approving review required before merge
4. Squash-merge into `main` — keep history linear

## Commit messages

Follow conventional commits:

```
feat: add honcho_search_messages tool
fix: correct ChromaDB response shape in query handler
docs: comprehensive install guide
chore: bump honcho-ai to 2.1.3
```

Co-author Claude-generated commits with:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

## Before submitting

- [ ] `python scripts/generate_plugins.py` — regenerates dist files
- [ ] `python scripts/generate_plugins.py --check` — verifies dist matches source
- [ ] `python -m pytest` — all tests pass
- [ ] New code follows existing patterns (fail-open, safe_tool_error, circuit breaker)
- [ ] New HonchoService methods are added to the appropriate plugin (tools, actions, or filter)

## Project structure

```
src/openwebui_honcho/
  core.py             Shared implementation
  filter_plugin.py    Filter (inlet/outlet + route replacement)
  tools_plugin.py     Model-callable tools
  actions_plugin.py   User-clickable actions

dist/                 Generated standalone plugins
scripts/
  generate_plugins.py Build script
  install.py          REST API installer

tests/
  test_core.py        Core logic tests
  test_plugins.py     Plugin integration tests
```

See [AGENTS.md](AGENTS.md) for detailed architecture and design rules.

## Environment variables

See `.env.example` for all required variables. `OPENWEBUI_HONCHO_IDENTITY_SALT` must be at least 32 random characters — this is the HMAC key for deriving opaque peer/session IDs.

## License

MIT — see the [LICENSE](LICENSE) file.
