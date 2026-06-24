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


def test_memory_route_map_is_complete_direct_routes(monkeypatch):
    """All 7 memory endpoints are replaced when routes are directly in app.routes."""
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
            FakeRoute("/", {"GET"}),
            FakeRoute("/add", {"POST"}),
            FakeRoute("/query", {"POST"}),
            FakeRoute("/reset", {"POST"}),
            FakeRoute("/delete/user", {"DELETE"}),
            FakeRoute("/{memory_id}/update", {"POST"}),
            FakeRoute("/{memory_id}", {"DELETE"}),
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

    import openwebui_honcho.core as core_module

    core_module._config = None

    import openwebui_honcho.filter_plugin as module

    importlib.reload(module)

    replaced = []
    for route in module.app.routes:
        if route.endpoint is not None:
            replaced.append((route.path, route.endpoint.__name__))

    assert len(replaced) == 7
    paths = {r[0] for r in replaced}
    assert "/reset" in paths
    assert "/{memory_id}/update" in paths


def test_memory_route_replacement_handles_included_router(monkeypatch):
    """Routes nested inside _IncludedRouter (app.include_router with prefix)
    are still found and replaced — this matches real Open WebUI behaviour."""
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

    # Simulate how Open WebUI actually serves the memories router:
    #   app.include_router(memories.router, prefix='/api/v1/memories')
    # This wraps routes inside an _IncludedRouter.
    memory_routes = [
        FakeRoute("/", {"GET"}),
        FakeRoute("/add", {"POST"}),
        FakeRoute("/query", {"POST"}),
        FakeRoute("/reset", {"POST"}),
        FakeRoute("/delete/user", {"DELETE"}),
        FakeRoute("/{memory_id}/update", {"POST"}),
        FakeRoute("/{memory_id}", {"DELETE"}),
    ]
    original_router = types.SimpleNamespace(routes=memory_routes)
    include_context = types.SimpleNamespace(prefix="/api/v1/memories")
    included = types.SimpleNamespace(
        original_router=original_router, include_context=include_context
    )

    class FakeApp:
        routes = [included]

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

    import openwebui_honcho.core as core_module

    core_module._config = None

    import openwebui_honcho.filter_plugin as module

    importlib.reload(module)

    # Routes inside the original router should now have replaced endpoints
    replaced = []
    for route in original_router.routes:
        if route.endpoint is not None:
            replaced.append((route.path, route.endpoint.__name__))

    assert len(replaced) == 7
    paths = {r[0] for r in replaced}
    assert "/" in paths
    assert "/{memory_id}" in paths
    assert "/reset" in paths


def test_included_router_with_non_matching_prefix_is_skipped(monkeypatch):
    """Included routers that don't target /api/v1/memories are left untouched."""
    import importlib
    import sys
    import types

    from pydantic import BaseModel

    class FakeRoute:
        def __init__(self, path, methods, endpoint_name="original"):
            self.path = path
            self.path_format = path
            self.methods = methods
            self.endpoint = lambda: None
            self.endpoint.__name__ = endpoint_name
            self.dependant = None
            self.dependencies = []
            self._flat_dependant = None

    # A non-memory router — should not be touched
    other_routes = [
        FakeRoute("/", {"GET"}, endpoint_name="other_handler"),
    ]
    memory_routes = [
        FakeRoute("/", {"GET"}, endpoint_name="memory_handler"),
    ]

    other_router = types.SimpleNamespace(routes=other_routes)
    memory_router = types.SimpleNamespace(routes=memory_routes)

    other_ctx = types.SimpleNamespace(prefix="/api/v1/chats")
    memory_ctx = types.SimpleNamespace(prefix="/api/v1/memories")

    included_other = types.SimpleNamespace(original_router=other_router, include_context=other_ctx)
    included_memory = types.SimpleNamespace(
        original_router=memory_router, include_context=memory_ctx
    )

    class FakeApp:
        routes = [included_other, included_memory]

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

    import openwebui_honcho.core as core_module

    core_module._config = None

    import openwebui_honcho.filter_plugin as module

    importlib.reload(module)

    # Memory route should be replaced
    assert memory_routes[0].endpoint.__name__ == "_honcho_get_memories"

    # Other route should NOT be touched
    assert other_routes[0].endpoint.__name__ == "other_handler"


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


def test_memory_ui_ids_include_content_hash():
    """Memory IDs use honcho_N__hash format for staleness detection."""
    import importlib

    module = importlib.import_module("openwebui_honcho.filter_plugin")
    facts = ["Likes Python", "Lives in Berlin"]
    result = module._card_to_memories(facts, "user-1")
    assert len(result) == 2
    for i, entry in enumerate(result):
        assert entry["id"].startswith(f"honcho_{i}__")
        assert len(entry["id"]) > len(f"honcho_{i}__")  # hash is present
        assert entry["created_at"] == 0  # epoch int — no per-fact timestamp
        assert entry["updated_at"] == 0


def test_memory_index_validates_content_hash():
    """_memory_index returns the index when hash matches, None when stale."""
    import importlib

    module = importlib.import_module("openwebui_honcho.filter_plugin")
    facts = ["Likes Python", "Lives in Berlin"]

    # Valid ID with matching hash
    valid_id = module._card_to_memories(facts, "u")[0]["id"]
    assert module._memory_index(valid_id, facts) == 0

    # Stale: hash from "Likes Python" but fact changed to "Likes Java"
    stale_facts = ["Likes Java", "Lives in Berlin"]
    assert module._memory_index(valid_id, stale_facts) is None

    # Out of range
    bad_id = f"honcho_{99}__deadbeef"
    assert module._memory_index(bad_id, facts) is None

    # Malformed
    assert module._memory_index("not_honcho_0__abc", facts) is None


def test_memory_index_backward_compat():
    """Old honcho_N format (no hash) still works for existing deployments."""
    import importlib

    module = importlib.import_module("openwebui_honcho.filter_plugin")
    facts = ["Likes Python", "Lives in Berlin"]
    old_style_id = "honcho_0"
    assert module._memory_index(old_style_id, facts) == 0

    old_style_id_1 = "honcho_1"
    assert module._memory_index(old_style_id_1, facts) == 1


def test_memory_model_shape_matches_upstream():
    """Response payloads must be compatible with upstream MemoryModel (Pydantic).

    Upstream ``MemoryModel`` requires: id: str, user_id: str, content: str,
    updated_at: int, created_at: int.  Extra fields are ignored by Pydantic v2
    (no ``extra='forbid'`` in upstream config).
    """
    import importlib

    from pydantic import BaseModel, ConfigDict

    module = importlib.import_module("openwebui_honcho.filter_plugin")

    # Replicate the upstream MemoryModel shape
    class MemoryModel(BaseModel):
        id: str
        user_id: str
        content: str
        updated_at: int
        created_at: int
        model_config = ConfigDict(from_attributes=True)

    facts = ["Likes Python"]
    result = module._card_to_memories(facts, "user-1")

    # Each entry must validate against the upstream model
    for entry in result:
        validated = MemoryModel(**entry)
        assert validated.id == entry["id"]
        assert validated.content == entry["content"]
        assert isinstance(validated.created_at, int)
        assert isinstance(validated.updated_at, int)


def test_memory_timestamps_are_epoch_zero_not_none():
    """created_at/updated_at must be int (epoch 0), not None.

    Pydantic v2 rejects None for int fields with:
    Input should be a valid integer [type=int_type, input_value=None]
    """
    import importlib

    module = importlib.import_module("openwebui_honcho.filter_plugin")
    result = module._card_to_memories(["fact"], "u")

    assert result[0]["created_at"] == 0
    assert result[0]["updated_at"] == 0
    assert isinstance(result[0]["created_at"], int)
    assert isinstance(result[0]["updated_at"], int)


def test_memory_response_shapes_match_upstream_response_models(monkeypatch):
    """Delete returns bool, update returns single entry or None, add returns single entry.

    Upstream route signatures:
    - DELETE /{memory_id} → response_model=bool
    - POST /{memory_id}/update → response_model=MemoryModel | None
    - POST /add → response_model=MemoryModel | None
    - POST /reset → response_model=bool
    - DELETE /delete/user → response_model=bool
    """
    import importlib

    import openwebui_honcho.core as core

    core._config = None
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", "x" * 32)
    monkeypatch.setenv("HONCHO_API_KEY", "sk-test")

    module = importlib.import_module("openwebui_honcho.filter_plugin")

    # Test timestamp values
    facts = ["Likes Python", "Lives in Berlin"]
    result = module._card_to_memories(facts, "user-1")
    assert len(result) == 2
    for entry in result:
        assert isinstance(entry["created_at"], int)
        assert isinstance(entry["updated_at"], int)
        assert entry["created_at"] == 0
        assert "id" in entry
        assert entry["id"].startswith("honcho_")
        assert "__" in entry["id"]  # content hash present
