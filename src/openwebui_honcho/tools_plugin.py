"""
title: Honcho Memory Tools
description: Read-only, user-scoped Honcho memory tools.
required_open_webui_version: 0.9.6
requirements: honcho-ai==2.1.2
version: 0.1.0
license: MIT
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from openwebui_honcho.core import *


class Tools:
    """Read-only, chat-toggle-gated Honcho tools for the current user and model."""

    class Valves(BaseModel):
        output_character_limit: int = Field(default=12000, ge=1000, le=50000)

    def __init__(self):
        self.valves = self.Valves()

    def _service_and_context(self, __user__, __model__, __metadata__):
        config = get_config()
        if not is_memory_enabled(__metadata__, config.filter_id):
            raise ValueError("Honcho memory is disabled for this chat.")
        if not is_memory_globally_enabled(__user__):
            raise ValueError("Honcho memory is disabled globally.")
        if not circuit_allows():
            raise CircuitOpenError("Honcho is temporarily unavailable")
        return HonchoService(config), request_context(__user__, __model__, __metadata__)

    async def honcho_context(
        self,
        detail: Literal["card", "full"] = "card",
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """Get known user facts or the current model's full user representation.

        :param detail: ``"card"`` for the user's collected facts,
            ``"full"`` for the model's complete working representation
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.tools.honcho_context") as span:
            span.set_attribute("honcho.detail", detail)
            LOG.debug("Honcho tool honcho_context started detail=%s", detail)
            try:
                service, ctx = self._service_and_context(__user__, __model__, __metadata__)
                card, representation = await service.full_context(*ctx)
                result = format_context(card, representation if detail == "full" else None)
                record_result(success=True)
                span.set_attribute("honcho.has_result", bool(result))
                LOG.debug("Honcho tool honcho_context completed")
                return result[: self.valves.output_character_limit]
            except Exception as exc:
                record_result(success=False)
                LOG.error(
                    "Honcho tool honcho_context failed: %s",
                    exc,
                    exc_info=LOG.isEnabledFor(logging.DEBUG),
                )
                set_span_status(span, exc)
                return safe_tool_error(exc)

    async def honcho_search_conclusions(
        self,
        query: str,
        top_k: int = 10,
        max_distance: float = 0.5,
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """Search the current model's conclusions about the current user.

        :param query: What to search for in the derived facts
        :param top_k: Maximum number of results to return (1–100)
        :param max_distance: Semantic distance threshold, 0.0–1.0
            (lower = more relevant)
        """
        tracer = get_tracer()
        with tracer.start_as_current_span(
            "openwebui_honcho.tools.honcho_search_conclusions"
        ) as span:
            span.set_attribute("honcho.query_length", len(query))
            LOG.debug("Honcho tool honcho_search_conclusions started")
            try:
                service, ctx = self._service_and_context(__user__, __model__, __metadata__)
                results = await service.search_conclusions(
                    *ctx, query=query, top_k=min(max(top_k, 1), 100), distance=max_distance
                )
                text = "\n".join(f"- {item.content}" for item in results)
                record_result(success=True)
                span.set_attribute("honcho.result_count", len(results))
                LOG.debug("Honcho tool honcho_search_conclusions completed")
                return (text or "No matching conclusions found.")[
                    : self.valves.output_character_limit
                ]
            except Exception as exc:
                record_result(success=False)
                LOG.error(
                    "Honcho tool honcho_search_conclusions failed: %s",
                    exc,
                    exc_info=LOG.isEnabledFor(logging.DEBUG),
                )
                set_span_status(span, exc)
                return safe_tool_error(exc)

    async def honcho_search_messages(
        self,
        query: str,
        sender: Literal["user", "assistant", "all"] = "all",
        created_after: str | None = None,
        created_before: str | None = None,
        metadata: dict | None = None,
        limit: int = 10,
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """Search the user's raw messages across all sessions.

        Use this to find specific things the user or assistant actually said,
        as opposed to honcho_search_conclusions which searches derived facts.

        :param query: What to search for in the message text
        :param sender: ``"user"``, ``"assistant"``, or ``"all"``
        :param created_after: ISO datetime string, e.g. ``"2025-01-01T00:00:00Z"``
        :param created_before: ISO datetime string
        :param metadata: Dict of key-value pairs to filter by message metadata
        :param limit: Maximum number of results (1–100)
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.tools.honcho_search_messages") as span:
            span.set_attribute("honcho.sender", sender)
            span.set_attribute("honcho.query_length", len(query))
            LOG.debug("Honcho tool honcho_search_messages started sender=%s", sender)
            try:
                service, ctx = self._service_and_context(__user__, __model__, __metadata__)
                results = await service.search_messages(
                    *ctx,
                    query=query,
                    sender=sender,
                    created_after=created_after,
                    created_before=created_before,
                    metadata=metadata,
                    limit=min(max(limit, 1), 100),
                )
                if not results:
                    record_result(success=True)
                    span.set_attribute("honcho.result_count", 0)
                    LOG.debug("Honcho tool honcho_search_messages completed")
                    return "No matching messages found."
                lines = []
                for m in results:
                    ts = getattr(m, "created_at", "")
                    content = getattr(m, "content", "")
                    session = getattr(m, "session_id", "")
                    line = f"- [{ts}] {content}"
                    if sender == "all":
                        line += f"  (session: {session})"
                    lines.append(line)
                record_result(success=True)
                span.set_attribute("honcho.result_count", len(results))
                LOG.debug("Honcho tool honcho_search_messages completed")
                return "\n".join(lines)[: self.valves.output_character_limit]
            except Exception as exc:
                record_result(success=False)
                LOG.error(
                    "Honcho tool honcho_search_messages failed: %s",
                    exc,
                    exc_info=LOG.isEnabledFor(logging.DEBUG),
                )
                set_span_status(span, exc)
                return safe_tool_error(exc)

    async def honcho_session(
        self,
        include_messages: bool = True,
        include_summary: bool = True,
        search_query: str | None = None,
        token_limit: int = 4000,
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """Get memory from the current chat session only.

        :param include_messages: Whether to include recent messages
        :param include_summary: Whether to include a session summary
        :param search_query: Optional search term to filter messages
        :param token_limit: Maximum token budget (100–32000)
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.tools.honcho_session") as span:
            span.set_attribute("honcho.include_messages", include_messages)
            span.set_attribute("honcho.include_summary", include_summary)
            LOG.debug("Honcho tool honcho_session started")
            try:
                service, ctx = self._service_and_context(__user__, __model__, __metadata__)
                user_peer, assistant_peer, session, _ = await service.resources(*ctx)
                context = await service.session_context(
                    *ctx,
                    summary=include_summary,
                    tokens=min(max(token_limit, 100), 32000),
                    search_query=search_query,
                )
                sections = []
                if context.summary:
                    sections.append(f"## Summary\n\n{context.summary.content}")
                if context.peer_card:
                    sections.append(
                        "## User Profile\n\n" + "\n".join(f"- {x}" for x in context.peer_card)
                    )
                if context.peer_representation:
                    sections.append(f"## User Context\n\n{context.peer_representation}")
                if include_messages and context.messages:
                    role_by_peer = {user_peer.id: "user", assistant_peer.id: "assistant"}
                    lines = []
                    for m in context.messages:
                        role = role_by_peer.get(getattr(m, "peer_id", ""), "unknown")
                        lines.append(f"{role}: {getattr(m, 'content', '')}")
                    sections.append("## Recent Messages\n\n" + "\n\n".join(lines))
                record_result(success=True)
                span.set_attribute("honcho.message_count", len(context.messages or []))
                LOG.debug("Honcho tool honcho_session completed")
                return ("\n\n".join(sections) or "No session memory available.")[
                    : self.valves.output_character_limit
                ]
            except Exception as exc:
                record_result(success=False)
                LOG.error(
                    "Honcho tool honcho_session failed: %s",
                    exc,
                    exc_info=LOG.isEnabledFor(logging.DEBUG),
                )
                set_span_status(span, exc)
                return safe_tool_error(exc)

    async def honcho_ask(
        self,
        query: str,
        depth: Literal["quick", "thorough", "minimal", "medium", "max"] = "quick",
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """Ask Honcho a direct question about the current user.

        :param query: The question to ask about the user
        :param depth: Reasoning effort — ``"quick"`` (fastest),
            ``"thorough"`` (most thoughtful), ``"minimal"``, ``"medium"``,
            or ``"max"``
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.tools.honcho_ask") as span:
            span.set_attribute("honcho.query_length", len(query))
            span.set_attribute("honcho.depth", depth)
            LOG.debug("Honcho tool honcho_ask started depth=%s", depth)
            try:
                service, ctx = self._service_and_context(__user__, __model__, __metadata__)
                depth_map = {
                    "quick": "low",
                    "thorough": "high",
                    "minimal": "minimal",
                    "medium": "medium",
                    "max": "max",
                }
                result = await service.ask(
                    *ctx, query=query, reasoning_level=depth_map.get(depth, "low")
                )
                record_result(success=True)
                span.set_attribute("honcho.result_length", len(result))
                LOG.debug("Honcho tool honcho_ask completed")
                return result[: self.valves.output_character_limit]
            except Exception as exc:
                record_result(success=False)
                LOG.error(
                    "Honcho tool honcho_ask failed: %s",
                    exc,
                    exc_info=LOG.isEnabledFor(logging.DEBUG),
                )
                set_span_status(span, exc)
                return safe_tool_error(exc)
