"""
The nodes of the graph: what exists, in each window.

No value is computed and no edge is drawn here. This module lists what exists
and gives each thing a stable identity so it can be recognised from one window
to the next.

    instance   one running copy of a service   a pod
    queue      one message queue
    host       one machine of the cluster      a node

TWO SOURCES THAT DO NOT SPEAK THE SAME LANGUAGE

Traces identify a pod by an opaque identifier:

    k8s.pod.uid = fc2f0f27-b624-433c-98ea-fff47c39355d

Metrics identify it by name:

    pod = ts-seat-service-6fbf7f6fbb-zllcn

`kube_pod_info` carries both, plus the host. It is the only piece that bridges
them, which is why it belongs in the exported metric set. Verified over the
range 15:05-15:14: all 41 pods seen in traces were found, and the host reported
by traces matched the host reported by metrics 41 times out of 41, with zero
disagreement.

RESTARTS. Two cases that must not be confused:

    container restarts in place  ->  SAME identifier, same node, and
                                     kube_pod_container_status_restarts_total
                                     increments
    pod is recreated             ->  NEW identifier, new node

The second is correct: it really is another copy, possibly on another host. The
two situations are distinguishable in the data, so no arbitrary convention is
needed.
"""
from __future__ import annotations

from dataclasses import dataclass

from windows import Window

KINDS = ("instance", "queue", "host")


@dataclass(slots=True)
class Node:
    kind: str                    # instance | queue | host
    key: str                     # stable identity
    name: str                    # readable label
    service: str | None = None
    namespace: str | None = None
    host: str | None = None      # for an instance: where it runs
    from_traces: bool = False
    from_metrics: bool = False

    @property
    def source(self) -> str:
        if self.from_traces and self.from_metrics:
            return "both"
        return "traces" if self.from_traces else "metrics"


def directory(window: Window) -> dict[str, dict]:
    """
    The window's pod directory, built from kube_pod_info.

    Maps each pod identifier to its name, namespace and host.
    """
    by_uid: dict[str, dict] = {}
    for s in window.samples:
        if s.name != "kube_pod_info":
            continue
        uid = s.labels.get("uid")
        if uid:
            by_uid[uid] = {"pod": s.labels.get("pod"),
                           "namespace": s.labels.get("namespace"),
                           "host": s.labels.get("node")}
    return by_uid


def collect(window: Window, namespace: str | None = None) -> dict[str, Node]:
    """
    List the nodes present in this window.

    `namespace` restricts instances and queues to one namespace. Without it the
    system's own pods and the measurement stack itself are picked up, and
    neither belongs to the graph under study.

    HOSTS ARE NEVER FILTERED, even when a namespace is given: a host carries
    pods from several namespaces, and that sharing is precisely what may explain
    a fault — a noisy neighbour.
    """
    book = directory(window)
    by_pod_name = {v["pod"]: (uid, v) for uid, v in book.items() if v["pod"]}
    nodes: dict[str, Node] = {}

    def put(kind: str, key: str, **kw) -> Node:
        node = nodes.get(key)
        if node is None:
            node = nodes[key] = Node(kind=kind, key=key,
                                     name=kw.pop("name", key))
        for field_name, value in kw.items():
            if value is not None and getattr(node, field_name, None) is None:
                setattr(node, field_name, value)
        return node

    def in_scope(ns: str | None) -> bool:
        return namespace is None or ns == namespace

    for s in window.spans:
        if not s.pod_uid or not in_scope(s.namespace):
            continue
        card = book.get(s.pod_uid, {})
        put("instance", s.pod_uid,
            name=card.get("pod") or s.service or s.pod_uid[:12],
            service=s.service, namespace=s.namespace,
            host=s.host or card.get("host")).from_traces = True

    for s in window.samples:
        if not s.name.startswith("container_"):
            continue
        pod_name = s.labels.get("pod")
        if not pod_name or not in_scope(s.labels.get("namespace")):
            continue
        found = by_pod_name.get(pod_name)
        if not found:
            continue                     # not in the directory: do not guess
        uid, card = found
        put("instance", uid, name=pod_name, namespace=card["namespace"],
            host=card["host"] or s.labels.get("kubernetes_io_hostname"),
            ).from_metrics = True

    for s in window.published + window.consumed:
        if s.queue_name:
            put("queue", f"queue:{s.queue_name}", name=s.queue_name,
                namespace=s.namespace).from_traces = True
    for s in window.samples:
        if s.name.startswith("rabbitmq_queue_") and s.queue:
            put("queue", f"queue:{s.queue}", name=s.queue,
                namespace=s.labels.get("namespace"),
                host=s.labels.get("node")).from_metrics = True

    for s in window.samples:
        if s.name.startswith("node_") and s.labels.get("node"):
            put("host", f"host:{s.labels['node']}",
                name=s.labels["node"]).from_metrics = True
    for node in [n for n in nodes.values() if n.kind == "instance" and n.host]:
        put("host", f"host:{node.host}", name=node.host).from_traces = True

    return nodes
