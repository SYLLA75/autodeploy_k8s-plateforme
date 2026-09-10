"""
Translating snapshots into PyTorch Geometric objects.

Produces no new data: it reads the files written by snapshot.py and puts them in
the shape the library expects.

    nodes.instance.X       ->  data['instance'].x
    edges.publishes.source ->  data['instance','publishes','queue'].edge_index
    edges.publishes.X      ->  data['instance','publishes','queue'].edge_attr

THREE THINGS THE CONVERSION MUST DECIDE, all of them method rather than
plumbing, and each one a setting.

1. MISSING VALUES. The file writes null. A tensor has no notion of absence.

       mask   fill with 0 AND add a boolean tensor recording where the hole
              was, so a model can learn to distrust it
       mean   fill with the column mean over the campaign
       zero   fill with 0 and say nothing

   `zero` is the dangerous one: an unknown rate becomes a null rate, that is,
   an invented fault.

2. SCALING. Magnitudes span 1e-2 to 1e8; without correction memory drowns
   everything else.

   METHODOLOGICAL TRAP. Means and standard deviations must be computed on the
   HEALTHY campaign only, then the same numbers applied to the faulty one.
   Computing them on both lets the anomaly into the normalisation, which then
   partly erases it — and the results are wrong with nothing to signal it.
   Hence the two separate modes, write and apply.

3. LOGARITHM. Durations, memory and byte counts spread over several orders of
   magnitude with a heavy tail. log(1+x) is applied before standardising. The
   columns concerned are named below, not guessed, so a reviewer can dispute the
   list.

DEVICE. Tensors can be built on a GPU, but THE FILE ALWAYS STORES CPU TENSORS,
deliberately: a file holding GPU tensors can only be reloaded on a machine that
has one, sometimes only with the same CUDA release. That is the opposite of
portability. The device belongs to the training loop:

    windows = torch.load('graph.pt', weights_only=False)
    windows = [w.to('cuda') for w in windows]

EDGE DIRECTION. Edges are written in the direction the data flows: an instance
publishes TO a queue, an instance executes ON a host. For a node to receive
information from its neighbours in both directions, a model often needs the
reverse relations; add_reverse_edges adds them, prefixed with "rev_". Off by
default, because it is a modelling choice and not a property of the format.
"""
from __future__ import annotations

import json
import math
import platform
from pathlib import Path

from edges import RELATIONS
from features import COLUMNS
from nodes import KINDS

# Heavy-tailed, always non-negative columns: log(1+x) before standardising.
LOG_COLUMNS = {
    "instance": ["process_time_p50", "process_time_p95", "process_time_p99",
                 "request_time_p50", "request_time_p95", "request_time_p99",
                 "memory_used", "memory_limit", "cpu_quota", "rx_bytes"],
    "queue": ["backlog"],
    "host": ["memory_available_min"],
}


def resolve_device(requested: str) -> str:
    """
    The device that can actually be used, never the one blindly asked for.

    Asking for cuda on a CPU-only build would fail at the first operation, far
    from here. It is reported immediately instead.
    """
    import torch
    available = torch.cuda.is_available()
    if requested == "auto":
        return "cuda" if available else "cpu"
    if requested == "cuda" and not available:
        raise SystemExit(
            "device 'cuda' requested but no usable GPU is available.\n"
            f"  installed torch: {torch.__version__}\n"
            "  a '+cpu' build never sees a GPU. To get one:\n"
            "    pip uninstall torch\n"
            "    pip install torch --index-url "
            "https://download.pytorch.org/whl/cu124")
    return requested


def environment(device: str) -> dict:
    """What must be recorded for a result to be repeatable."""
    import torch
    import torch_geometric
    return {
        "python": platform.python_version(),
        "system": f"{platform.system()} {platform.release()}",
        "torch": torch.__version__,
        "torch_geometric": torch_geometric.__version__,
        "cuda_in_torch": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "devices": [torch.cuda.get_device_name(i)
                    for i in range(torch.cuda.device_count())],
        "device_used": device,
        "note": "The conversion involves no random draw: it gives the same "
                "result on CPU and on GPU.",
    }


def fit_scaler(snapshots: list[dict]) -> dict:
    """Mean and standard deviation per column, absences ignored."""
    scaler = {}
    for kind in KINDS:
        columns = snapshots[0]["nodes"][kind]["columns"]
        logged = set(LOG_COLUMNS.get(kind, []))
        stats = []
        for j, name in enumerate(columns):
            seen = []
            for s in snapshots:
                for row in s["nodes"][kind]["X"]:
                    v = row[j]
                    if v is None:
                        continue
                    if name in logged:
                        v = math.log1p(max(0.0, v))
                    seen.append(v)
            if seen:
                mean = sum(seen) / len(seen)
                sd = math.sqrt(sum((x - mean) ** 2 for x in seen) / len(seen))
            else:
                mean, sd = 0.0, 1.0
            stats.append({"column": name, "mean": mean,
                          "std": sd if sd > 1e-12 else 1.0,
                          "log": name in logged, "observations": len(seen)})
        scaler[kind] = stats
    return scaler


def _transform(row: list, stats: list[dict] | None, columns: list[str],
               kind: str) -> tuple[list, list[bool]]:
    logged = set(LOG_COLUMNS.get(kind, []))
    out, present = [], []
    for j, v in enumerate(row):
        present.append(v is not None)
        if v is None:
            out.append(None)
            continue
        x = float(v)
        if columns[j] in logged:
            x = math.log1p(max(0.0, x))
        if stats:
            s = stats[j]
            x = (x - s["mean"]) / s["std"]
        out.append(x)
    return out, present


def convert(snapshots: list[dict], scaler: dict | None, missing: str,
            reverse: bool, device: str):
    import torch
    from torch_geometric.data import HeteroData

    fillers = {}
    if missing == "mean":
        for kind in KINDS:
            columns = snapshots[0]["nodes"][kind]["columns"]
            stats = scaler.get(kind) if scaler else None
            buckets = [[] for _ in columns]
            for s in snapshots:
                for row in s["nodes"][kind]["X"]:
                    values, _ = _transform(row, stats, columns, kind)
                    for j, v in enumerate(values):
                        if v is not None:
                            buckets[j].append(v)
            fillers[kind] = [sum(b) / len(b) if b else 0.0 for b in buckets]

    out = []
    for snap in snapshots:
        data = HeteroData()
        for kind in KINDS:
            block = snap["nodes"][kind]
            columns = block["columns"]
            stats = scaler.get(kind) if scaler else None
            rows, masks = [], []
            for row in block["X"]:
                values, present = _transform(row, stats, columns, kind)
                filler = fillers.get(kind) if missing == "mean" else None
                values = [(filler[j] if filler else 0.0) if v is None else v
                          for j, v in enumerate(values)]
                rows.append(values)
                masks.append(present)
            data[kind].x = torch.tensor(rows, dtype=torch.float32).reshape(
                len(block["X"]), len(columns)).to(device)
            data[kind].num_nodes = len(block["keys"])
            data[kind].keys_ = block["keys"]
            data[kind].names = block["names"]
            data[kind].columns = columns
            if missing == "mask":
                data[kind].present = torch.tensor(
                    masks, dtype=torch.bool).reshape(
                    len(block["X"]), len(columns)).to(device)

        for relation, (src, dst, _) in RELATIONS.items():
            block = snap["edges"][relation]
            index = torch.tensor([block["source"], block["target"]],
                                 dtype=torch.long).reshape(2, -1).to(device)
            attr = torch.tensor(
                [[0.0 if v is None else float(v) for v in row]
                 for row in block["X"]],
                dtype=torch.float32).reshape(len(block["X"]),
                                             len(block["columns"])).to(device)
            data[src, relation, dst].edge_index = index
            data[src, relation, dst].edge_attr = attr
            if reverse:
                data[dst, f"rev_{relation}", src].edge_index = index.flip(0)
                data[dst, f"rev_{relation}", src].edge_attr = attr

        data.start_utc = snap["window"]["start_utc"]
        data.start_ns = snap["window"]["start_ns"]
        out.append(data)
    return out


def save(windows, target: Path, device: str, keep_device: bool) -> Path:
    import torch
    if device != "cpu" and not keep_device:
        windows = [w.to("cpu") for w in windows]
    target.parent.mkdir(parents=True, exist_ok=True)
    torch.save(windows, target)
    (target.parent / "environment.json").write_text(
        json.dumps(environment(device), ensure_ascii=False, indent=1),
        encoding="utf-8")
    return target
