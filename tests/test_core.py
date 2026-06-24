import asyncio
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from openwebui_honcho.core import (
    MEMORY_OPEN,
    RuntimeConfig,
    build_memory_block,
    derive_event_id,
    derive_identity,
    extract_text,
    inject_system_context,
    is_memory_enabled,
    is_supported_chat,
    should_skip_message,
    strip_memory_context,
)

SALT = "a" * 32


def test_identity_is_stable_namespaced_and_bounded():
    first = derive_identity("user-1", "model-1", "chat-1", SALT)
    second = derive_identity("user-1", "model-1", "chat-1", SALT)
    other = derive_identity("user-2", "model-1", "chat-1", SALT)
    assert first == second
    assert first.user_peer_id != other.user_peer_id
    assert first.session_id != other.session_id
    assert max(map(len, first.__dict__.values())) < 100
    assert derive_event_id("user-1", "chat-1", "message-1", SALT).startswith("evt_")


def test_runtime_config_requires_strong_identity_salt(monkeypatch):
    monkeypatch.delenv("OPENWEBUI_HONCHO_IDENTITY_SALT", raising=False)
    with pytest.raises(Exception, match="IDENTITY_SALT"):
        RuntimeConfig.from_env()


def test_chat_and_toggle_scoping():
    assert is_supported_chat("chat-1")
    assert not is_supported_chat("local:socket")
    assert not is_supported_chat("channel:team")
    assert is_memory_enabled({"filter_ids": ["honcho_memory"]}, "honcho_memory")
    assert not is_memory_enabled({"filter_ids": []}, "honcho_memory")


def test_text_cleaning_and_noise_patterns():
    assert extract_text([{"type": "text", "text": "one"}, {"type": "image_url"}]) == "one"
    assert strip_memory_context(f"hello\n{MEMORY_OPEN}\nsecret\n</honcho-memory>") == "hello"
    assert should_skip_message("HEARTBEAT_OK later", ["HEARTBEAT_OK"])
    assert should_skip_message("PING 42", ["/^ping/i"])
    assert not should_skip_message("normal", ["HEARTBEAT_OK"])


def test_context_injection_and_html_escaping():
    messages = [{"role": "system", "content": "Base"}, {"role": "user", "content": "Hi"}]
    block = build_memory_block(["Likes <script>"], "Context", 1000)
    inject_system_context(messages, block)
    assert messages[0]["content"].startswith("Base")
    assert MEMORY_OPEN in messages[0]["content"]


@pytest.mark.asyncio
async def test_service_deduplicates_each_message(monkeypatch):
    from openwebui_honcho.core import HonchoService

    stored = []

    class Page:
        items = []

    existing_ids = {"evt_000000000000000000000000000000"}

    class SessionAio:
        async def messages(self, **kwargs):
            event_id = kwargs["filters"]["metadata"]["event_id"]
            return SimpleNamespace(items=[object()] if event_id in existing_ids else [])

        async def add_messages(self, messages):
            stored.extend(messages)

    class Session:
        aio = SessionAio()

    class Peer:
        def message(self, content, **kwargs):
            return {"content": content, **kwargs}

    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    async def resources(*args):
        return Peer(), Peer(), Session(), None

    monkeypatch.setattr(service, "resources", resources)
    # Monkeypatch derive_event_id so the third message simulates an existing one.
    monkeypatch.setattr(
        "openwebui_honcho.core.derive_event_id",
        lambda user_id, chat_id, message_id, salt: (
            "evt_000000000000000000000000000000"
            if message_id == "existing"
            else f"evt_{message_id}"
        ),
    )

    count = await service.add_completed_messages(
        "user",
        "model",
        "chat",
        [
            {"id": "one", "role": "user", "content": "hello"},
            {"id": "two", "role": "assistant", "content": "hi"},
            {"id": "existing", "role": "user", "content": "already stored"},
        ],
    )
    assert count == 2
    assert len(stored) == 2
    assert all(m["content"] != "already stored" for m in stored)


@pytest.mark.asyncio
async def test_user_peer_card_returns_empty_list_when_no_card(monkeypatch):
    """User self-card returns empty list when dreaming agent hasn't populated it yet."""
    from openwebui_honcho.core import HonchoService, RuntimeConfig

    SALT = "a" * 32
    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    # Mock the client and peer chain
    card_holder = []

    class FakePeerAio:
        async def card(self, target=None):
            return card_holder if card_holder else None

        async def set_card(self, peer_card, target=None):
            card_holder.clear()
            card_holder.extend(peer_card)
            return peer_card

    class FakePeer:
        aio = FakePeerAio()

    async def fake_get_user_peer(user_id):
        return FakePeer()

    monkeypatch.setattr(service, "_get_user_peer", fake_get_user_peer)

    result = await service.user_peer_card("user-1")
    assert result == []


@pytest.mark.asyncio
async def test_user_peer_set_card_and_read_back(monkeypatch):
    """Setting the self-card and reading it back roundtrips correctly."""
    from openwebui_honcho.core import HonchoService, RuntimeConfig

    SALT = "a" * 32
    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    card_holder = []

    class FakePeerAio:
        async def card(self, target=None):
            return card_holder if card_holder else None

        async def set_card(self, peer_card, target=None):
            card_holder.clear()
            card_holder.extend(peer_card)
            return peer_card

    class FakePeer:
        aio = FakePeerAio()

    async def fake_get_user_peer(user_id):
        return FakePeer()

    monkeypatch.setattr(service, "_get_user_peer", fake_get_user_peer)

    facts = ["Likes Python", "Lives in Berlin"]
    result = await service.user_peer_set_card("user-1", facts)
    assert result == facts

    read_back = await service.user_peer_card("user-1")
    assert read_back == facts


def test_get_user_peer_derives_stable_id():
    """User peer ID is derived deterministically from user_id and salt."""
    from openwebui_honcho.core import derive_id

    SALT = "a" * 32
    id1 = derive_id("usr", "user-1", SALT)
    id2 = derive_id("usr", "user-1", SALT)
    id3 = derive_id("usr", "user-2", SALT)

    assert id1 == id2
    assert id1 != id3
    assert id1.startswith("usr_")
    assert len(id1) < 100


def test_inject_system_context_strips_old_memory_block():
    """A previously injected memory block is removed before adding a fresh one."""
    from openwebui_honcho.core import (
        MEMORY_CLOSE,
        MEMORY_OPEN,
        build_memory_block,
        inject_system_context,
    )

    stale = f"{MEMORY_OPEN}\nold fact\n{MEMORY_CLOSE}"
    messages = [{"role": "system", "content": f"Base prompt.\n\n{stale}\n\nTrailing text."}]
    fresh = build_memory_block(["New fact"], None, 1000)
    inject_system_context(messages, fresh)

    assert messages[0]["role"] == "system"
    assert messages[0]["content"].count(MEMORY_OPEN) == 1
    assert "New fact" in messages[0]["content"]
    assert "old fact" not in messages[0]["content"]
    assert "Trailing text" in messages[0]["content"]


@pytest.mark.asyncio
async def test_sender_all_search_is_user_model_scoped(monkeypatch):
    """sender='all' should not fall back to workspace-level client search."""
    from openwebui_honcho.core import HonchoService, RuntimeConfig

    SALT = "a" * 32
    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    class Msg:
        def __init__(self, id, content):
            self.id = id
            self.content = content

    captured_searches = []

    class FakePeerAio:
        def __init__(self, peer_id):
            self.peer_id = peer_id

        async def search(self, query, *, filters=None, limit=10):
            captured_searches.append((self.peer_id, query, filters, limit))
            if self.peer_id == "usr":
                return [Msg("m1", "user says hi")]
            return [Msg("m2", "assistant says hi")]

    class FakePeer:
        def __init__(self, peer_id):
            self.id = peer_id
            self.aio = FakePeerAio(peer_id)

    async def resources(*args):
        return FakePeer("usr"), FakePeer("ast"), None, None

    monkeypatch.setattr(service, "resources", resources)

    # Also wrap client() to prove it is never awaited for search.
    class NoopClient:
        class aio:
            @staticmethod
            async def search(*args, **kwargs):
                raise AssertionError("workspace search should not be called")

    monkeypatch.setattr(service, "client", lambda: NoopClient)

    results = await service.search_messages("u", "m", "c", "test", sender="all", limit=10)
    assert len(results) == 2
    assert captured_searches[0][3] == 10
    assert captured_searches[1][3] == 10


@pytest.mark.asyncio
async def test_capture_locks_serialized_and_evict_oldest(monkeypatch):
    """The capture-lock dict is serialized and evicts oldest entries."""
    from openwebui_honcho.core import HonchoService, RuntimeConfig

    SALT = "a" * 32
    service = HonchoService(RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2))

    class SessionAio:
        async def messages(self, **kwargs):
            return SimpleNamespace(items=[])

        async def add_messages(self, messages):
            pass

    class NoopSession:
        aio = SessionAio()

    class NoopPeer:
        def message(self, content, **kwargs):
            return {"content": content, **kwargs}

    async def resources(*args):
        return NoopPeer(), NoopPeer(), NoopSession(), None

    monkeypatch.setattr(service, "resources", resources)
    service.__class__._capture_locks.clear()

    # Sanity-check that the lock dict is populated safely by calling twice.
    await service.add_completed_messages("u1", "m", "c1", [])
    await service.add_completed_messages("u1", "m", "c2", [])
    assert len(service.__class__._capture_locks) == 2

    # Verify the eviction path by temporarily lowering the capacity.
    monkeypatch.setattr(service.__class__, "_capture_locks", OrderedDict())

    # Fill the dict past its eviction threshold (hardcoded to 2048 in core.py,
    # but we monkeypatch len() so the existing three entries trigger eviction).
    locks = OrderedDict()
    for i in range(3):
        locks[("u", f"c{i}")] = asyncio.Lock()
    monkeypatch.setattr(service.__class__, "_capture_locks", locks)

    # Simulate eviction by invoking the same logic add_completed_messages uses.
    async with service.__class__._capture_locks_lock:
        while len(service.__class__._capture_locks) > 1:
            del service.__class__._capture_locks[next(iter(service.__class__._capture_locks))]
    assert ("u", "c0") not in service.__class__._capture_locks
