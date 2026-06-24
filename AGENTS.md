# AGENTS.md

Guide for AI agents working on this codebase.

## Project overview

Open WebUI Honcho Memory — three plugins (Filter, Tools, Action) that add persistent, user-scoped memory to Open WebUI via the Honcho SDK. Written in Python, targets Open WebUI 0.9.6 and honcho-ai 2.1.2.

## Build, test, lint

```bash
pip install -e ".[dev]"
pre-commit install                      # runs --check + pytest before commits
python scripts/generate_plugins.py      # build dist files
python scripts/generate_plugins.py --check  # CI: verify dist matches source
python -m pytest -v                     # run tests (30 expected)
```

Always regenerate dist files after source changes and verify `--check` passes.

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Every commit message must start with a type: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Breaking changes require a `!` after the type and a `BREAKING CHANGE:` footer.

## Architecture

```
src/openwebui_honcho/
  core.py             Shared implementation (HonchoService, identity, config, utilities)
  filter_plugin.py    Filter class — inlet/outlet hooks + route replacement for /api/v1/memories
  tools_plugin.py     Tools class — 5 model-callable memory tools
  actions_plugin.py   Action class — 3 user-clickable message actions

dist/                 Generated standalone plugins (core + plugin concatenated)
scripts/
  generate_plugins.py Bundles core.py into each plugin as standalone .py files
  install.py          REST API installer for a running Open WebUI instance
  migrate.py          ChromaDB → Honcho migration for existing Open WebUI memories
docs/                 Reference guides for Open WebUI extensibility and Honcho SDK
tests/
  test_core.py        Unit tests for core logic and identity
  test_plugins.py     Integration tests for generated plugins
  test_telemetry.py   OpenTelemetry span and metric tests
```

Each plugin imports from core via `from openwebui_honcho.core import *`. The generate script strips this line and inlines core.py. The dist files are what get imported into Open WebUI.

## Key design rules

1. **Identity model**: All Honcho resource IDs are HMAC-SHA256 derived from `OPENWEBUI_HONCHO_IDENTITY_SALT` + user/model/chat IDs. User IDs never leave the server. Use `derive_id()` and `derive_identity()` — never construct IDs manually.

2. **Peer layout**: `user_peer` (observe_me=True) and `assistant_peer` (observe_me=False, one per model). The user_peer's self-card (`user_peer.card()`) is the canonical memory store. The assistant_peer's perspective (`assistant_peer.context(target=user_peer)`) provides model-scoped context.

3. **Fail-open everywhere**: All three plugins catch exceptions and return safe fallbacks. The filter returns the original body unchanged. Tools return error strings via `safe_tool_error()`. Actions return `{"ok": False, "message": "..."}`. Never let a Honcho exception propagate to Open WebUI.

4. **Circuit breaker**: Module-level `_failure_count`/`_failure_until` state in core.py. Check `circuit_allows()` before Honcho calls; call `record_result(success)` after. Opened after 3 consecutive failures, 60s cooldown. Shared across all three plugins.

5. **Configuration**: Everything from env vars, loaded once via `get_config()`. Never call `RuntimeConfig.from_env()` outside of `get_config()`. The cached config is shared across all plugins.

6. **Route replacement**: The filter module replaces `/api/v1/memories/*` route handlers at load time. Must rebuild `route.dependant` (not just `route.endpoint`) because FastAPI resolves dependencies from `dependant.call`. Guard behind `_HAS_OPENWEBUI` import check and `HONCHO_API_KEY` presence.

## Honcho SDK version warning

This project pins **honcho-ai==2.1.2**, which surfaces async operations through an `.aio` namespace:

```python
# v2.1.2 (this project) — correct
peer = await honcho.aio.peer("alice")
card = await peer.aio.card()
context = await peer.aio.context(target=other_peer)

# v3.x (current docs) — DO NOT USE, will fail
peer = honcho.peer("alice")
card = peer.card()
context = peer.context(target=other_peer)
```

Every Honcho API call must go through `.aio`. If you're reading the Honcho v3 docs, translate every method to the `.aio` namespace. When the SDK is upgraded, every `.aio` call site will need updating.

## When adding a new tool

1. Add the service method to `HonchoService` in `core.py` — follow the existing pattern: span, telemetry attributes, try/except/finally with metrics
2. Add the tool method to `Tools` in `tools_plugin.py` — use `_service_and_context` for the gating preamble, then try/except with `safe_tool_error` and `record_result`
3. Regenerate dist files, run tests, and add a changelog entry under `[Unreleased]`

## When touching the memories API routes

The route replacement handlers must match the original endpoint signatures exactly (parameter names and `Depends` annotations). FastAPI dependency injection depends on parameter name matching. New handlers must be defined inside the `if _HAS_OPENWEBUI:` block. Always test with `test_memory_route_map_is_complete` after changes.

## Frontmatter fields

Each plugin docstring supports: `title`, `description`, `required_open_webui_version`, `requirements`, `version`, `license`. The `requirements` field triggers auto-install by Open WebUI. The `generate_plugins.py` script strips these lines from the generated Python output — add new frontmatter fields there too.

## Testing constraints

Tests run without Open WebUI or Honcho — all external dependencies are mocked using `monkeypatch` and `types.SimpleNamespace`. Generated dist files are tested for importability. The route replacement code is guarded and never runs in tests (the `_HAS_OPENWEBUI` guard is always `False` outside Open WebUI).

## Common pitfalls

- **Forgetting `.aio`**: Calling `peer.card()` instead of `peer.aio.card()` fails silently or raises `AttributeError`. Every Honcho object access (peer, session) must go through `.aio`.
- **Not regenerating dist files**: Source changes in core.py or plugin files won't take effect in Open WebUI until `scripts/generate_plugins.py` is run. CI enforces this with `--check`.
- **Letting exceptions propagate**: Every plugin entry point (inlet, outlet, tool method, action method) must catch all exceptions. Use `safe_tool_error()` for tools, return original body for filters, return `{"ok": False}` for actions.
- **Constructing IDs manually**: Use `derive_id()`, `derive_identity()`, and `derive_event_id()`. Never concatenate strings to build peer or session IDs.
- **Calling `RuntimeConfig.from_env()` directly**: Always use `get_config()` — it caches the config globally. Calling `from_env()` creates a duplicate with potentially stale or missing values.
