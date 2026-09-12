"""
Keep the readout of a run next to the campaign it belongs to.

    ./.venv/bin/python lecture.py runs/<timestamp> <campaign> [word]

Writes ../campagnes/<campaign>/lecture.txt: which run it comes from, the
time range it was built on, then the two tables of queues.py (the queue) and
instances.py (every instance whose name contains the word, default delivery).

runs/ is not versioned — a run weighs hundreds of megabytes — but this text
is small, and it is what a report quotes. Standard library only.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import instances
import queues


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.strip())
        return 2
    run_dir, campaign = Path(argv[1]), argv[2]
    word = argv[3] if len(argv) > 3 else "delivery"
    manifest = json.loads((run_dir / "graph" / "manifest.json").read_text())
    s = manifest["settings"]
    target = Path(__file__).resolve().parent.parent / "campagnes" / campaign / "lecture.txt"
    if not target.parent.is_dir():
        sys.exit(f"no such campaign directory: {target.parent}")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        print(f"# Lecture du graphe construit par run.py — {run_dir}")
        print(f"# plage {s['date']} {s['from']} -> {s['to']}, fenêtres de {s['window_width_s']:.0f} s")
        print(f"# fenêtres gardées : {manifest['windowing']['kept']}")
        print()
        queues.main(["queues.py", str(run_dir)])
        print()
        instances.main(["instances.py", str(run_dir), word])
    target.write_text(out.getvalue())
    print(out.getvalue(), end="")
    print(f"-> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
