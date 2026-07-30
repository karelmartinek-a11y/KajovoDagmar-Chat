from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from kajovodagmar.config import InfrastructureSettings

P = ParamSpec("P")
R = TypeVar("R")
_lock = Lock()
_configured = False


def configure_tracing(settings: InfrastructureSettings, component: str) -> None:
    global _configured
    with _lock:
        if _configured:
            return
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.telemetry_service_name,
                    "service.version": "1.0.0",
                    "service.instance.id": component,
                    "deployment.environment.name": settings.environment,
                    "kajovodagmar.specification_revision": "v0021",
                }
            )
        )
        if settings.otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
            )
        trace.set_tracer_provider(provider)
        _configured = True


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[trace.Span]:
    tracer = trace.get_tracer("kajovodagmar", "1.0.0")
    with tracer.start_as_current_span(name, attributes=attributes) as current:
        yield current


def traced(
    name: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    def decorate(
        function: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with span(name):
                return await function(*args, **kwargs)

        return wrapped

    return decorate
