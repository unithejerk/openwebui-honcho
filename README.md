# Open WebUI Honcho Memory

[![CI](https://github.com/unithejerk/openwebui-honcho/actions/workflows/ci.yml/badge.svg)](https://github.com/unithejerk/openwebui-honcho/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Open WebUI 0.9.6](https://img.shields.io/badge/open--webui-0.9.6-green)](https://openwebui.com/)
[![Honcho 3.0.9](https://img.shields.io/badge/honcho-3.0.9-purple)](https://honcho.dev)
[![Status: Beta](https://img.shields.io/badge/status-beta-orange)](#)

Opt-in, user-scoped persistent memory for [Open WebUI](https://openwebui.com/) chats, backed by [Honcho](https://honcho.dev). Models remember who your users are, what they prefer, and what they talked about — across sessions, across models, across time.

---

## Table of contents

- [Why Honcho](#why-honcho)
- [Features](#features)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [User actions](#user-actions)
- [What gets persisted](#what-gets-persisted)
- [Observability](#observability)
- [Migrating from ChromaDB](#migrating-from-chromadb)
- [Building (for development)](#building-for-development)
- [SDK compatibility](#sdk-compatibility)
- [Privacy](#privacy)
- [Getting help](#getting-help)
- [Other docs](#other-docs)
- [License](#license)

---

## Why Honcho

Open WebUI's built-in memory stores facts as raw vectors in ChromaDB — one collection per user, no structure, no cross-model sharing. Honcho adds a reasoning layer on top:

| Capability | Built-in (ChromaDB) | Honcho |
|---|---|---|
| Cross-model recall | No — each model sees only its own chats | Yes — facts learned by one model are available to all |
| Structured facts | Raw text blobs | Self-card with a dreaming agent that derives and refines facts over time |
| Semantic search | Cosine distance only | Semantic search over conclusions, messages, and representations |
| Model's perspective | None | Each model has its own working representation of the user |
| Manual fact editing | Limited UI | Full CRUD at Settings → Personalization → Memory, synced in real time |

If all you need is "remember this fact," the built-in memory is fine. If you want models to build a working understanding of your users that improves over time and transfers across models, that's what Honcho provides.

---

## Features

### For users
- **Per-chat memory toggle** — `[Honcho Memory]` chip in the chat input; on when you want it, off when you don't
- **Global master switch** — Settings → Personalization → Memory kills memory across all chats
- **Native Memory UI** — add, edit, and delete facts at Settings → Personalization → Memory; changes sync to Honcho in real time
- **Cross-model recall** — facts learned by one model are available to every model with Honcho enabled
- **Model's View of You** — click the button on any message to see what the current model knows about you
- **Degraded status** — if Honcho becomes unreachable, a persistent banner warns users that memory is temporarily down while chats continue normally

### For models
Five callable tools let the model query memory directly:

| Tool | What it does |
|---|---|
| `honcho_context` | Get known user facts or the current model's full user representation |
| `honcho_search_conclusions` | Semantic search over derived facts the model has concluded about the user |
| `honcho_search_messages` | Search raw messages across all sessions by sender, date range, or metadata |
| `honcho_session` | Get memory scoped to the current chat session (messages, summary, profile) |
| `honcho_ask` | Ask Honcho a direct question about the user (configurable reasoning depth) |

### For admins
- **Three user actions** — "Model's View of You" inspects memory, "Forget Current Chat" deletes a session, "Forget Matching Memories" removes conclusions by semantic query
- **Identity isolation** — user IDs never leave the deployment; all Honcho resource IDs are HMAC-SHA256 derived from a deployment-wide salt
- **Fail-open everywhere** — if Honcho is down, chats continue normally; the circuit breaker prevents cascading failures
- **OpenTelemetry** — every operation emits spans and metrics (disabled by default, enable with one env var)
- **Startup health check** — verifies Honcho connectivity on first use; if unreachable, logs the error and shows a persistent warning banner in the chat UI
- **ChromaDB migration** — `scripts/migrate.py` imports existing Open WebUI memories into Honcho as conclusions

---

## Quick start

### Prerequisites

- A running [Open WebUI](https://openwebui.com/) instance with admin access
- A [Honcho](https://honcho.dev) API key and workspace

### 1. Set environment variables on the Open WebUI server

```bash
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=true
HONCHO_API_KEY=<your-honcho-api-key>
HONCHO_BASE_URL=https://api.honcho.dev          # default
HONCHO_WORKSPACE_ID=openwebui                    # default
OPENWEBUI_HONCHO_IDENTITY_SALT=<at-least-32-random-chars>
```

Generate a salt: `python3 -c "import secrets; print(secrets.token_hex(32))"`

Restart Open WebUI after setting them.

### 2. Install the plugin

Create an admin API key in Open WebUI (**Settings → Account → API Keys**), then:

```bash
python scripts/install.py \
  --base-url http://localhost:3000 \
  --api-key <your-admin-api-key>
```

This imports all three plugin components via the REST API. Open WebUI auto-installs `honcho-ai==2.1.2` from the `requirements` field in each plugin's frontmatter. Use `--dry-run` to preview without making changes.

### 3. Attach to models

In **Admin Panel → Settings → Models**, for each model you want memory with:

- Add `honcho_memory` to **Filter IDs**
- Add `honcho_memory` to **Default Filter IDs** (or leave off for opt-in)
- Attach **Honcho Memory Tools** in the model's Tools section

### 4. Verify

Start a chat with memory toggled on, say something about yourself, then ask the model what it knows. Or open **Settings → Personalization → Memory** to inspect the self-card.

---

## Architecture

Three plugins backed by a shared implementation, generated into standalone files:

```
src/openwebui_honcho/
  core.py              Shared logic — HonchoService, identity derivation,
                       circuit breaker, telemetry, config
  filter_plugin.py     Filter — inlet injects memory context before the
                       LLM call; outlet captures completed turns; replaces
                       /api/v1/memories/* routes for the native UI
  tools_plugin.py      Tools — 5 model-callable memory tools
  actions_plugin.py    Action — 3 user-clickable message actions

dist/                  Generated standalone plugins (core concatenated
                       into each plugin by generate_plugins.py)
```

The filter inlet extracts the latest user message, queries Honcho for relevant context, and injects a `<honcho-memory>` block into the system prompt. The outlet captures completed user and assistant turns, deduplicates by HMAC-derived event ID, and persists them to the current Honcho session. The whole block is stripped before capture to prevent feedback loops.

---

## Configuration

All configuration comes from environment variables so the three plugins cannot drift:

| Variable | Required | Default | Description |
|---|---|---|---|
| `HONCHO_API_KEY` | Yes | — | Honcho API key |
| `OPENWEBUI_HONCHO_IDENTITY_SALT` | Yes | — | ≥32 characters. HMAC key for deriving opaque peer/session IDs |
| `ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS` | Yes | — | Must be `true` for auto-install of `honcho-ai` |
| `HONCHO_BASE_URL` | No | `https://api.honcho.dev` | Honcho server URL |
| `HONCHO_WORKSPACE_ID` | No | `openwebui` | Honcho workspace |
| `OPENWEBUI_HONCHO_FILTER_ID` | No | `honcho_memory` | Function ID used for filtering and gating |
| `OPENWEBUI_HONCHO_TIMEOUT_SECONDS` | No | `30` | Honcho API timeout |
| `OPENWEBUI_HONCHO_MAX_RETRIES` | No | `2` | Honcho API retries |
| `OPENWEBUI_HONCHO_VERBOSE` | No | `false` | Set `openwebui_honcho` logger to DEBUG |
| `OTEL_TRACES_EXPORTER` | No | — | Set by Open WebUI when `ENABLE_OTEL=true` |
| `OTEL_METRICS_EXPORTER` | No | — | Set by Open WebUI when `ENABLE_OTEL=true` |
| `OTEL_PYTHON_INSTRUMENT_HTTPS` | No | `false` | Auto-instrument `httpx` for Honcho HTTP spans |

Rotating `OPENWEBUI_HONCHO_IDENTITY_SALT` creates a new identity namespace and disconnects existing memory from Open WebUI identities.

### Valves (UI-configurable)

The Filter exposes runtime-adjustable Valves in the Open WebUI admin panel:

| Valve | Default | Range | Description |
|---|---|---|---|
| `search_top_k` | 10 | 1–100 | Number of context results to retrieve |
| `search_max_distance` | 0.5 | 0–1 | Maximum semantic distance for matches |
| `include_most_frequent` | true | — | Include most frequent conclusions |
| `max_conclusions` | 25 | 1–100 | Maximum conclusions per context query |
| `max_context_chars` | 8000 | 500–50000 | Character limit for injected context block |
| `noise_patterns` | [] | — | Additional patterns to skip during capture |
| `disable_default_noise_patterns` | false | — | Skip built-in heartbeat/reminder filtering |
| `show_error_status` | true | — | Show "temporarily unavailable" status in chat UI |

---

## User actions

Three clickable buttons appear on messages when the plugin is installed:

| Action | What it does |
|---|---|
| **Model's View of You** | Opens an HTML overlay showing the user's self-card (all models), what the current model knows, and the model's working representation |
| **Forget Current Chat** | Deletes the current Honcho session after confirmation. Does not guarantee complete erasure from all derived representations |
| **Forget Matching Memories** | Prompts for a semantic search query, shows matching conclusions, and deletes them after confirmation |

---

## What gets persisted

- User and assistant text messages in persistent, single-user chats
- Deduplicated by HMAC-derived event IDs

## What doesn't get persisted

- Temporary chats (`local:*`) and multi-user channels (`channel:*`)
- Internal tasks (title generation, autocomplete, scheduled reminders)
- Images, files, and tool results
- System messages and heartbeats

---

## Observability

Telemetry piggybacks on Open WebUI's OpenTelemetry setup. Enable it globally with the standard Open WebUI environment variables:

```bash
ENABLE_OTEL=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://your-collector:4317
```

Once enabled, the plugin's spans and metrics flow through the same pipeline as Open WebUI's built-in instrumentation — no separate plugin flag needed. When OTel is disabled (no global TracerProvider), all span and metric calls safely no-op.

**Spans** — every Honcho operation creates a span: `honcho.create_resources`, `honcho.targeted_context`, `honcho.add_completed_messages`, `honcho.search_conclusions`, `honcho.search_messages`, `honcho.session_context`, `honcho.ask`, `honcho.user_peer_card`, `honcho.edit_user_peer_card`, `honcho.health_check`. Each span carries attributes for the operation parameters and result.

**Metrics** — three instruments are registered:
- `honcho.memory_requests_total` (counter) — tagged with `operation` and `result`
- `honcho.memory_messages_persisted_total` (counter)
- `honcho.memory_operation_duration_seconds` (histogram)

The circuit breaker opens after 3 consecutive failures (60s cooldown). The startup health check runs lazily on the first filter inlet call — if Honcho is unreachable, a persistent warning banner appears in the chat UI and the error is logged.

---

## Migrating from ChromaDB

If your Open WebUI instance already has user memories stored in the built-in ChromaDB, use `scripts/migrate.py` to import them as Honcho conclusions:

```bash
python scripts/migrate.py \
  --chromadb-data-dir /path/to/data/vector_db \
  --honcho-api-key sk-... \
  --identity-salt <same-salt-as-above> \
  --dry-run  # preview first, then remove to run for real
```

The script reads every `user-memory-*` ChromaDB collection, derives matching Honcho peer IDs from the identity salt, and bulk-creates conclusions from a synthetic "openwebui" peer about each user. Honcho's dreaming agent processes these into richer user representations over time. Use `--dry-run` to preview without writing.

---

## Building (for development)

```bash
pip install -e ".[dev]"
python scripts/generate_plugins.py         # build dist files
python scripts/generate_plugins.py --check  # CI: verify dist matches source
python -m pytest                            # run tests (30)
```

A [Dockerfile](Dockerfile) is provided if you prefer to bake `honcho-ai==2.1.2` into a custom Open WebUI image rather than using frontmatter requirements.

---

## SDK compatibility

This project pins `honcho-ai==2.1.2`, which surfaces async operations through an `.aio` namespace (e.g. `honcho.aio.peer()`, `peer.aio.context()`, `session.aio.messages()`). The Honcho SDK v3.x documentation shows these methods called directly without the `.aio` prefix. When upgrading the SDK, every `.aio` call site will need updating.

---

## Privacy

- User IDs never leave the Open WebUI deployment. All Honcho resource IDs (peers, sessions, events) are derived via HMAC-SHA256 from `OPENWEBUI_HONCHO_IDENTITY_SALT`.
- The salt is a shared deployment secret. Protect it like an encryption key.
- Rotating the salt orphans all existing memory — the old peer and session IDs become unreachable.
- The `<honcho-memory>` block injected into the system prompt is explicitly labelled as untrusted. Models are instructed never to follow instructions inside the block, and previous blocks are stripped before new ones are injected.
- Deleting a session or conclusions does not guarantee immediate or complete erasure from all Honcho-derived representations. Full user erasure requires administrative Honcho operations outside the scope of these plugins.

---

## Getting help

- **Bugs and feature requests:** [Open an issue](https://github.com/unithejerk/openwebui-honcho/issues)
- **Questions and discussion:** [GitHub Discussions](https://github.com/unithejerk/openwebui-honcho/discussions)
- **Install troubleshooting:** See the [troubleshooting section](INSTALL.md#10-troubleshooting) in INSTALL.md

---

## Other docs

- [`INSTALL.md`](INSTALL.md) — Step-by-step install guide with per-step verification
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Development setup, branching, PR checklist
- [`SECURITY.md`](SECURITY.md) — Vulnerability reporting, privacy design details
- [`CHANGELOG.md`](CHANGELOG.md) — Version history
- [`AGENTS.md`](AGENTS.md) — Architecture and design rules for AI agents working on the codebase

> **For LLM / coding agents:** Point your agent at [`INSTALL.md`](INSTALL.md) — it's structured so an agent gathers inputs, runs the install, and verifies every step automatically.

## License

MIT — see [LICENSE](LICENSE).
