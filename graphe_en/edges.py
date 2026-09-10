"""
The edges of the graph: who talks to whom, in each window.

    calls         instance -> instance    5 numbers
    publishes     instance -> queue       1 number
    consumes      queue    -> instance    1 number
    executes on   instance -> host        0 numbers, purely structural

HOW A CALL IS RECONSTRUCTED

When one service calls another, two spans are written, not one:

    at the caller   a CLIENT span (kind 3)
    at the callee   a SERVER span (kind 2), whose parent is the CLIENT span

So SERVER spans are the starting point: walk up to the parent, and see which
instance wrote it. If it is another instance, that is an edge.

TWO PITFALLS, both measured and reported:

  1. The parent may be missing — its span fell in another window, or in a file
     that was not fetched. The proportion of parents found is the paper's
     resolution rate. It is printed: a missing edge distorts the graph
     silently, a printed rate cannot.

  2. The parent may be in the SAME instance. That is an internal call, not a
     relation between two nodes. It is set aside and counted separately.

THE "EXECUTES ON" EDGE CARRIES NOTHING. It is not useless for that: it is what
makes co-location observable, and co-location can explain a fault without the
edge itself carrying any measurement.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from features import quantile, ratio
from nodes import Node
from otlp import SERVER, Span, failed
from windows import Window

CALL_COLUMNS = ["call_rate", "latency_p50", "latency_p95", "latency_p99",
                "error_ratio"]
RATE_COLUMNS = ["rate"]

RELATIONS = {
    "calls":       ("instance", "instance", CALL_COLUMNS),
    "publishes":   ("instance", "queue", RATE_COLUMNS),
    "consumes":    ("queue", "instance", RATE_COLUMNS),
    "executes_on": ("instance", "host", []),
}


@dataclass(slots=True)
class Edge:
    relation: str
    source: str                  # key of the origin node
    target: str                  # key of the destination node
    columns: list[str] = field(default_factory=list)
    values: list[float | None] = field(default_factory=list)


def build(window: Window, nodes: dict[str, Node], width_s: float,
          eta: float, quantiles: tuple) -> tuple[list[Edge], dict]:
    edges: list[Edge] = []
    known = set(nodes)

    by_id = {s.span_id: s for s in window.spans if s.span_id}
    served = [s for s in window.spans if s.kind == SERVER and s.parent_id]
    grouped: dict[tuple[str, str], list[Span]] = defaultdict(list)
    resolved = orphaned = internal = out_of_scope = 0

    for s in served:
        parent = by_id.get(s.parent_id)
        if parent is None:
            orphaned += 1
            continue
        resolved += 1
        if parent.pod_uid == s.pod_uid:
            internal += 1
            continue
        if parent.pod_uid not in known or s.pod_uid not in known:
            out_of_scope += 1
            continue
        grouped[(parent.pod_uid, s.pod_uid)].append(s)

    for (source, target), group in grouped.items():
        latencies = [s.duration_ns / 1e6 for s in group]
        edges.append(Edge("calls", source, target, CALL_COLUMNS, [
            ratio(len(group) / eta, width_s),
            *[quantile(latencies, q) for q in quantiles],
            ratio(sum(1 for s in group if failed(s)), len(group)),
        ]))

    for relation, group, towards_queue in (
            ("publishes", window.published, True),
            ("consumes", window.consumed, False)):
        counts: Counter = Counter()
        for s in group:
            if not (s.pod_uid and s.queue_name):
                continue
            queue_key = f"queue:{s.queue_name}"
            if s.pod_uid not in known or queue_key not in known:
                continue
            counts[(s.pod_uid, queue_key)] += 1
        for (pod, queue_key), n in counts.items():
            source, target = ((pod, queue_key) if towards_queue
                              else (queue_key, pod))
            edges.append(Edge(relation, source, target, RATE_COLUMNS,
                              [ratio(n / eta, width_s)]))

    for key, node in nodes.items():
        if node.kind != "instance" or not node.host:
            continue
        target = f"host:{node.host}"
        if target in known:
            edges.append(Edge("executes_on", key, target, [], []))

    total_parents = resolved + orphaned
    report = {
        "server_spans_with_parent": total_parents,
        "parents_resolved": resolved,
        "parents_missing": orphaned,
        "resolution": resolved / total_parents if total_parents else None,
        "internal_calls": internal,
        "out_of_scope": out_of_scope,
    }
    return edges, report
