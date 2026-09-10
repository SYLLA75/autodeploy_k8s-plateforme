"""
The values carried by each node.

    instance   18 numbers
    queue       6 numbers
    host        5 numbers

FIVE WAYS OF SUMMARISING a window (the paper's operators):

    last       the final value of the window          a level
    extreme    the minimum or maximum over the window a dip, a peak
    increase   how much a counter rose                a cumulative count
    quantile   the value below which q of the cases fall
    slope      the trend over H consecutive windows   a drift

Plus two combinations: a ratio (a/b) and a difference (a-b). A per-second rate
is a ratio: an increase divided by the window width.

THREE DELIBERATE DEPARTURES FROM THE PAPER, each of them measured:

  1. A queue's publish rate (component 3) was to come from the counter
     rabbitmq_queue_messages_published_total. THAT COUNTER DOES NOT EXIST on
     RabbitMQ 3.8 — verified, it is not among the exported metrics. It is
     therefore derived from publication spans, symmetrically to component 4,
     which the paper already reconstructs from consumption spans. This is an
     improvement: both rates are measured the same way, so their difference is
     homogeneous, whereas the original definition mixed a broker counter with a
     span count.

  2. "increase" is defined in the paper as last minus first. A counter reset by
     a restart would then yield a NEGATIVE value, that is, a negative rate.
     Increases between consecutive samples are summed instead, ignoring drops.
     Without a restart both formulas agree.

  3. A consumed message emits two identical spans; they are deduplicated,
     otherwise the consume rate doubles.

TWO CORRECTIONS TO THE CONSUMED-MESSAGE COUNT, both measured:

  A. process_rate IS GONE FROM THE INSTANCE VECTOR. It was component 4 there
     and component 1 of the consumption relation — the same quantity written
     twice, so a model weighted it twice. Worse, the two copies disagreed by a
     factor of exactly 2.00 over all 48 readings of the healthy campaign,
     because the vector counted spans while the relation counted messages.

     The quantity now lives on the consumption relation alone, where it
     belongs: a rate of messages from one queue to one replica. A node needing
     it sums its incoming consumption edges, which is what message passing
     does anyway. Checked before removing: no replica had a non-zero
     process_rate without a consumption edge, so nothing is lost.

     This is also what makes the paper's own ablation testable. Section 10.7
     predicts that removing the consumption relations degrades attribution;
     while the rate stayed in the vector that prediction could not fail.

  B. process_time NOW MEASURES HANDLING, NOT DELIVERY. The two spans of a
     consumed message are not copies: one is the broker handing the message
     over the wire, the other the application listener handling it. Mixing
     them put two populations in one distribution and reported a median of
     0.283 ms where the true handling median was 6.201 ms. See
     otlp.consumed_messages.

WHAT ETA IS WORTH. The paper corrects span counts by the sampling rate eta. The
chain is set to keep every trace (OTEL_TRACES_SAMPLER=parentbased_always_on), so
eta = 1 and the correction is neutral. The setting exists for the day sampling
is enabled to sustain load.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from nodes import Node, collect, directory
from otlp import SERVER, Sample, consumed_messages
from windows import Window

INSTANCE_COLUMNS = [
    "process_time_p50", "process_time_p95", "process_time_p99",
    "request_time_p50", "request_time_p95", "request_time_p99",
    "error_ratio",
    "cpu_throttle_ratio", "cpu_rate",
    "memory_used", "memory_slope", "memory_limit", "cpu_quota",
    "restarts",
    "rx_packets_dropped", "tx_packets_dropped", "rx_errors", "rx_bytes",
]
QUEUE_COLUMNS = ["backlog", "backlog_slope", "publish_rate", "consume_rate",
                 "rate_imbalance", "consumers"]
HOST_COLUMNS = ["cpu_pressure", "memory_pressure", "io_pressure",
                "memory_available_min", "cpu_busy"]

COLUMNS = {"instance": INSTANCE_COLUMNS, "queue": QUEUE_COLUMNS,
           "host": HOST_COLUMNS}

# Where the slope operator writes, per node kind: (source column, target column).
# Held BY NAME and resolved to positions here. They used to be written as bare
# indices, which meant that removing one column silently shifted them and wrote
# the slope into a neighbouring column instead.
SLOPE_BY_NAME = {"instance": ("memory_used", "memory_slope"),
                 "queue": ("backlog", "backlog_slope")}
SLOPE_SLOTS = {kind: (COLUMNS[kind].index(src), COLUMNS[kind].index(dst))
               for kind, (src, dst) in SLOPE_BY_NAME.items()}


# ------------------------------------------------------------ the operators
def last(series: list[tuple[int, float]]) -> float | None:
    return max(series, key=lambda x: x[0])[1] if series else None


def extreme(series: list[tuple[int, float]], which: str = "min") -> float | None:
    if not series:
        return None
    return (min if which == "min" else max)(v for _, v in series)


def increase(series: list[tuple[int, float]]) -> float | None:
    """
    How much a counter rose over the window.

    Rises between consecutive samples are summed. A drop means the counter
    restarted from zero, so it is not counted as a negative step.
    """
    if len(series) < 2:
        return 0.0 if series else None
    ordered = sorted(series)
    total = 0.0
    for (_, a), (_, b) in zip(ordered, ordered[1:]):
        total += (b - a) if b >= a else b
    return total


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    i = max(0, math.ceil(q * len(ordered)) - 1)
    return ordered[i]


def slope(series: list[float | None], horizon: int) -> float | None:
    """
    The trend over the last H windows.

    The only operator that leaves the window: it describes a slow drift that a
    single window cannot see.
    """
    y = [v for v in series[-horizon:] if v is not None]
    if len(y) < 2:
        return None
    n = len(y)
    mx = (n - 1) / 2
    my = sum(y) / n
    top = sum((i - mx) * (v - my) for i, v in enumerate(y))
    bottom = sum((i - mx) ** 2 for i in range(n))
    return top / bottom if bottom else None


def ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def difference(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


# ------------------------------------------------------- grouping samples
def _series(samples: list[Sample]) -> dict[tuple, list[tuple[int, float]]]:
    """
    One metric carries several parallel series, one per label set. Mixing them
    would corrupt every increase, so they are separated first.
    """
    out: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for s in samples:
        out[tuple(sorted(s.labels.items()))].append((s.timestamp_ns, s.value))
    return out


def _sum_increase(samples: list[Sample]) -> float | None:
    if not samples:
        return None
    return sum(v for v in (increase(s) for s in _series(samples).values())
               if v is not None)


def _sum_last(samples: list[Sample]) -> float | None:
    if not samples:
        return None
    return sum(v for v in (last(s) for s in _series(samples).values())
               if v is not None)


def _one_level_only(samples: list[Sample]) -> list[Sample]:
    """
    cAdvisor publishes two levels for one pod: one line per container, and one
    aggregate line with no container name. Adding them would count everything
    twice, so named containers win whenever there are any.
    """
    named = [s for s in samples if s.labels.get("container")]
    return named or samples


# ------------------------------------------------------------- the vectors
@dataclass(slots=True)
class Vector:
    node: Node
    columns: list[str]
    values: list[float | None] = field(default_factory=list)

    @property
    def completeness(self) -> float:
        return sum(1 for v in self.values if v is not None) / len(self.values)


def _samples_by_pod(window: Window, book: dict) -> dict[str, list[Sample]]:
    uid_by_name = {v["pod"]: uid for uid, v in book.items() if v["pod"]}
    out: dict[str, list[Sample]] = defaultdict(list)
    for s in window.samples:
        name = s.labels.get("pod")
        uid = uid_by_name.get(name) if name else None
        if uid:
            out[uid].append(s)
    return out


def instance_vector(node: Node, window: Window, samples: list[Sample],
                    width_s: float, quantiles: tuple) -> Vector:
    spans = [s for s in window.spans if s.pod_uid == node.key]
    # One entry per consumed message, and the span that describes the replica
    # handling it rather than the broker delivering it.
    processing = consumed_messages(spans)
    serving = [s for s in spans if s.kind == SERVER]
    http = [s for s in spans if "http.response.status_code" in s.attributes]
    failed = [s for s in http if s.attributes.get("error.type")]

    def metric(name: str) -> list[Sample]:
        return _one_level_only([s for s in samples if s.name == name])

    def rate(name: str) -> float | None:
        return ratio(_sum_increase(metric(name)), width_s)

    processing_ms = [s.duration_ns / 1e6 for s in processing]
    serving_ms = [s.duration_ns / 1e6 for s in serving]

    v: list[float | None] = [quantile(processing_ms, q) for q in quantiles]
    v += [quantile(serving_ms, q) for q in quantiles]
    v.append(ratio(len(failed), len(http)) if http else None)

    v.append(ratio(_sum_increase(metric("container_cpu_cfs_throttled_periods_total")),
                   _sum_increase(metric("container_cpu_cfs_periods_total"))))
    v.append(rate("container_cpu_usage_seconds_total"))
    v.append(_sum_last(metric("container_memory_working_set_bytes")))
    v.append(None)                                   # slope: second pass
    v.append(_sum_last(metric("container_spec_memory_limit_bytes")))
    v.append(_sum_last(metric("container_spec_cpu_quota")))
    v.append(_sum_increase([s for s in samples
                            if s.name == "kube_pod_container_status_restarts_total"]))
    v.append(rate("container_network_receive_packets_dropped_total"))
    v.append(rate("container_network_transmit_packets_dropped_total"))
    v.append(rate("container_network_receive_errors_total"))
    v.append(rate("container_network_receive_bytes_total"))
    return Vector(node, INSTANCE_COLUMNS, v)


def queue_vector(node: Node, window: Window, width_s: float,
                 eta: float) -> Vector:
    name = node.name
    samples = [s for s in window.samples if s.queue == name]

    def level(metric: str) -> float | None:
        return last([(s.timestamp_ns, s.value) for s in samples
                     if s.name == metric])

    published = [s for s in window.published if s.queue_name == name]
    consumed = [s for s in window.consumed if s.queue_name == name]
    publish_rate = ratio(len(published) / eta, width_s)
    consume_rate = ratio(len(consumed) / eta, width_s)

    return Vector(node, QUEUE_COLUMNS, [
        level("rabbitmq_queue_messages_ready"),
        None,                                        # slope: second pass
        publish_rate, consume_rate,
        difference(publish_rate, consume_rate),
        level("rabbitmq_queue_consumers"),
    ])


def host_vector(node: Node, window: Window, width_s: float) -> Vector:
    name = node.name
    samples = [s for s in window.samples if s.labels.get("node") == name]

    def rate(metric: str) -> float | None:
        return ratio(_sum_increase([s for s in samples if s.name == metric]),
                     width_s)

    available = [(s.timestamp_ns, s.value) for s in samples
                 if s.name == "node_memory_MemAvailable_bytes"]

    cpu = [s for s in samples if s.name == "node_cpu_seconds_total"]
    cores = len({s.labels.get("cpu") for s in cpu if s.labels.get("cpu")})
    busy = _sum_increase([s for s in cpu if s.labels.get("mode") != "idle"])

    return Vector(node, HOST_COLUMNS, [
        rate("node_pressure_cpu_waiting_seconds_total"),
        rate("node_pressure_memory_waiting_seconds_total"),
        rate("node_pressure_io_waiting_seconds_total"),
        extreme(available, "min"),
        ratio(busy, width_s * cores) if cores else None,
    ])


def compute(windows: list[Window], namespace: str | None, width_s: float,
            horizon: int, eta: float, quantiles: tuple,
            node_series: list[dict[str, Node]] | None = None
            ) -> list[dict[str, Vector]]:
    """
    One dictionary of vectors per window, then the slopes in a second pass.

    `node_series` accepts nodes already collected, so the caller can report on
    them as a step of its own without the work being done twice.
    """
    series: list[dict[str, Vector]] = []
    for w_index, w in enumerate(windows):
        book = directory(w)
        per_pod = _samples_by_pod(w, book)
        vectors: dict[str, Vector] = {}
        found = (node_series[w_index] if node_series is not None
                 else collect(w, namespace))
        for key, node in found.items():
            if node.kind == "instance":
                vectors[key] = instance_vector(node, w, per_pod.get(key, []),
                                               width_s, quantiles)
            elif node.kind == "queue":
                vectors[key] = queue_vector(node, w, width_s, eta)
            else:
                vectors[key] = host_vector(node, w, width_s)
        series.append(vectors)

    for k in range(len(series)):
        for key, vec in series[k].items():
            slots = SLOPE_SLOTS.get(vec.node.kind)
            if not slots:
                continue
            source, target = slots
            history = [series[j][key].values[source] if key in series[j] else None
                       for j in range(max(0, k - horizon + 1), k + 1)]
            vec.values[target] = slope(history, horizon)
    return series
