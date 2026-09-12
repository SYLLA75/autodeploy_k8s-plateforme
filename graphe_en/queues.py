"""
One line per window for one queue: is the consumer keeping up?

    ./.venv/bin/python queues.py runs/<timestamp> [queue_name]

Reads the window_*.json files written by run.py and prints, for the chosen
queue (default: food_delivery), the six queue components of every window:

    window  start_utc  backlog  backlog_slope  publish_rate  consume_rate  imbalance  consumers

This is the readout of a calibration campaign: the load step where backlog
starts to grow, or consume_rate stops following publish_rate, is where the
consumer saturates. Standard library only, so it runs without the venv too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def rows(run_dir: Path, queue: str):
    files = sorted(run_dir.glob("graph/window_*.json"))
    if not files:
        sys.exit(f"no graph/window_*.json under {run_dir}")
    for f in files:
        snap = json.loads(f.read_text())
        block = snap["nodes"].get("queue") or {}
        names = block.get("names", [])
        if queue not in names:
            yield snap["window"]["index"], snap["window"]["start_utc"], None, block.get("columns", [])
            continue
        yield (snap["window"]["index"], snap["window"]["start_utc"],
               block["X"][names.index(queue)], block["columns"])


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    run_dir = Path(argv[1])
    queue = argv[2] if len(argv) > 2 else "food_delivery"
    columns = None
    absent = 0
    print(f"queue: {queue}    run: {run_dir}")
    for index, start, values, cols in rows(run_dir, queue):
        if columns is None:
            columns = cols
            print(f"{'window':>6}  {'start_utc':<20}" + "".join(f"{c:>15}" for c in columns))
        if values is None:
            absent += 1
            print(f"{index:>6}  {start:<20}" + f"{'(absent)':>15}")
            continue
        print(f"{index:>6}  {start:<20}" + "".join(f"{fmt(v):>15}" for v in values))
    if absent:
        print(f"\n{absent} window(s) without this queue — names are those of the "
              f"'queue' node block, check with: grep -h '\"names\"' graph/window_0000.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
