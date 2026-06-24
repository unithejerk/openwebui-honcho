"""Tests for OpenTelemetry spans, metrics, and lifecycle logging."""

import importlib
import logging
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import openwebui_honcho.core as core

SALT = "x" * 32


@pytest.fixture
def telemetry(monkeypatch):
    """Wire core telemetry to in-memory span and metric exporters."""
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = tracer_provider.get_tracer("openwebui_honcho")

    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    meter = meter_provider.get_meter("openwebui_honcho")

    monkeypatch.setattr(core, "get_tracer", lambda: tracer)
    monkeypatch.setattr(core, "get_meter", lambda: meter)
    monkeypatch.setattr(core, "_metric_instruments", {})
    core._init_metrics()

    yield {"exporter": exporter, "reader": reader}


def _find_metric(reader, name, attributes):
    """Return the sum/count for the first matching metric data point."""
    data = reader.get_metrics_data()
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    if point.attributes == attributes:
                        return point.value if hasattr(point, "value") else point.count
    return None


def _service(config=None):
    return core.HonchoService(
        config or core.RuntimeConfig(None, None, "workspace", SALT, "honcho_memory", 30, 2)
    )


@pytest.mark.asyncio
async def test_full_context_records_success_span_and_metrics(monkeypatch, telemetry):
    service = _service()

    class FakeAio:
        async def context(self, **kwargs):
            return SimpleNamespace(peer_card=["fact"], representation="rep")

    class FakePeer:
        aio = FakeAio()

    async def resources(*args):
        return FakePeer(), FakePeer(), None, None

    monkeypatch.setattr(service, "resources", resources)
    await service.full_context("u", "m", "c")

    spans = telemetry["exporter"].get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "honcho.full_context"
    assert span.status.status_code == StatusCode.OK

    assert (
        _find_metric(
            telemetry["reader"],
            "honcho.memory_requests_total",
            {"operation": "full_context", "result": "success"},
        )
        == 1
    )
    assert (
        _find_metric(
            telemetry["reader"],
            "honcho.memory_operation_duration_seconds",
            {"operation": "full_context"},
        )
        == 1
    )


@pytest.mark.asyncio
async def test_full_context_records_error_span_and_metrics(monkeypatch, telemetry):
    service = _service()

    async def resources(*args):
        raise RuntimeError("honcho down")

    monkeypatch.setattr(service, "resources", resources)
    with pytest.raises(RuntimeError, match="honcho down"):
        await service.full_context("u", "m", "c")

    spans = telemetry["exporter"].get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "honcho.full_context"
    assert spans[0].status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in spans[0].events)

    assert (
        _find_metric(
            telemetry["reader"],
            "honcho.memory_requests_total",
            {"operation": "full_context", "result": "error"},
        )
        == 1
    )


def test_record_metric_routes_counter_and_histogram(telemetry):
    core.record_metric("requests_total", 1, {"operation": "test", "result": "success"})
    core.record_metric("operation_duration", 0.123, {"operation": "test"})

    assert (
        _find_metric(
            telemetry["reader"],
            "honcho.memory_requests_total",
            {"operation": "test", "result": "success"},
        )
        == 1
    )
    assert (
        _find_metric(
            telemetry["reader"],
            "honcho.memory_operation_duration_seconds",
            {"operation": "test"},
        )
        == 1
    )


@pytest.mark.asyncio
async def test_filter_inlet_logs_lifecycle(monkeypatch, caplog, telemetry):
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", SALT)
    module = importlib.import_module("openwebui_honcho.filter_plugin")

    class FakeService:
        def __init__(self, config):
            pass

        async def targeted_context(self, *args, **kwargs):
            return (["fact"], None)

    monkeypatch.setattr(module, "HonchoService", FakeService)
    caplog.set_level(logging.DEBUG, logger="openwebui_honcho")

    body = {"messages": [{"role": "user", "content": "hello"}]}
    result = await module.Filter().inlet(
        body,
        __user__={"id": "u", "settings": {"memory": True}},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c"},
    )
    assert result is body
    messages = [r.message for r in caplog.records]
    assert any("Honcho inlet started" in m for m in messages)
    assert any("Honcho inlet completed" in m for m in messages)


@pytest.mark.asyncio
async def test_tools_log_lifecycle(monkeypatch, caplog, telemetry):
    monkeypatch.setenv("OPENWEBUI_HONCHO_IDENTITY_SALT", SALT)
    tools_module = importlib.import_module("openwebui_honcho.tools_plugin")

    class FakeService:
        async def full_context(self, *args, **kwargs):
            return (["fact"], "representation")

    tools = tools_module.Tools()

    monkeypatch.setattr(
        tools,
        "_service_and_context",
        lambda *args, **kwargs: (FakeService(), ("u", "m", "c")),
    )
    caplog.set_level(logging.DEBUG, logger="openwebui_honcho")

    result = await tools.honcho_context(
        __user__={"id": "u", "settings": {"memory": True}},
        __model__={"id": "m"},
        __metadata__={"chat_id": "c", "filter_ids": ["honcho_memory"]},
    )
    assert "fact" in result
    messages = [r.message for r in caplog.records]
    assert any("Honcho tool honcho_context started" in m for m in messages)
    assert any("Honcho tool honcho_context completed" in m for m in messages)
