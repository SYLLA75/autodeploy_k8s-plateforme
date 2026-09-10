"""
Reading the raw files produced by the collection chain.

The only module that knows the OTLP format. Everything downstream works on flat
records and never needs to know where they came from.

Two sources, two shapes:

    traces   what the programs report      ->  spans
    metrics  what the cluster measures     ->  samples

Both arrive as compressed JSON, laid out by date:

    otel-data/year=2026/month=09/day=09/hour=15/minute=19/traces_*.json.gz
    otel-data/year=2026/month=09/day=09/hour=15/minute=19/metrics_*.json.gz

OTLP nests deeply: a resource holds scopes, which hold spans. Everything is
flattened, copying the resource identity onto every span, because that identity
is what later attaches the span to a node of the graph.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# OTLP span kinds. Verified against real data: kind 2 spans are
# "POST /api/v1/..." and kind 3 spans are "SELECT ...".
INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER = 1, 2, 3, 4, 5


def _value(v: dict) -> Any:
    """OTLP wraps every value in a typed object: {"stringValue": "ts-food"}."""
    if not isinstance(v, dict) or not v:
        return None
    key, raw = next(iter(v.items()))
    if key == "intValue":
        return int(raw)
    if key == "doubleValue":
        return float(raw)
    if key == "boolValue":
        return bool(raw)
    return raw


def _attributes(items: list[dict] | None) -> dict[str, Any]:
    return {a["key"]: _value(a.get("value", {})) for a in (items or [])}


@dataclass(slots=True)
class Span:
    """
    One action performed by a program.

    The first four fields say WHO acted. They come from the resource, not from
    the span: a raw span says "I processed a message in 18 ms" without saying
    who did. The collector added the identity, and that identity is what binds
    the span to a node of the graph.
    """
    service: str | None
    pod_uid: str | None
    host: str | None
    namespace: str | None

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    kind: int
    start_ns: int
    end_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1_000_000

    # -- messaging ---------------------------------------------------------
    @property
    def messaging_system(self) -> str | None:
        return self.attributes.get("messaging.system")

    @property
    def queue_name(self) -> str | None:
        return self.attributes.get("messaging.destination.name")

    @property
    def messaging_operation(self) -> str | None:
        """"send" when publishing, "process" when consuming."""
        return self.attributes.get("messaging.operation.type")

    @property
    def is_broker_delivery(self) -> bool:
        """
        True when this consumption span describes the BROKER HANDING OVER the
        message, false when it describes the APPLICATION HANDLING it.

        Measured on the healthy campaign: exactly one span of each consumed
        pair carries network.peer.address, 710 pairs out of 710. The attribute
        separates the two roles; the duration does not.
        """
        return "network.peer.address" in self.attributes

    @property
    def message_key(self) -> tuple | None:
        """
        What identifies one MESSAGE, as opposed to one span.

        Verified trap. A single consumed message produces TWO spans, not one:
        same trace, same parent, same delivery tag, same messaging attributes.
        This was systematic — 710 out of 710 consumptions.

        THEY ARE NOT COPIES OF EACH OTHER. They describe two different things,
        and only one of them carries a network peer address:

            with network.peer.address     the broker handing the message over
                                          the wire — p50 0.090 ms
            without                       the application listener actually
                                          handling it — p50 6.201 ms

        Which is which is decided by the attribute, never by the duration: on
        5 of the 710 pairs the network span outlasted the handling. See
        Span.is_broker_delivery.

        Counting spans therefore doubles the consumed rate, which is half of the
        difference between what enters and what leaves a queue, the central
        quantity of this work. Measured over five real minutes:

            counting spans     : difference = -52 and -39   (absurd)
            counting messages  : difference =   1 and   0   (credible)

        A negative difference would mean a queue draining with nobody filling it.
        """
        if not self.queue_name:
            return None
        return (self.trace_id,
                self.attributes.get("messaging.rabbitmq.message.delivery_tag"),
                self.attributes.get("messaging.message.id"))


@dataclass(slots=True)
class Sample:
    """One number, measured at one instant, about one thing."""
    name: str
    value: float
    timestamp_ns: int
    labels: dict[str, Any] = field(default_factory=dict)

    @property
    def pod(self) -> str | None:
        return self.labels.get("pod")

    @property
    def namespace(self) -> str | None:
        return self.labels.get("namespace")

    @property
    def host(self) -> str | None:
        # Host metrics and container metrics do not name the host the same way.
        return (self.labels.get("node")
                or self.labels.get("kubernetes_io_hostname")
                or self.labels.get("instance"))

    @property
    def queue(self) -> str | None:
        return self.labels.get("queue")


def _text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def _documents(text: str) -> Iterator[dict]:
    """A file holds either one JSON document, or several, one per line."""
    text = text.strip()
    if not text:
        return
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def read_spans(path: str | Path) -> list[Span]:
    spans: list[Span] = []
    for doc in _documents(_text(path)):
        for block in doc.get("resourceSpans", []):
            ident = _attributes(block.get("resource", {}).get("attributes"))
            service = ident.get("service.name")
            pod_uid = ident.get("k8s.pod.uid")
            host = ident.get("k8s.node.name")
            namespace = ident.get("k8s.namespace.name")
            for scope in block.get("scopeSpans", []):
                for s in scope.get("spans", []):
                    spans.append(Span(
                        service=service, pod_uid=pod_uid, host=host,
                        namespace=namespace,
                        trace_id=s.get("traceId", ""),
                        span_id=s.get("spanId", ""),
                        parent_id=s.get("parentSpanId") or None,
                        name=s.get("name", ""),
                        kind=int(s.get("kind", 0) or 0),
                        start_ns=int(s.get("startTimeUnixNano", 0)),
                        end_ns=int(s.get("endTimeUnixNano", 0)),
                        attributes=_attributes(s.get("attributes")),
                    ))
    return spans


def read_samples(path: str | Path) -> list[Sample]:
    samples: list[Sample] = []
    for doc in _documents(_text(path)):
        for block in doc.get("resourceMetrics", []):
            for scope in block.get("scopeMetrics", []):
                for m in scope.get("metrics", []):
                    name = m.get("name", "")
                    # Everything arrives as a gauge, including cumulative _total
                    # counters — a consequence of the conversion from Prometheus.
                    # The declared shape therefore does NOT say whether a value
                    # is a level or a cumulative count; the name does.
                    for shape in ("gauge", "sum", "histogram", "summary"):
                        body = m.get(shape)
                        if not body:
                            continue
                        for dp in body.get("dataPoints", []):
                            value = dp.get("asDouble")
                            if value is None and "asInt" in dp:
                                value = float(dp["asInt"])
                            if value is None:
                                continue
                            samples.append(Sample(
                                name=name, value=float(value),
                                timestamp_ns=int(dp.get("timeUnixNano", 0)),
                                labels=_attributes(dp.get("attributes")),
                            ))
    return samples


def is_counter(name: str) -> bool:
    """A cumulative counter only goes up; a level goes up and down."""
    return name.endswith("_total") or name.endswith("_seconds_total")


def failed(span: Span) -> bool:
    """
    Whether a request failed.

    The response code decides; error.type answers for spans that carry no code.

    Two sites used to answer this question differently: the instance vector
    looked only at error.type, the calls relation looked at the code first. The
    same request could therefore count as failed on the edge and healthy on the
    node. Invisible on a healthy campaign — both read zero, 82 113 HTTP spans
    with not one failure — and it would have surfaced exactly during the fault
    injections, which is when the answer matters.
    """
    code = span.attributes.get("http.response.status_code")
    if code is None:
        return bool(span.attributes.get("error.type"))
    try:
        return int(code) >= 400
    except (TypeError, ValueError):
        return bool(span.attributes.get("error.type"))


def published_messages(spans: list[Span]) -> list[Span]:
    """
    Spans that publish a message, one per message.

    Deliberately NOT deduplicated. A publication carries neither delivery tag
    nor message id, so its only signature would be the trace, and one trace may
    legitimately publish two different messages. Verified: publications are not
    duplicated (87 publications for 88 consumed messages — a difference of one,
    not a factor of two).
    """
    return [s for s in spans
            if s.queue_name and s.messaging_operation == "send"]


def consumed_messages(spans: list[Span]) -> list[Span]:
    """
    Spans that consume a message, ONE PER MESSAGE, and always the one that
    describes the APPLICATION HANDLING it.

    Two things are settled here, not one.

    THE COUNT. Deduplication is mandatory: one consumed message emits two
    spans, so counting spans doubles the consumed rate — half of the difference
    between what enters and what leaves a queue, the central quantity of this
    work. See Span.message_key.

    WHICH ONE SURVIVES. The two spans do not last the same time, so keeping
    whichever arrived first left the duration to chance. The handling span is
    kept and the broker delivery discarded, because the quantity wanted is how
    long the replica took to process the message, not how long the wire took to
    deliver it. Measured on the healthy campaign, keeping both mixed two
    populations and reported a median of 0.283 ms where the true handling
    median was 6.201 ms — twenty-two times too small.
    """
    best: dict[tuple, Span] = {}
    order: list[tuple] = []
    for s in spans:
        if not (s.queue_name and s.messaging_operation == "process"):
            continue
        key = s.message_key
        if key not in best:
            best[key] = s
            order.append(key)
        elif best[key].is_broker_delivery and not s.is_broker_delivery:
            best[key] = s
    return [best[k] for k in order]
