# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.2.0] — 2026-06-15

### Added
- Native memory UI integration — Settings → Personalization → Memory backed by `user_peer.card()`
- Route replacement for `/api/v1/memories/*` — native UI reads/writes Honcho self-card
- Global memory toggle support — Settings toggle acts as master switch for all chats
- `honcho_search_messages` tool with sender, date range, and metadata filters
- Date range (`created_after`/`created_before`) and metadata filters on message search
- `HonchoService.user_peer_card()` and `user_peer_set_card()` for self-card operations
- `HonchoService.search_messages()` with per-sender peer routing
- REST API install script (`scripts/install.py`) — imports all three plugins via API
- Auto-install of `honcho-ai` via frontmatter `requirements:` field
- Circuit breaker with configurable Valves (`circuit_breaker_threshold`, `circuit_breaker_cooldown_seconds`)
- Per-session capture locks (replaces global lock)
- Expanded reasoning level support (minimal, low, medium, high, max)
- `__all__` public API surface in core.py

### Changed
- Inspect action renamed to "Model's View of You"
- `RuntimeConfig` cached at module level via `get_config()`
- `strip_memory_context` fast-path when no memory tags present
- Error logging includes `exc_info=True` for full tracebacks
- Actions plugin uses `safe_tool_error()` consistently

### Fixed
- Route replacement now rebuilds FastAPI `dependant` (not just `endpoint`)
- ChromaDB response shape in `_honcho_query_memory`
- Install guide no longer references fictional UI elements

## [0.1.0] — 2026-06-15

### Added
- Initial release: Honcho memory plugin for Open WebUI
- Three-plugin architecture: Filter, Tools, Action
- Per-chat togglable memory injection via Filter inlet/outlet
- Four model-callable memory tools (honcho_context, honcho_search_conclusions, honcho_session, honcho_ask)
- Three user-triggered actions (Inspect, Forget Current Chat, Forget Matching Memories)
- HMAC-SHA256 derived opaque identity layer
- 11 tests, CI workflow
