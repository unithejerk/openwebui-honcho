"""
title: Honcho Memory
description: Opt-in Honcho memory injection and completed-turn capture.
required_open_webui_version: 0.9.6
requirements: honcho-ai==2.1.2
version: 0.1.0
license: MIT
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from honcho import Honcho
from pydantic import BaseModel, Field

from openwebui_honcho.core import *

# Additional imports for memory route replacement (only used inside Open WebUI)
try:
    from fastapi import Depends, HTTPException, Request, status
    from open_webui.main import app
    from open_webui.routers.memories import AddMemoryForm, QueryMemoryForm
    from open_webui.utils.auth import get_verified_user

    _HAS_OPENWEBUI = True
except ImportError:
    _HAS_OPENWEBUI = False

LOG_MEM = logging.getLogger("openwebui_honcho.memories")


def _card_to_memories(facts: list[str], user_id: str) -> list[dict[str, Any]]:
    """Convert Honcho peer card facts to the memory model shape the frontend expects."""
    now = datetime.now(UTC).isoformat()
    return [
        {
            "id": f"honcho_{i}",
            "content": fact,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
        }
        for i, fact in enumerate(facts)
    ]


if _HAS_OPENWEBUI:

    def _require_config():
        """Load config or raise a friendly HTTP 503 if Honcho is not configured."""
        try:
            return get_config()
        except ConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Honcho memory is not configured: {exc}",
            ) from exc

    async def _honcho_get_memories(user=Depends(get_verified_user)):
        """Return the user's Honcho self-card as memory entries."""
        config = _require_config()
        service = HonchoService(config)
        facts = await service.user_peer_card(user.id)
        return _card_to_memories(facts, user.id)

    async def _honcho_add_memory(
        request: Request,
        form_data: AddMemoryForm,
        user=Depends(get_verified_user),
    ):
        """Add a fact to the user's Honcho self-card."""
        config = _require_config()
        service = HonchoService(config)
        facts = await service.edit_user_peer_card(user.id, lambda card: card + [form_data.content])
        return _card_to_memories(facts, user.id)

    async def _honcho_query_memory(
        request: Request,
        form_data: QueryMemoryForm,
        user=Depends(get_verified_user),
    ):
        """Search the user's Honcho memory using semantic context."""
        config = _require_config()
        service = HonchoService(config)
        # Use the user peer's own context with semantic search over conclusions,
        # then fall back to substring matching the self-card if nothing is found.
        results = await service.query_user_peer_card(
            user.id,
            query=form_data.content or "",
            top_k=form_data.k or 3,
        )
        return {
            "ids": [[f"honcho_{i}" for i in range(len(results))]],
            "documents": [results],
            "metadatas": [[{} for _ in results]],
            # Honcho SDK v2.1.2 does not return distance/similarity scores for
            # any query endpoint (context, search, conclusions).  The ChromaDB
            # response shape still requires this key, so we fill it with 0.0.
            "distances": [[0.0 for _ in results]],
        }

    async def _honcho_delete_user_memories(user=Depends(get_verified_user)):
        """Clear all facts from the user's Honcho self-card."""
        config = _require_config()
        service = HonchoService(config)
        await service.edit_user_peer_card(user.id, lambda _card: [])
        return {"ok": True}

    async def _honcho_delete_memory(memory_id: str, user=Depends(get_verified_user)):
        """Delete a single fact from the user's Honcho self-card."""
        config = _require_config()
        service = HonchoService(config)

        def editor(facts: list[str]) -> list[str]:
            index = _memory_index(memory_id, len(facts))
            if index is not None:
                facts.pop(index)
            return facts

        await service.edit_user_peer_card(user.id, editor)
        return {"ok": True}

    class MemoryUpdateForm(BaseModel):
        content: str

    async def _honcho_update_memory(
        memory_id: str,
        request: Request,
        form_data: MemoryUpdateForm,
        user=Depends(get_verified_user),
    ):
        """Replace a single fact in the user's Honcho self-card by index."""
        config = _require_config()
        service = HonchoService(config)

        def editor(facts: list[str]) -> list[str]:
            index = _memory_index(memory_id, len(facts))
            if index is not None:
                facts[index] = form_data.content
            return facts

        facts = await service.edit_user_peer_card(user.id, editor)
        return _card_to_memories(facts, user.id)

    async def _honcho_reset_memories(user=Depends(get_verified_user)):
        """Clear all facts from the user's Honcho self-card."""
        config = _require_config()
        service = HonchoService(config)
        await service.edit_user_peer_card(user.id, lambda _card: [])
        return {"ok": True}

    def _memory_index(memory_id: str, length: int) -> int | None:
        """Parse the integer index from a honcho_N memory id if valid."""
        if not memory_id.startswith("honcho_"):
            return None
        try:
            index = int(memory_id[len("honcho_") :])
            if 0 <= index < length:
                return index
        except ValueError:
            pass
        return None

    def _replace_memory_routes():
        """Replace built-in /api/v1/memories route handlers with Honcho-backed versions.

        Only activates when Honcho is configured (API key present). Rebuilds both
        route.endpoint and route.dependant because FastAPI resolves dependencies
        from dependant.call (set at init time), not from route.endpoint at call time.
        """
        from fastapi.dependencies.utils import (
            get_dependant,
            get_flat_dependant,
            get_parameterless_sub_dependant,
        )

        config = get_config()
        if not config.api_key:
            return  # Honcho not configured, leave built-in handlers alone

        route_map = {
            ("/api/v1/memories/", "GET"): _honcho_get_memories,
            ("/api/v1/memories/add", "POST"): _honcho_add_memory,
            ("/api/v1/memories/query", "POST"): _honcho_query_memory,
            ("/api/v1/memories/reset", "POST"): _honcho_reset_memories,
            ("/api/v1/memories/delete/user", "DELETE"): _honcho_delete_user_memories,
            ("/api/v1/memories/{memory_id}/update", "POST"): _honcho_update_memory,
            ("/api/v1/memories/{memory_id}", "DELETE"): _honcho_delete_memory,
        }

        replaced = 0
        for route in app.routes:
            if not hasattr(route, "path"):
                continue
            methods = route.methods or set()
            for (path, method), handler in route_map.items():
                if route.path == path and method in methods:
                    route.endpoint = handler
                    route.dependant = get_dependant(
                        path=route.path_format, call=handler, scope="function"
                    )
                    for depends in (route.dependencies or [])[::-1]:
                        route.dependant.dependencies.insert(
                            0,
                            get_parameterless_sub_dependant(
                                depends=depends, path=route.path_format
                            ),
                        )
                    route._flat_dependant = get_flat_dependant(route.dependant)
                    replaced += 1
                    break

        expected = len(route_map)
        if replaced < expected:
            LOG_MEM.error(
                "Honcho: replaced only %d of %d /api/v1/memories route handlers",
                replaced,
                expected,
            )
        else:
            LOG_MEM.info("Honcho: replaced all %d /api/v1/memories route handlers", replaced)

    try:
        _replace_memory_routes()
    except Exception as exc:
        LOG_MEM.error(
            "Honcho: failed to replace /api/v1/memories routes: %s",
            exc,
            exc_info=LOG_MEM.isEnabledFor(logging.DEBUG),
        )
        # Fail open -- the filter inlet/outlet still work


_health_checked: bool = False
_health_ok: bool = False
_health_banner_emitted: bool = False
_health_lock = asyncio.Lock()


async def _run_health_check() -> None:
    """Verify Honcho connectivity once, lazily, at first use.

    Catches misconfigured API keys or unreachable Honcho servers at startup
    time rather than surfacing the error in a user's chat.
    """
    global _health_checked, _health_ok
    async with _health_lock:
        if _health_checked:
            return
        _health_checked = True

    config = get_config()
    tracer = get_tracer()
    with tracer.start_as_current_span("openwebui_honcho.health_check") as span:
        span.set_attribute("honcho.base_url", config.base_url or "")
        span.set_attribute("honcho.workspace_id", config.workspace_id)

        if not config.api_key:
            span.set_attribute("honcho.health_result", "skipped_no_api_key")
            record_metric(
                "requests_total",
                1,
                {"operation": "health_check", "result": "skipped"},
            )
            LOG_MEM.warning("Honcho health check skipped: HONCHO_API_KEY is not set")
            return

        # Construct the client first — if this raises the error may carry
        # constructor arguments, so log a sanitised message without exc_info.
        try:
            honcho = Honcho(
                api_key=config.api_key,
                base_url=config.base_url,
                workspace_id=config.workspace_id,
                timeout=10.0,
                max_retries=1,
            )
        except Exception as exc:
            span.set_attribute("honcho.health_result", "failed")
            set_span_status(span, exc)
            record_metric(
                "requests_total",
                1,
                {"operation": "health_check", "result": "error"},
            )
            LOG_MEM.error(
                "Honcho health check failed — could not create client: %s",
                exc,
                exc_info=LOG_MEM.isEnabledFor(logging.DEBUG),
            )
            return

        # Lightweight call — any peer lookup proves connectivity.
        try:
            await honcho.aio.peers(size=1)
        except Exception as exc:
            span.set_attribute("honcho.health_result", "failed")
            set_span_status(span, exc)
            record_metric(
                "requests_total",
                1,
                {"operation": "health_check", "result": "error"},
            )
            LOG_MEM.error(
                "Honcho health check failed — API is unreachable: %s",
                exc,
                exc_info=LOG_MEM.isEnabledFor(logging.DEBUG),
            )
            return

        _health_ok = True
        span.set_attribute("honcho.health_result", "ok")
        record_metric(
            "requests_total",
            1,
            {"operation": "health_check", "result": "success"},
        )
        LOG_MEM.info("Honcho health check passed — API is reachable")


class Filter:
    """Toggleable Open WebUI Filter that retrieves and captures Honcho memory."""

    class Valves(BaseModel):
        priority: int = Field(default=0)
        search_top_k: int = Field(default=10, ge=1, le=100)
        search_max_distance: float = Field(default=0.5, ge=0, le=1)
        include_most_frequent: bool = True
        max_conclusions: int = Field(default=25, ge=1, le=100)
        max_context_chars: int = Field(default=8000, ge=500, le=50000)
        noise_patterns: list[str] = Field(default_factory=list)
        disable_default_noise_patterns: bool = False
        show_error_status: bool = True
        # Circuit breaker thresholds are shared across all three plugins
        # (filter, tools, actions) via module-level constants in core.py so
        # that every call site feeds the same counter.  Changing them here
        # would only affect the filter and create an inconsistency.
        # See _CIRCUIT_BREAKER_THRESHOLD / _CIRCUIT_BREAKER_COOLDOWN in core.py.

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True

    async def inlet(
        self,
        body: dict,
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
        __task__: str | None = None,
        __event_emitter__=None,
    ) -> dict:
        """Inject targeted memory before the model request while failing open."""
        if not _health_checked:
            await _run_health_check()
        original = body
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.filter.inlet") as span:
            try:
                span.set_attribute("honcho.has_task", bool(__task__))
                if __task__:
                    span.set_attribute("honcho.skip_reason", "internal_task")
                    LOG.debug("Honcho inlet/outlet skipped: internal task")
                    return body
                if not is_memory_globally_enabled(__user__):
                    span.set_attribute("honcho.globally_disabled", True)
                    span.set_attribute("honcho.skip_reason", "globally_disabled")
                    LOG.debug("Honcho inlet/outlet skipped: memory globally disabled")
                    return body
                if not circuit_allows():
                    span.set_attribute("honcho.skip_reason", "circuit_open")
                    LOG.warning("Honcho circuit breaker open — skipping Honcho call")
                    await self._error_status(__event_emitter__)
                    return body
                if _health_checked and not _health_ok and not _health_banner_emitted:
                    await self._degraded_banner(__event_emitter__)
                user_id, model_id, chat_id = request_context(__user__, __model__, __metadata__)
                user_peer_id = derive_id("usr", user_id, get_config().identity_salt)
                session_id = derive_id("ses", f"{user_id}\0{chat_id}", get_config().identity_salt)
                span.set_attribute("honcho.user_peer_id", user_peer_id)
                span.set_attribute("honcho.session_id", session_id)
                LOG.debug(
                    "Honcho inlet started user_peer_id=%s session_id=%s",
                    user_peer_id,
                    session_id,
                )
                latest = find_latest_message(body.get("messages", []), "user")
                query = extract_text((latest or {}).get("content"))
                span.set_attribute("honcho.query_length", len(query))
                if not query:
                    span.set_attribute("honcho.skip_reason", "empty_query")
                    return body
                service = HonchoService(get_config())
                card, representation = await service.targeted_context(
                    user_id,
                    model_id,
                    chat_id,
                    query,
                    top_k=self.valves.search_top_k,
                    max_distance=self.valves.search_max_distance,
                    include_most_frequent=self.valves.include_most_frequent,
                    max_conclusions=self.valves.max_conclusions,
                )
                inject_system_context(
                    body.setdefault("messages", []),
                    build_memory_block(card, representation, self.valves.max_context_chars),
                )
                record_result(success=True)
                injected = bool(card or representation)
                span.set_attribute("honcho.injected", injected)
                LOG.debug("Honcho inlet completed injected=%s", injected)
                return body
            except Exception as exc:
                record_result(success=False)
                set_span_status(span, exc)
                LOG.error("Honcho inlet failed: %s", exc, exc_info=LOG.isEnabledFor(logging.DEBUG))
                await self._error_status(__event_emitter__)
                return original

    async def outlet(
        self,
        body: dict,
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
        __task__: str | None = None,
        __event_emitter__=None,
    ) -> dict:
        """Persist the latest completed text turn while failing open."""
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.filter.outlet") as span:
            try:
                span.set_attribute("honcho.has_task", bool(__task__))
                if __task__:
                    span.set_attribute("honcho.skip_reason", "internal_task")
                    LOG.debug("Honcho inlet/outlet skipped: internal task")
                    return body
                if not is_memory_globally_enabled(__user__):
                    span.set_attribute("honcho.globally_disabled", True)
                    span.set_attribute("honcho.skip_reason", "globally_disabled")
                    LOG.debug("Honcho inlet/outlet skipped: memory globally disabled")
                    return body
                if not circuit_allows():
                    span.set_attribute("honcho.skip_reason", "circuit_open")
                    LOG.warning("Honcho circuit breaker open — skipping Honcho call")
                    await self._error_status(__event_emitter__)
                    return body
                user_id, model_id, chat_id = request_context(__user__, __model__, __metadata__)
                user_peer_id = derive_id("usr", user_id, get_config().identity_salt)
                session_id = derive_id("ses", f"{user_id}\0{chat_id}", get_config().identity_salt)
                span.set_attribute("honcho.user_peer_id", user_peer_id)
                span.set_attribute("honcho.session_id", session_id)
                LOG.debug(
                    "Honcho outlet started user_peer_id=%s session_id=%s",
                    user_peer_id,
                    session_id,
                )
                patterns = [
                    *([] if self.valves.disable_default_noise_patterns else DEFAULT_NOISE_PATTERNS),
                    *self.valves.noise_patterns,
                ]
                candidates = []
                for role in ("user", "assistant"):
                    message = find_latest_message(body.get("messages", []), role)
                    content = strip_memory_context(extract_text((message or {}).get("content")))
                    if message and content and not should_skip_message(content, patterns):
                        candidates.append({**message, "content": content})
                span.set_attribute("honcho.candidate_count", len(candidates))
                service = HonchoService(get_config())
                persisted = await service.add_completed_messages(
                    user_id, model_id, chat_id, candidates
                )
                record_result(success=True)
                span.set_attribute("honcho.persisted_count", persisted)
                LOG.debug("Honcho outlet completed persisted=%s", persisted)
            except Exception as exc:
                record_result(success=False)
                set_span_status(span, exc)
                LOG.error("Honcho outlet failed: %s", exc, exc_info=LOG.isEnabledFor(logging.DEBUG))
                await self._error_status(__event_emitter__)
            return body

    async def _error_status(self, emitter) -> None:
        if emitter and self.valves.show_error_status:
            await emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Memory is temporarily unavailable.",
                        "done": True,
                    },
                }
            )

    async def _degraded_banner(self, emitter) -> None:
        """Emit a persistent warning banner once when the health check fails.

        Uses ``done: False`` so the status stays visible in the chat UI
        rather than disappearing after a few seconds.  The module-level
        ``_health_banner_emitted`` flag prevents re-emission on every
        subsequent inlet call.
        """
        global _health_banner_emitted
        if not emitter or not self.valves.show_error_status:
            return
        _health_banner_emitted = True
        await emitter(
            {
                "type": "status",
                "data": {
                    "description": (
                        "Memory is temporarily unavailable. "
                        "Your chats will work normally but won't "
                        "remember past conversations. If this persists, "
                        "ask your administrator to check the server "
                        "configuration."
                    ),
                    "done": False,
                },
            }
        )
