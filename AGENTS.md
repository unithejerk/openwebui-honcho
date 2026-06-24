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
tests/
  test_core.py        Unit tests for core logic and identity
  test_plugins.py     Integration tests for generated plugins
```

Each plugin imports from core via `from openwebui_honcho.core import *`. The generate script strips this line and inlines core.py. The dist files are what get imported into Open WebUI.

## Key design rules

1. **Identity model**: All Honcho resource IDs are HMAC-SHA256 derived from `OPENWEBUI_HONCHO_IDENTITY_SALT` + user/model/chat IDs. User IDs never leave the server.

2. **Peer layout**: `user_peer` (observe_me=True) and `assistant_peer` (observe_me=False, one per model). The user_peer's self-card (`user_peer.card()`) is the canonical memory store. The assistant_peer's perspective (`assistant_peer.context(target=user_peer)`) provides model-scoped context.

3. **Fail-open**: All three plugins catch exceptions and return safe fallbacks. The filter returns the original body unchanged. Tools return error strings via `safe_tool_error()`. Actions return `{"ok": False, "message": "..."}`.

4. **Circuit breaker**: Module-level `_failure_count`/`_failure_until` state. Check `circuit_allows()` before Honcho calls; call `record_result(success)` after. Configurable via Filter Valves.

5. **Configuration**: Everything from env vars, loaded once via `get_config()`. Never call `RuntimeConfig.from_env()` outside of `get_config()`.

6. **Route replacement**: The filter module replaces `/api/v1/memories/*` route handlers at load time. Must rebuild `route.dependant` (not just `route.endpoint`) because FastAPI resolves dependencies from `dependant.call`. Guard behind `_HAS_OPENWEBUI` import check and `HONCHO_API_KEY` presence.

## When adding a new tool

1. Add the service method to `HonchoService` in `core.py`
2. Add the tool method to `Tools` in `tools_plugin.py` following the existing pattern (`_service_and_context` + try/except + `safe_tool_error`)
3. Regenerate dist files and run tests

## When touching the memories API routes

The route replacement handlers must match the original endpoint signatures exactly (parameter names and `Depends` annotations). FastAPI dependency injection depends on parameter name matching. New handlers must be defined inside the `if _HAS_OPENWEBUI:` block.

## Frontmatter fields

Each plugin docstring supports: `title`, `description`, `required_open_webui_version`, `requirements`, `version`, `license`. The `requirements` field triggers auto-install by Open WebUI. The `generate_plugins.py` script strips these lines from the generated Python output — add new frontmatter fields there too.

## Testing constraints

Tests run without Open WebUI or Honcho — all external dependencies are mocked. Generated dist files are tested for importability. The route replacement code is guarded and never runs in tests.
