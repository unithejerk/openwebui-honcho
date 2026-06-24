# Security Policy

## Reporting a vulnerability

If you discover a security issue in this plugin, please report it privately to
the maintainers rather than opening a public issue. The integration handles
user conversation data and derived identity material, so we take reports
seriously.

## Design protections

This plugin was built with several privacy and safety properties. If you
believe any of them are compromised, that's a security issue.

### Identity isolation

- User IDs never leave the Open WebUI deployment. All Honcho resource IDs
  (peers, sessions, events) are derived via **HMAC-SHA256** from a
  deployment-wide salt (`OPENWEBUI_HONCHO_IDENTITY_SALT`) combined with the
  internal Open WebUI user/model/chat identifiers.
- The salt must be ≥32 random characters. Rotating it creates a new identity
  namespace and disconnects existing memory from Open WebUI identities.
- The identity derivation is one-way: given a Honcho peer ID, you cannot
  recover the original Open WebUI user ID without the salt.

### Scoped operations

- Each peer pair is strictly scoped: the `user_peer` observes itself (builds
  self-knowledge); the `assistant_peer` observes the user (builds model-scoped
  knowledge). The assistant peer never observes itself.
- Sessions are derived per (user, chat) pair. No cross-chat or cross-user
  leakage through session IDs.
- Model-callable tools are gated behind the Honcho filter toggle — they refuse
  to operate if memory is disabled for the chat or globally.
- The global memory toggle in Settings → Personalization → Memory acts as a
  master kill-switch across all chats.

### Fail-open

All three plugins (filter, tools, actions) are designed to **fail open**:
- The filter returns the original request body unchanged on error
- Tools return safe error strings that don't leak connection details
- Actions return `{"ok": False, "message": "..."}` on failure

A circuit breaker prevents cascading failures to the Honcho API.

### Data minimisation

- Only text messages in persistent, single-user chats are persisted
- Temporary chats (`local:*`) and multi-user channels (`channel:*`) are
  explicitly skipped
- Internal tasks (title generation, autocomplete), images, files, and tool
  results are not persisted
- Messages are deduplicated by HMAC-derived event IDs

### Memory injection is explicitly untrusted

The `<honcho-memory>` block injected into the system prompt is labelled as
untrusted. Models are instructed never to follow instructions inside the
block. Previously injected blocks are stripped before a new one is added to
prevent context accumulation.

## What deletion covers

- **Forget Current Chat**: Requests asynchronous deletion of the current
  Honcho session. Does not guarantee immediate erasure from all Honcho-derived
  representations.
- **Forget Matching Memories**: Deletes conclusions matching a semantic search
  query. Scoped to the current model's perspective.
- **Full erasure** of a user from all Honcho-derived representations requires
  administrative Honcho operations outside the scope of these plugins.

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | Yes |
| 0.1.x | No |

## Dependencies

- `honcho-ai==2.1.2` — pinned to avoid unexpected SDK changes
- `fastapi>=0.115`, `pydantic>=2.0` — standard Open WebUI dependencies
- `opentelemetry-*` — optional, disabled by default
