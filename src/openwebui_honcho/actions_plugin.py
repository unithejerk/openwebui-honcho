"""
title: Honcho Memory Actions
description: Inspect and delete the current user's Honcho memory.
required_open_webui_version: 0.9.6
requirements: honcho-ai==2.1.2
version: 0.1.0
license: MIT
"""

import logging

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from openwebui_honcho.core import *


class Action:
    """User-triggered Actions for inspecting and deleting scoped Honcho memory."""

    actions = [
        {"id": "inspect_memory", "name": "Model's View of You"},
        {"id": "forget_current_chat", "name": "Forget Current Chat"},
        {"id": "forget_matching_memories", "name": "Forget Matching Memories"},
    ]

    class Valves(BaseModel):
        priority: int = 0
        maximum_matching_deletions: int = Field(default=10, ge=1, le=50)

    def __init__(self):
        self.valves = self.Valves()

    async def action(
        self,
        body: dict,
        __id__: str = "",
        __user__: dict | None = None,
        __model__: dict | str | None = None,
        __event_call__=None,
    ):
        """Dispatch the selected inspect or confirmed deletion Action."""
        tracer = get_tracer()
        with tracer.start_as_current_span("openwebui_honcho.actions.action") as span:
            span.set_attribute("honcho.action_id", __id__)
            LOG.debug("Honcho action started action_id=%s", __id__)
            metadata = {
                "chat_id": body.get("chat_id"),
                "message_id": body.get("id"),
                "session_id": body.get("session_id"),
            }
            try:
                ctx = request_context(__user__, __model__, metadata)
                if not circuit_allows():
                    span.set_attribute("honcho.skip_reason", "circuit_open")
                    return {"ok": False, "message": "Honcho memory is temporarily unavailable."}
                service = HonchoService(get_config())
                if __id__ == "inspect_memory":
                    import html as _html

                    user_id, model_id, _chat_id = ctx
                    self_card = await service.user_peer_card(user_id)
                    card, representation = await service.full_context(*ctx)

                    # Self-card section
                    self_facts_html = (
                        "".join(f"<li>{_html.escape(f)}</li>" for f in self_card)
                        if self_card
                        else "<li>No facts accumulated yet.</li>"
                    )

                    # Model-specific card section
                    model_facts_html = (
                        "".join(f"<li>{_html.escape(f)}</li>" for f in (card or []))
                        if card
                        else "<li>No model-specific facts.</li>"
                    )

                    rep_html = _html.escape(representation or "No representation available.")
                    model_name = _html.escape(model_id)

                    html_content = (
                        "<!doctype html><html><body style='font:14px sans-serif;padding:20px;max-width:720px'>"
                        "<h2>Honcho Memory</h2>"
                        "<p style='color:#666;font-size:12px'>"
                        "Manage memories in <a href='/settings' target='_top'>Settings → Personalization → Memory</a>"
                        "</p>"
                        "<h3>Your Facts (all models)</h3>"
                        f"<ul>{self_facts_html}</ul>"
                        f"<h3>What {model_name} Knows About You</h3>"
                        f"<ul>{model_facts_html}</ul>"
                        f"<h3>{model_name}'s Working Model</h3>"
                        f"<pre style='white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:6px'>{rep_html}</pre>"
                        "</body></html>"
                    )

                    record_result(success=True)
                    LOG.debug("Honcho action inspect_memory completed")
                    return HTMLResponse(
                        html_content,
                        headers={"Content-Disposition": "inline"},
                    )
                if __id__ == "forget_current_chat":
                    approved = await confirm(
                        __event_call__,
                        "Forget current chat?",
                        "This deletes the current Honcho session asynchronously. It does not guarantee complete user erasure.",
                    )
                    if not approved:
                        return {"ok": False, "message": "Cancelled."}
                    await service.delete_session(*ctx)
                    record_result(success=True)
                    LOG.debug("Honcho action forget_current_chat completed")
                    return {"ok": True, "message": "Current Honcho session deletion requested."}
                if __id__ == "forget_matching_memories":
                    query = await __event_call__(
                        {
                            "type": "input",
                            "data": {
                                "title": "Forget matching memories",
                                "message": "Enter a semantic search query for memories to delete.",
                                "placeholder": "e.g. old work preferences",
                            },
                        }
                    )
                    if not isinstance(query, str) or not query.strip():
                        return {"ok": False, "message": "Cancelled."}
                    matches = await service.search_conclusions(
                        *ctx,
                        query=query,
                        top_k=self.valves.maximum_matching_deletions,
                        distance=None,
                    )
                    record_result(success=True)
                    LOG.debug(
                        "Honcho action forget_matching_memories found %s matches", len(matches)
                    )
                    if not matches:
                        return {"ok": True, "message": "No matching conclusions found."}
                    preview = "\n".join(f"- {item.content}" for item in matches)
                    approved = await confirm(
                        __event_call__,
                        "Delete matching conclusions?",
                        f"The following conclusions will be deleted:\n\n{preview}",
                    )
                    if not approved:
                        return {"ok": False, "message": "Cancelled."}
                    deleted = await service.delete_conclusions(*ctx, conclusions=matches)
                    record_result(success=True)
                    LOG.debug(
                        "Honcho action forget_matching_memories deleted %s conclusions", deleted
                    )
                    return {"ok": True, "message": f"Deleted {deleted} conclusions."}
                return {"ok": False, "message": "Unknown Honcho action."}
            except Exception as exc:
                record_result(success=False)
                set_span_status(span, exc)
                LOG.error("Honcho action failed: %s", exc, exc_info=LOG.isEnabledFor(logging.DEBUG))
                return {"ok": False, "message": safe_tool_error(exc)}
