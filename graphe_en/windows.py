"""
Cutting a fetched range into windows.

A single count over the whole range shows nothing: a queue that misbehaves for
one minute out of ten drowns in the average. Counting window by window shows
WHEN it goes wrong, which is the point of the work.

    width   what one window covers
    step    how far apart two consecutive windows start

    step == width   back-to-back, no overlap
    step <  width   overlapping — "sliding"

A span may then belong to several windows. That is intended.

THREE RULES, decided after measuring on real data:

  1. A span is filed under its START, never its end. Today this changes
     nothing (a consumption lasts 5 ms). Under a fault, a slowed consumer would
     produce long consumptions, and filing by the end would push the departure
     into a later window — hiding exactly the anomaly being looked for.

  2. Only windows fully covered by the data are kept. The edges of a fetched
     range are always truncated: files are laid out by export minute, not by
     event instant. A window covering 40 s instead of 60 reports smaller counts
     without the traffic having changed, and reads as a drop in load.

  3. A consumed message counts once, not twice. See otlp.Span.message_key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from otlp import (Sample, Span, consumed_messages, published_messages,
                  read_samples, read_spans)

BILLION = 1_000_000_000


@dataclass(slots=True)
class Window:
    index: int
    start_ns: int
    end_ns: int
    spans: list[Span] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return (self.end_ns - self.start_ns) / 1e9

    @property
    def label(self) -> str:
        return datetime.fromtimestamp(self.start_ns / 1e9,
                                      timezone.utc).strftime("%H:%M:%S")

    @property
    def covered_s(self) -> float:
        """
        How many seconds this window actually holds data for.

        Used to check the edges: a truncated window reports smaller counts
        without the traffic having changed.
        """
        instants = [s.start_ns for s in self.spans]
        instants += [s.timestamp_ns for s in self.samples if s.timestamp_ns]
        return (max(instants) - min(instants)) / 1e9 if instants else 0.0

    @property
    def published(self) -> list[Span]:
        return published_messages(self.spans)

    @property
    def consumed(self) -> list[Span]:
        return consumed_messages(self.spans)

    def imbalance(self, queue: str | None = None) -> int:
        """
        Messages in minus messages out, during this window.

        A flow balance, not a pairing: a message published here and consumed
        three windows later counts +1 here and -1 there. Both are correct — the
        queue did grow, then did shrink. A negative value is therefore
        legitimate.
        """
        pub = [s for s in self.published if queue is None or s.queue_name == queue]
        con = [s for s in self.consumed if queue is None or s.queue_name == queue]
        return len(pub) - len(con)

    @property
    def queues(self) -> list[str]:
        return sorted({s.queue_name for s in self.published + self.consumed
                       if s.queue_name})


def load(files: list[Path], with_metrics: bool = True
         ) -> tuple[list[Span], list[Sample]]:
    """
    Read every measurement file of a directory.

    Everything is held at once, because overlapping windows revisit the same
    data several times. Ten minutes fit comfortably; a whole day would not.
    """
    spans: list[Span] = []
    samples: list[Sample] = []
    for path in files:
        if path.name == "origin.json":
            continue
        head = path.read_bytes()[:120]
        if b"resourceSpans" in head:
            spans += read_spans(path)
        elif b"resourceMetrics" in head and with_metrics:
            samples += read_samples(path)
    return [s for s in spans if s.start_ns], samples


def _indices(instant_ns: int, width_ns: int, step_ns: int) -> range:
    """
    The windows that contain this instant.

    The grid is anchored on the absolute epoch, not on the start of the data.
    Two ranges cut with the same settings therefore land on exactly the same
    boundaries, which is what makes two campaigns comparable.
    """
    last = instant_ns // step_ns
    first = (instant_ns - width_ns) // step_ns + 1
    return range(first, last + 1)


def cut(spans: list[Span], samples: list[Sample], width_s: float, step_s: float,
        margin: int = 0, limit: int | None = None
        ) -> tuple[list[Window], dict]:
    """
    File every span and sample into the windows that contain them.

    Returns the retained windows and a report of what was set aside, so that no
    data disappears silently.
    """
    width_ns = int(width_s * BILLION)
    step_ns = int(step_s * BILLION)

    instants = [s.start_ns for s in spans]
    instants += [s.timestamp_ns for s in samples if s.timestamp_ns]
    if not instants:
        return [], {"reason": "no usable timestamp", "built": 0, "kept": 0,
                    "dropped_coverage": 0, "dropped_margin": 0,
                    "dropped_limit": 0, "discarded": []}
    first_ns, last_ns = min(instants), max(instants)

    boxes: dict[int, Window] = {}

    def box(k: int) -> Window:
        w = boxes.get(k)
        if w is None:
            w = boxes[k] = Window(index=k, start_ns=k * step_ns,
                                  end_ns=k * step_ns + width_ns)
        return w

    for s in spans:
        for k in _indices(s.start_ns, width_ns, step_ns):
            box(k).spans.append(s)
    for s in samples:
        if not s.timestamp_ns:
            continue
        for k in _indices(s.timestamp_ns, width_ns, step_ns):
            box(k).samples.append(s)

    everything = [boxes[k] for k in sorted(boxes)]
    covered = [w for w in everything
               if w.start_ns >= first_ns and w.end_ns <= last_ns]
    trimmed = covered[margin:-margin] if margin and len(covered) > 2 * margin else (
        [] if margin else covered)

    dropped_limit = 0
    kept = trimmed
    if limit and len(trimmed) > limit:
        dropped_limit = len(trimmed) - limit
        kept = trimmed[:limit]

    # Each reason is attributed to the step that actually applied it. They used
    # to share one label, so a window cut off by windows.max was reported as
    # discarded by the edge margin — a setting the run may not even use.
    kept_ids = {id(w) for w in kept}
    trimmed_ids = {id(w) for w in trimmed}
    covered_ids = {id(w) for w in covered}
    discarded = [(w, "outside data coverage") for w in everything
                 if id(w) not in covered_ids]
    discarded += [(w, "edge margin") for w in covered
                  if id(w) not in trimmed_ids]
    discarded += [(w, "over windows.max") for w in trimmed
                  if id(w) not in kept_ids]
    discarded.sort(key=lambda x: x[0].index)

    report = {
        "built": len(everything),
        "dropped_coverage": len(everything) - len(covered),
        "dropped_margin": len(covered) - len(trimmed),
        "dropped_limit": dropped_limit,
        "kept": len(kept),
        "data_from_ns": first_ns, "data_to_ns": last_ns,
        "width_s": width_s, "step_s": step_s, "margin": margin,
        "discarded": discarded,
    }
    return kept, report
