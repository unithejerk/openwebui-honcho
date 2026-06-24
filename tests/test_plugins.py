import asyncio
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_filter_fails_open(monkeypatch):
    module = importlib.import_module("openwebui_honcho.filter_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)

    async def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(module.HonchoService, "targeted_context", fail)
    body = {"messages": [{"role": "user", "content": "hello"}]}
    result = await module.Filter().inlet(
        body,
        __user__={"id": "u", "settings": {"memory": True}},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": ["honcho_memory"]},
    )
    assert result == body


@pytest.mark.asyncio
async def test_filter_disabled_by_default_when_no_memory_setting(monkeypatch):
    module = importlib.import_module("openwebui_honcho.filter_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    called = False

    async def retrieve(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(module.HonchoService, "targeted_context", retrieve)
    body = {"messages": [{"role": "user", "content": "hello"}]}
    result = await module.Filter().inlet(
        body,
        __user__={"id": "u"},  # no settings.memory key
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": ["honcho_memory"]},
    )
    assert result == body
    assert not called


@pytest.mark.asyncio
async def test_tools_require_active_filter(monkeypatch):
    module = importlib.import_module("openwebui_honcho.tools_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    result = await module.Tools().honcho_context(
        __user__={"id": "u"},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": []},
    )
    assert "disabled for this chat" in result


@pytest.mark.asyncio
async def test_outlet_skips_temp_chats(monkeypatch):
    module = importlib.import_module("openwebui_honcho.filter_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    called = False

    async def add(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(module.HonchoService, "add_completed_messages", add)
    body = {"messages": [{"id": "1", "role": "user", "content": "hello"}]}
    assert (
        await module.Filter().outlet(
            body,
            __user__={"id": "u"},
            __model__={"id": "m"},
            __metadata__={"chat_id": "local:x"},
        )
        == body
    )
    assert not called


@pytest.mark.asyncio
async def test_filter_skips_internal_tasks(monkeypatch):
    module = importlib.import_module("openwebui_honcho.filter_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    called = False

    async def retrieve(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(module.HonchoService, "targeted_context", retrieve)
    body = {"messages": [{"role": "user", "content": "hello"}]}
    assert (
        await module.Filter().inlet(
            body,
            __user__={"id": "u"},
            __model__={"id": "m"},
            __metadata__={"chat_id": "c"},
            __task__="title_generation",
        )
        == body
    )
    assert not called


@pytest.mark.asyncio
async def test_tools_respect_global_memory_toggle(monkeypatch):
    module = importlib.import_module("openwebui_honcho.tools_plugin")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    result = await module.Tools().honcho_context(
        __user__={"id": "u", "settings": {"memory": False}},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": ["honcho_memory"]},
    )
    assert "disabled globally" in result


def test_memory_route_map_is_complete(monkeypatch):
    """All Open WebUI memory endpoints have Honcho replacements."""
    import importlib
    import sys
    import types

    from pydantic import BaseModel

    class FakeRoute:
        def __init__(self, path, methods):
            self.path = path
            self.path_format = path
            self.methods = methods
            self.endpoint = None
            self.dependant = None
            self.dependencies = []
            self._flat_dependant = None

    class FakeApp:
        routes = [
            FakeRoute("/api/v1/memories/", {"GET"}),
            FakeRoute("/api/v1/memories/add", {"POST"}),
            FakeRoute("/api/v1/memories/query", {"POST"}),
            FakeRoute("/api/v1/memories/reset", {"POST"}),
            FakeRoute("/api/v1/memories/delete/user", {"DELETE"}),
            FakeRoute("/api/v1/memories/{memory_id}/update", {"POST"}),
            FakeRoute("/api/v1/memories/{memory_id}", {"DELETE"}),
        ]

    def fake_get_dependant(*args, **kwargs):
        return SimpleNamespace(dependencies=[])

    def fake_get_flat_dependant(*args, **kwargs):
        return None

    def fake_get_parameterless_sub_dependant(*args, **kwargs):
        return None

    import fastapi.dependencies.utils as dep_utils

    monkeypatch.setattr(dep_utils, "get_dependant", fake_get_dependant)
    monkeypatch.setattr(dep_utils, "get_flat_dependant", fake_get_flat_dependant)
    monkeypatch.setattr(
        dep_utils, "get_parameterless_sub_dependant", fake_get_parameterless_sub_dependant
    )

    # Create fake open_webui package tree so the guarded imports succeed.
    fake_main = types.SimpleNamespace(app=FakeApp())
    fake_auth = types.SimpleNamespace(get_verified_user=lambda: None)
    fake_utils = types.SimpleNamespace(auth=fake_auth)

    class AddMemoryForm(BaseModel):
        content: str

    class QueryMemoryForm(BaseModel):
        content: str
        k: int | None = 1

    fake_memories = types.SimpleNamespace(
        AddMemoryForm=AddMemoryForm, QueryMemoryForm=QueryMemoryForm
    )
    fake_routers = types.SimpleNamespace(memories=fake_memories)
    fake_open_webui = types.SimpleNamespace(main=fake_main, utils=fake_utils, routers=fake_routers)

    sys.modules["open_webui"] = fake_open_webui
    sys.modules["open_webui.main"] = fake_main
    sys.modules["open_webui.utils"] = fake_utils
    sys.modules["open_webui.utils.auth"] = fake_auth
    sys.modules["open_webui.routers"] = fake_routers
    sys.modules["open_webui.routers.memories"] = fake_memories

    monkeypatch.setenv("HONCHO_API_KEY", "sk-test")
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)

    # Ensure a fresh RuntimeConfig is loaded with the API key present.
    import openwebui_honcho.core as core_module

    core_module._config = None

    # Reload filter_plugin with the fake environment so _HAS_OPENWEBUI is True.
    import openwebui_honcho.filter_plugin as module

    importlib.reload(module)

    replaced = []
    for route in module.app.routes:
        if route.endpoint is not None:
            replaced.append((route.path, route.endpoint.__name__))

    assert len(replaced) == 7
    paths = {r[0] for r in replaced}
    assert "/api/v1/memories/reset" in paths
    assert "/api/v1/memories/{memory_id}/update" in paths


@pytest.mark.asyncio
async def test_memory_routes_require_config(monkeypatch):
    """Memory route handlers return a clear 503 when identity config is missing."""
    import importlib
    import sys
    import types

    from fastapi import HTTPException
    from pydantic import BaseModel

    import openwebui_honcho.core as core_module

    core_module._config = None

    class FakeUser:
        id = "user-1"

    fake_auth = types.SimpleNamespace(get_verified_user=lambda: FakeUser())
    fake_utils = types.SimpleNamespace(auth=fake_auth)

    class AddMemoryForm(BaseModel):
        content: str

    class QueryMemoryForm(BaseModel):
        content: str
        k: int | None = 1

    fake_memories = types.SimpleNamespace(
        AddMemoryForm=AddMemoryForm, QueryMemoryForm=QueryMemoryForm
    )
    fake_routers = types.SimpleNamespace(memories=fake_memories)
    fake_open_webui = types.SimpleNamespace(
        main=types.SimpleNamespace(app=types.SimpleNamespace(routes=[])),
        utils=fake_utils,
        routers=fake_routers,
    )
    for k, v in [
        ("open_webui", fake_open_webui),
        ("open_webui.main", fake_open_webui.main),
        ("open_webui.utils", fake_utils),
        ("open_webui.utils.auth", fake_auth),
        ("open_webui.routers", fake_routers),
        ("open_webui.routers.memories", fake_memories),
    ]:
        sys.modules[k] = v

    # Ensure no salt is present.
    monkeypatch.delenv("OPENWEBUI_HONCHO_IDENTITY_SALT", raising=False)
    monkeypatch.setenv("HONCHO_API_KEY", "sk-test")

    import openwebui_honcho.filter_plugin as module

    importlib.reload(module)

    with pytest.raises(HTTPException) as exc_info:
        await module._honcho_get_memories()
    assert exc_info.value.status_code == 503
    assert "Honcho memory is not configured" in exc_info.value.detail


def test_install_dry_run_makes_no_requests(monkeypatch, tmp_path):
    """--dry-run does not call the Open WebUI API."""
    import sys

    import scripts.install as install_module

    calls = []

    class NoopResponse:
        status_code = 200

        def json(self):
            return {}

        def raise_for_status(self):
            pass

    def capture_request(*args, **kwargs):
        calls.append((args, kwargs))
        return NoopResponse()

    monkeypatch.setattr("requests.get", capture_request)
    monkeypatch.setattr("requests.post", capture_request)
    monkeypatch.setattr(
        sys,
        "argv",
        ["install.py", "--base-url", "http://localhost:3000", "--api-key", "sk-test", "--dry-run"],
    )
    # Ensure dist files exist.
    for plugin in install_module.PLUGINS:
        assert (install_module.DIST / plugin["file"]).exists()

    install_module.main()
    assert not calls


@pytest.mark.asyncio
async def test_honcho_query_memory_uses_semantic_context(monkeypatch):
    """The query memory endpoint uses user_peer.aio.context with search_query."""
    import importlib

    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    monkeypatch.setenv("HONCHO_API_KEY", "sk-test")

    module = importlib.import_module("openwebui_honcho.filter_plugin")

    class FakeContext:
        representation = "Loves sushi"
        peer_card = []

    class FakePeerAio:
        async def context(self, **kwargs):
            assert kwargs.get("search_query") == "food"
            return FakeContext()

        async def card(self):
            return []

    class FakePeer:
        aio = FakePeerAio()

    async def fake_get_user_peer(user_id):
        return FakePeer()

    service = module.HonchoService(module.get_config())
    monkeypatch.setattr(service, "_get_user_peer", fake_get_user_peer)
    result = await service.query_user_peer_card("u1", query="food", top_k=3)
    assert result == ["Loves sushi"]


@pytest.mark.asyncio
async def test_honcho_session_uses_roles(monkeypatch):
    """honcho_session formats messages with user/assistant roles, not peer ids."""
    import importlib

    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)

    tools_module = importlib.import_module("openwebui_honcho.tools_plugin")

    class Msg:
        def __init__(self, peer_id, content):
            self.peer_id = peer_id
            self.content = content

    class FakeContext:
        summary = None
        peer_card = None
        peer_representation = None
        messages = [Msg("usr_abc", "hello"), Msg("ast_def", "hi there")]

    class FakePeer:
        def __init__(self, peer_id):
            self.id = peer_id
            self.aio = None

    class FakeService:
        async def resources(self, *args):
            return FakePeer("usr_abc"), FakePeer("ast_def"), None, None

        async def session_context(self, *args, **kwargs):
            return FakeContext()

    tools = tools_module.Tools()

    monkeypatch.setattr(
        tools,
        "_service_and_context",
        lambda *args, **kwargs: (FakeService(), ("u", "m", "c")),
    )
    result = await tools.honcho_session(
        __user__={"id": "u", "settings": {"memory": True}},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": ["honcho_memory"]},
    )
    assert "user: hello" in result
    assert "assistant: hi there" in result
    assert "usr_abc" not in result
    assert "ast_def" not in result


@pytest.mark.asyncio
async def test_self_card_edits_are_serialized(monkeypatch):
    """edit_user_peer_card serializes concurrent edits per user."""
    from openwebui_honcho.core import HonchoService, RuntimeConfig

    SALT = "a" * 32
    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    card = ["a"]

    class FakePeerAio:
        async def card(self):
            return list(card)

        async def set_card(self, facts):
            card[:] = facts
            return card

    class FakePeer:
        aio = FakePeerAio()

    async def fake_get_user_peer(user_id):
        return FakePeer()

    monkeypatch.setattr(service, "_get_user_peer", fake_get_user_peer)

    async def appender(label):
        await service.edit_user_peer_card("u1", lambda c: c + [label])

    await asyncio.gather(appender("b"), appender("c"))
    assert set(card) == {"a", "b", "c"}


def test_generated_plugins_are_importable():
    root = Path(__file__).resolve().parents[1]
    for name in (
        "honcho_memory",
        "honcho_memory_tools",
        "honcho_memory_actions",
    ):
        spec = importlib.util.spec_from_file_location(name, root / "dist" / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
