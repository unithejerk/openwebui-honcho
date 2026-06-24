# Contributing

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior by opening an issue in the [project repository](https://github.com/unithejerk/openwebui-honcho/issues).

## Setup

```bash
git clone https://github.com/unithejerk/openwebui-honcho.git
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

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Every commit message must use one of these types:

```
feat: add honcho_search_messages tool
fix: correct ChromaDB response shape in query handler
docs: comprehensive install guide
chore: bump honcho-ai to 2.1.3
test: add coverage for session_context
refactor: extract identity derivation into standalone helper
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

Breaking changes must include a `!` after the type and a `BREAKING CHANGE:` footer:

```
feat!: upgrade to Honcho SDK v3

BREAKING CHANGE: the .aio namespace is removed — all async methods are
now called directly on peer/session objects.
```

## Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every PR that changes behavior must include a changelog entry under the `[Unreleased]` section in `CHANGELOG.md`. Use the standard categories: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

## Pull requests

1. Push your branch and open a PR against `main`
2. CI must pass: `generate_plugins.py --check` and `pytest`
3. At least one approving review required before merge
4. Squash-merge into `main` — keep history linear

## Before submitting

- [ ] `python scripts/generate_plugins.py` — regenerates dist files
- [ ] `python scripts/generate_plugins.py --check` — verifies dist matches source
- [ ] `python -m pytest` — all tests pass
- [ ] `ruff format --check src scripts tests` — formatting
- [ ] `ruff check src scripts tests` — linting
- [ ] Changelog entry added under `[Unreleased]` in `CHANGELOG.md`
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

## License

MIT — see the [LICENSE](LICENSE) file.
