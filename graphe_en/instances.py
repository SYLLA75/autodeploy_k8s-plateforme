"""
One line per window and per instance whose name contains a word.

    ./.venv/bin/python instances.py runs/<timestamp> delivery [column ...]

Reads the window_*.json files written by run.py and prints, for every
instance whose name contains the word (default: delivery), the chosen
components — by default:

    process_time_p50  process_time_p95  error_ratio  cpu_rate  memory_used

process_time is in seconds (the time one replica takes to handle a message);
this is how the consumer's service time is read after a reference campaign,
and how a single replica is watched during a fault. Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT = ["process_time_p50", "process_time_p95", "error_ratio", "cpu_rate", "memory_used"]


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    run_dir = Path(argv[1])
    word = argv[2] if len(argv) > 2 else "delivery"
    wanted = argv[3:] or DEFAULT
    files = sorted(run_dir.glob("graph/window_*.json"))
    if not files:
        sys.exit(f"no graph/window_*.json under {run_dir}")
    header = None
    for f in files:
        snap = json.loads(f.read_text())
        block = snap["nodes"].get("instance") or {}
        cols = block.get("columns", [])
        missing = [c for c in wanted if c not in cols]
        if missing:
            sys.exit(f"unknown column(s) {missing}; available: {cols}")
        if header is None:
            header = f"{'window':>6}  {'start_utc':<20} {'instance':<22}" + "".join(f"{c:>18}" for c in wanted)
            print(f"instances containing '{word}'    run: {run_dir}")
            print(header)
        for name, values in zip(block.get("names", []), block.get("X", [])):
            if word not in name:
                continue
            row = [values[cols.index(c)] for c in wanted]
            print(f"{snap['window']['index']:>6}  {snap['window']['start_utc']:<20} {name[:22]:<22}"
                  + "".join(f"{fmt(v):>18}" for v in row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
