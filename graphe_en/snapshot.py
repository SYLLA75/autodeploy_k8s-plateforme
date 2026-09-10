"""
Assembling one window into a snapshot, and writing it.

WHY A NEUTRAL FORMAT RATHER THAN PyTorch Geometric DIRECTLY

PyG pulls in PyTorch, two to three gigabytes, and its versions break against
each other. A dataset must outlive a change of library: in five years a reviewer
will open a JSON file, not install this exact PyG release. Conversion to PyG is
therefore a separate, optional step that reads these files.

WHAT IS WRITTEN

    <run>/graph/
        manifest.json          settings, provenance, dimensions, departures
        window_0001.json       one snapshot
        ...

Each window file holds, per node kind, the list of identities and a matrix of
numbers; per relation, the two index lists and a matrix of numbers. Indices
refer to the position in the node list of the relevant kind — the shape PyG and
DGL both expect, and one that can still be read by eye.

MISSING VALUES ARE WRITTEN `null`, NEVER ZERO. A zero and an absence do not mean
the same thing: a null rate is information, an unknown rate is not. Writing zero
would manufacture measurements that were never taken.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from edges import RELATIONS
from features import COLUMNS
from nodes import KINDS

DEPARTURES = [
    "Queue component 3 (publish rate): the counter "
    "rabbitmq_queue_messages_published_total does not exist on RabbitMQ 3.8. It "
    "is derived from publication spans, symmetrically to component 4, which the "
    "paper already reconstructs from consumption spans.",
    "The increase operator sums rises between consecutive samples instead of "
    "taking last minus first: a counter reset by a restart would otherwise "
    "produce a negative rate.",
    "A consumed message emits two identical spans; they are deduplicated, "
    "otherwise the consume rate doubles.",
    "REPORTED, NOT FIXED: instance component 4 and consumption relation "
    "component 1 are the same quantity, so it appears twice in the "
    "representation.",
]

BEFORE_TRAINING = [
    "Handle missing values (written null, never 0).",
    "Scale the features: magnitudes span 1e-2 to 1e8. Fit the scaling on the "
    "HEALTHY campaign only — fitting it on both would let the anomaly into the "
    "normalisation.",
    "No one-hot encoding is required: the graph is heterogeneous and no "
    "component is categorical.",
]


def _clean(v):
    """JSON accepts neither NaN nor infinity; both become indistinguishable
    from an absence, which is what they are."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def build(window, vectors, edges, edge_report) -> dict:
    grouped = {kind: [] for kind in KINDS}
    for key, vec in vectors.items():
        grouped[vec.node.kind].append((key, vec))
    for kind in grouped:
        grouped[kind].sort(key=lambda pair: pair[1].node.name)

    position = {kind: {key: i for i, (key, _) in enumerate(grouped[kind])}
                for kind in grouped}

    node_block = {}
    for kind, group in grouped.items():
        node_block[kind] = {
            "keys":    [key for key, _ in group],
            "names":   [v.node.name for _, v in group],
            "hosts":   [v.node.host for _, v in group],
            "columns": COLUMNS[kind],
            "X":       [[_clean(x) for x in v.values] for _, v in group],
        }

    edge_block = {}
    for relation, (src_kind, dst_kind, columns) in RELATIONS.items():
        group = [e for e in edges if e.relation == relation]
        src, dst, X = [], [], []
        for e in group:
            i = position[src_kind].get(e.source)
            j = position[dst_kind].get(e.target)
            if i is None or j is None:
                continue                  # an endpoint outside the kept graph
            src.append(i)
            dst.append(j)
            X.append([_clean(v) for v in e.values])
        edge_block[relation] = {"source_kind": src_kind, "target_kind": dst_kind,
                                "source": src, "target": dst,
                                "columns": columns, "X": X}

    return {
        "window": {
            "index": window.index,
            "start_ns": window.start_ns, "end_ns": window.end_ns,
            "start_utc": window.label,
            "duration_s": window.duration_s,
            "covered_s": round(window.covered_s, 2),
            "spans": len(window.spans), "samples": len(window.samples),
        },
        "nodes": node_block,
        "edges": edge_block,
        "call_resolution": edge_report["resolution"],
    }


def _counted(snapshots: list[dict]) -> dict:
    """
    How MANY objects each window holds, as one number when it never varies and
    a [min, max] range otherwise.

    Reported next to the component widths because the two were confused. The
    manifest used to publish only the widths under the keys "nodes" and
    "edges", so a relation carrying no feature column showed as
    "executes_on: 0" and read as "there is no such edge" — while every window
    in fact held 58 of them.
    """
    def spread(values: list[int]):
        return values[0] if len(set(values)) == 1 else [min(values), max(values)]

    return {
        "nodes_per_window": {k: spread([len(s["nodes"][k]["keys"])
                                        for s in snapshots]) for k in KINDS},
        "edges_per_window": {r: spread([len(s["edges"][r]["target"])
                                        for s in snapshots]) for r in RELATIONS},
    }


def manifest(settings, fetched, cut_report, written: int,
             snapshots: list[dict] | None = None) -> dict:
    origin = {}
    if fetched and fetched.manifest.exists():
        raw = json.loads(fetched.manifest.read_text())
        origin = {"store": raw.get("store"), "bucket": raw.get("bucket"),
                  "files": len(raw.get("files", []))}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(settings.path),
        "raw_provenance": origin,
        "settings": {
            "date": str(settings.day),
            "from": settings.range["from"], "to": settings.range["to"],
            "window_width_s": settings.width,
            "window_step_s": settings.step,
            "namespace": settings.graph["namespace"],
            "slope_horizon": settings.graph["slope_horizon"],
            "sampling_rate": settings.graph["sampling_rate"],
            "quantiles": list(settings.graph["quantiles"]),
            "assignment": "a span belongs to the window of its START",
            "edges": "windows not fully covered by the data are discarded",
        },
        "dimensions": {
            "node_components": {k: len(COLUMNS[k]) for k in KINDS},
            "edge_components": {r: len(v[2]) for r, v in RELATIONS.items()},
            **(_counted(snapshots) if snapshots else {}),
        },
        "windowing": {k: v for k, v in cut_report.items() if k != "discarded"},
        "windows_written": written,
        "discarded_windows": [
            {"start_utc": w.label, "covered_s": round(w.covered_s, 2),
             "spans": len(w.spans), "reason": reason}
            for w, reason in cut_report.get("discarded", [])
        ],
        "departures_from_paper": DEPARTURES,
        "before_training": BEFORE_TRAINING,
    }


def write(snapshots: list[dict], target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, snap in enumerate(snapshots, 1):
        p = target / f"window_{i:04d}.json"
        p.write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        paths.append(p)
    return paths
