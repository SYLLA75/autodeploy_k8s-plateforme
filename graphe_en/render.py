"""
Rendering one window as a figure.

Reads a snapshot and draws it. Produces no data.

THREE BANDS, bottom to top:

    hosts        the machines of the cluster
    instances    the running copies of the services
    queues       the message queues

Instances are ordered by host then by name, so the "executes on" lines group
instead of crossing and membership can be read at a glance.

A QUEUE SITS ABOVE THE INSTANCES IT TOUCHES (the barycentre of its neighbours),
not at an arbitrary rank. Placed by rank, its two edges cross the whole figure
and nothing can be read.

THE LAYOUT IS DETERMINISTIC. No random draw, no force-directed placement:
positions are computed from names. Two runs give the same image, and two
consecutive windows are superimposable. Otherwise the system would appear to
move when only the drawing had changed — the classic defect of spring layouts.

WHERE TEXT GOES, WHERE ENCODING GOES

    queues       2 nodes         text: rates, imbalance, backlog
    hosts        5 to 7 nodes    text: three numbers
    instances    41 to 56 nodes  no text — the node fill carries the value

Forty-one numbers written under the instances would make the figure unreadable.

THE LAYOUT AND THE GREY SCALE ARE BOTH COMPUTED OVER THE WHOLE CAMPAIGN, not
over the window being drawn.

That applies to WHICH NODES APPEAR as much as to where they sit. A first version
picked the queue's neighbours window by window and fell back to the whole graph
when a window had no traffic: the same run then produced two incomparable kinds
of figure, some with four nodes and some with sixty-five. Selecting the nodes
once, over the union of every window, keeps the series flippable like the frames
of a film — which is the only way a fault developing over time can be seen.

A node that exists in the campaign but not in the window being drawn keeps its
place, drawn pale and dotted. Removing it would shift everything else.

GREYS RATHER THAN COLOURS, so the figure survives black-and-white printing. The
single colour accent is reserved for the queue.

A DASHED OUTLINE MEANS NO DATA, not a zero.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                              # noqa: E402
from matplotlib.lines import Line2D                          # noqa: E402
from matplotlib.patches import FancyArrowPatch                # noqa: E402

LINE_GREY = "#9a9a9a"
PALE_GREY = "#d8d8d8"
INK = "#1a1a1a"
ACCENT = "#c2410c"
BAND = {"host": 0.0, "instance": 1.0, "queue": 2.25}
BAND_LABEL = {"host": "hosts", "instance": "instances", "queue": "queues"}


def _short_labels(keys: list[str], full: dict[str, str]) -> dict[str, str]:
    """
    Short, readable labels — kept distinct.

    A pod name carries the service, the replica set and the instance:

        ts-delivery-service-7fdf74bc6-8jxvq
        |____ service _____| |__ rs __| |_ id _|

    Only the service part is worth reading, so the rest is dropped. But three
    replicas of one service then produce three identical labels, and the reader
    cannot tell which circle is which — exactly the question that matters when a
    single replica falls behind.

    So the trailing identifier is added back, but ONLY where a label would
    otherwise be ambiguous. Unique services stay short.
    """
    def base(name: str) -> str:
        core = name.rsplit("-", 2)[0] if name.count("-") >= 3 else name
        return core.replace("ts-", "").replace("-service", "")

    counts: dict[str, int] = {}
    for k in keys:
        counts[base(full[k])] = counts.get(base(full[k]), 0) + 1

    labels = {}
    for k in keys:
        name = full[k]
        b = base(name)
        if counts[b] > 1:
            suffix = name.rsplit("-", 1)[-1]
            labels[k] = f"{b}·{suffix[:5]}"
        else:
            labels[k] = b
    return labels


class Layout:
    """
    Where every node of the campaign sits, decided once.

    Holds keys rather than per-window indices, because a node's index differs
    from one window to the next while its key does not.
    """

    def __init__(self, order: dict[str, list[str]], label: dict[str, str],
                 host_of: dict[str, str | None],
                 position: dict[str, tuple[float, float]],
                 queue: str | None, short: dict[str, str] | None = None):
        self.order = order
        self.label = label
        self.short = short or {}
        self.host_of = host_of
        self.position = position
        self.queue = queue

    @property
    def size(self) -> dict[str, int]:
        return {kind: len(keys) for kind, keys in self.order.items()}


def _campaign_neighbourhood(snapshots: list[dict], queue_name: str
                            ) -> dict[str, set[str]]:
    """
    Every node that touches the queue at any point of the campaign.

    Taken over the union, not per window: a publisher that is idle for one
    minute must keep its place, or the figures stop being comparable.
    """
    queue_keys, instance_keys = set(), set()
    for snap in snapshots:
        block = snap["nodes"]["queue"]
        if queue_name not in block["names"]:
            continue
        q = block["names"].index(queue_name)
        queue_keys.add(block["keys"][q])
        for relation, side in (("publishes", "source"), ("consumes", "target")):
            edge = snap["edges"][relation]
            other = "target" if side == "source" else "source"
            for k in range(len(edge["source"])):
                if edge[other][k] == q:
                    instance_keys.add(snap["nodes"]["instance"]["keys"][edge[side][k]])
    if not queue_keys:
        raise SystemExit(f"queue '{queue_name}' never appears in this campaign")

    host_names = set()
    for snap in snapshots:
        block = snap["nodes"]["instance"]
        for i, key in enumerate(block["keys"]):
            if key in instance_keys and block["hosts"][i]:
                host_names.add(block["hosts"][i])
    host_keys = set()
    for snap in snapshots:
        block = snap["nodes"]["host"]
        for i, name in enumerate(block["names"]):
            if name in host_names:
                host_keys.add(block["keys"][i])
    return {"queue": queue_keys, "instance": instance_keys, "host": host_keys}


def plan(snapshots: list[dict], queue_name: str | None) -> Layout:
    """Decide the layout once, from every window of the campaign."""
    label: dict[str, str] = {}
    host_of: dict[str, str | None] = {}
    seen: dict[str, set[str]] = {kind: set() for kind in BAND}
    for snap in snapshots:
        for kind in BAND:
            block = snap["nodes"][kind]
            for i, key in enumerate(block["keys"]):
                seen[kind].add(key)
                label.setdefault(key, block["names"][i])
                if kind == "instance" and host_of.get(key) is None:
                    host_of[key] = block["hosts"][i]

    if queue_name:
        wanted = _campaign_neighbourhood(snapshots, queue_name)
        seen = {kind: seen[kind] & wanted[kind] for kind in BAND}

    order = {
        "host": sorted(seen["host"], key=lambda k: label[k]),
        "instance": sorted(seen["instance"],
                           key=lambda k: (host_of.get(k) or "", label[k])),
    }

    position: dict[str, tuple[float, float]] = {}
    for kind in ("host", "instance"):
        n = len(order[kind])
        for rank, key in enumerate(order[kind]):
            position[key] = (0.5 if n == 1 else rank / (n - 1), BAND[kind])

    # a queue sits above the instances it touches, over the whole campaign
    neighbours: dict[str, list[float]] = {}
    for snap in snapshots:
        qkeys = snap["nodes"]["queue"]["keys"]
        ikeys = snap["nodes"]["instance"]["keys"]
        for relation, qside, iside in (("publishes", "target", "source"),
                                       ("consumes", "source", "target")):
            edge = snap["edges"][relation]
            for k in range(len(edge["source"])):
                qk, ik = qkeys[edge[qside][k]], ikeys[edge[iside][k]]
                if qk in seen["queue"] and ik in position:
                    neighbours.setdefault(qk, []).append(position[ik][0])

    order["queue"] = sorted(seen["queue"], key=lambda k: label[k])
    free = [k for k in order["queue"] if k not in neighbours]
    for key in order["queue"]:
        if key in neighbours:
            x = sum(neighbours[key]) / len(neighbours[key])
        else:
            r = free.index(key)
            x = 0.5 if len(free) == 1 else r / (len(free) - 1)
        position[key] = (min(0.97, max(0.03, x)), BAND["queue"])

    short = _short_labels(order["instance"], label)
    return Layout(order, label, host_of, position, queue_name, short)


def scale_bounds(snapshots: list[dict], columns: dict[str, str]) -> dict:
    """Smallest and largest value of each encoded column, over the campaign."""
    bounds = {}
    for kind, column in columns.items():
        names = snapshots[0]["nodes"][kind]["columns"]
        if column not in names:
            bounds[kind] = None
            continue
        j = names.index(column)
        seen = [row[j] for s in snapshots for row in s["nodes"][kind]["X"]
                if row[j] is not None]
        bounds[kind] = (min(seen), max(seen)) if seen else None
    return bounds


def _shade(value, bounds):
    if value is None or bounds is None:
        return None
    low, high = bounds
    if high <= low:
        return 0.12
    return 0.06 + 0.62 * (value - low) / (high - low)


def _num(x: float | None, unit: str = "") -> str:
    if x is None:
        return "n/a"
    if unit == "B":
        for suffix, threshold in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
            if abs(x) >= threshold:
                return f"{x/threshold:.1f} {suffix}"
        return f"{x:.0f} B"
    if unit == "%":
        return f"{100*x:.1f}%"
    if abs(x) >= 100 or (x and abs(x) < 0.01):
        return f"{x:.2g}"
    return f"{x:.3g}"


def _plural(n: float | None, word: str) -> str:
    if n is None:
        return f"no {word} data"
    n = int(n)
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _arrow(ax, a, b, colour, width, curve=0.0, style="-", alpha=1.0, head=True):
    ax.add_patch(FancyArrowPatch(
        a, b, connectionstyle=f"arc3,rad={curve}",
        arrowstyle="-|>" if head else "-",
        mutation_scale=11 if head else 1,
        linewidth=width, linestyle=style, color=colour, alpha=alpha,
        shrinkA=9, shrinkB=11, zorder=1))


def has_neighbourhood(snapshot: dict, queue_name: str) -> bool:
    """
    Whether that queue has anyone publishing to it or consuming from it.

    A queue known only through its metrics, with no traffic in this window, has
    no neighbours: restricting to it would produce a figure holding one circle
    and nothing else.
    """
    block = snapshot["nodes"]["queue"]
    if queue_name not in block["names"]:
        return False
    q = block["names"].index(queue_name)
    for relation, side in (("publishes", "target"), ("consumes", "source")):
        if q in snapshot["edges"][relation][side]:
            return True
    return False


def draw(snapshot: dict, layout: Layout, base: Path,
         encoded: dict[str, str], bounds: dict, dpi: int = 170,
         formats: tuple[str, ...] = ("svg",)) -> list[Path]:
    """
    Draw one window onto the campaign's layout.

    `base` carries no extension: the figure is built once and written in every
    requested format. svg and pdf keep the drawing as geometry, so it can be
    enlarged without pixels and its text stays selectable and searchable — what
    a paper needs. dpi applies to png alone.

    Every node of the layout is drawn, whether or not this particular window
    knows about it. One absent from the window keeps its place, pale and dotted:
    dropping it would shift every other node and break the comparison with the
    neighbouring frames.
    """
    pos = layout.position
    here = {kind: {key: i for i, key in enumerate(snapshot["nodes"][kind]["keys"])}
            for kind in BAND}
    drawn = {kind: set(layout.order[kind]) for kind in BAND}

    width = max(9.0, min(26.0, 0.42 * len(layout.order["instance"]) + 5))
    fig, ax = plt.subplots(figsize=(width, 6.4))

    def key_of(kind: str, index: int) -> str | None:
        keys = snapshot["nodes"][kind]["keys"]
        return keys[index] if 0 <= index < len(keys) else None

    def both_shown(kind_a, i, kind_b, j):
        a, b = key_of(kind_a, i), key_of(kind_b, j)
        if a in drawn[kind_a] and b in drawn[kind_b]:
            return pos[a], pos[b]
        return None

    block = snapshot["edges"]["executes_on"]
    for k in range(len(block["source"])):
        pair = both_shown("instance", block["source"][k], "host", block["target"][k])
        if pair:
            _arrow(ax, pair[0], pair[1], PALE_GREY, 0.7, style=(0, (1, 2)),
                   head=False)

    block = snapshot["edges"]["calls"]
    rates = [row[0] or 0 for row in block["X"]] or [1]
    top = max(rates) or 1
    for k in range(len(block["source"])):
        pair = both_shown("instance", block["source"][k],
                          "instance", block["target"][k])
        if pair:
            _arrow(ax, pair[0], pair[1], LINE_GREY,
                   0.6 + 1.8 * (rates[k] / top), curve=0.16, alpha=0.75)

    for relation, sk, tk in (("publishes", "instance", "queue"),
                             ("consumes", "queue", "instance")):
        block = snapshot["edges"][relation]
        for k in range(len(block["source"])):
            pair = both_shown(sk, block["source"][k], tk, block["target"][k])
            if pair:
                _arrow(ax, pair[0], pair[1], ACCENT, 1.9)

    columns = {kind: snapshot["nodes"][kind]["columns"] for kind in BAND}
    slot = {kind: (columns[kind].index(encoded[kind])
                   if encoded.get(kind) in columns[kind] else None)
            for kind in ("instance", "host")}

    def row_of(kind: str, key: str):
        i = here[kind].get(key)
        return snapshot["nodes"][kind]["X"][i] if i is not None else None

    for kind in BAND:
        for key in layout.order[kind]:
            x, y = pos[key]
            name = layout.label[key]
            row = row_of(kind, key)
            absent = row is None

            if kind == "host":
                value = row[slot["host"]] if row and slot["host"] is not None else None
                shade = _shade(value, bounds.get("host"))
                ax.scatter([x], [y], s=420, marker="s",
                           facecolor="white" if shade is None else str(1 - shade),
                           edgecolor=PALE_GREY if absent else INK, linewidth=1.1,
                           linestyle="-" if shade is not None else "--", zorder=3)
                if absent:
                    ax.text(x, y - 0.17, name, ha="center", va="top",
                            fontsize=7.8, color=PALE_GREY)
                else:
                    pick = lambda c: (row[columns["host"].index(c)]
                                      if c in columns["host"] else None)
                    detail = (f"cpu {_num(pick('cpu_busy'), '%')}"
                              f"   mem {_num(pick('memory_available_min'), 'B')}"
                              f"\ncpu pressure {_num(pick('cpu_pressure'))}")
                    ax.text(x, y - 0.17, f"{name}\n{detail}", ha="center",
                            va="top", fontsize=7.8, color=INK, linespacing=1.5)

            elif kind == "queue":
                backlog = row[0] if row else None
                ax.scatter([x], [y], s=min(620 + 90 * (backlog or 0), 2600),
                           facecolor="white",
                           edgecolor=PALE_GREY if absent else ACCENT, linewidth=2.0,
                           linestyle="-" if backlog is not None else "--", zorder=3)
                detail = ""
                if row and row[2] is not None and row[3] is not None:
                    detail = (f"\nin {row[2]:.2f}/s    out {row[3]:.2f}/s"
                              f"\nimbalance {row[4]:+.2f}/s")
                if row:
                    detail += (f"\nbacklog {_num(backlog)}"
                               f"    {_plural(row[5], 'consumer')}")
                ax.text(x, y + 0.22, name + detail, ha="center", va="bottom",
                        fontsize=9, color=PALE_GREY if absent else ACCENT,
                        linespacing=1.5)

            else:
                value = (row[slot["instance"]]
                         if row and slot["instance"] is not None else None)
                shade = _shade(value, bounds.get("instance"))
                ax.scatter([x], [y], s=165,
                           facecolor="white" if shade is None else str(1 - shade),
                           edgecolor=PALE_GREY if absent else INK, linewidth=0.9,
                           linestyle="-" if shade is not None else "--", zorder=3)
                short = layout.short.get(key, name)
                ax.text(x, y - 0.09, short, ha="right", va="top", fontsize=7.2,
                        rotation=42, rotation_mode="anchor",
                        color=PALE_GREY if absent else INK)

    span = bounds.get("instance")
    if span:
        x0, w, yb = 0.02, 0.13, -0.86
        for k in range(24):
            ax.add_patch(plt.Rectangle((x0 + k * w / 24, yb), w / 24, 0.075,
                                       facecolor=str(1 - (0.06 + 0.62 * k / 23)),
                                       edgecolor="none", zorder=2))
        ax.add_patch(plt.Rectangle((x0, yb), w, 0.075, fill=False,
                                   edgecolor=LINE_GREY, linewidth=0.6, zorder=3))
        ax.text(x0, yb - 0.03, _num(span[0]), fontsize=7, ha="left", va="top",
                color=LINE_GREY)
        ax.text(x0 + w, yb - 0.03, _num(span[1]), fontsize=7, ha="right",
                va="top", color=LINE_GREY)
        ax.text(x0, yb + 0.10, f"instance fill: {encoded['instance']}",
                fontsize=7.5, ha="left", va="bottom", color=INK)
        ax.text(x0 + w + 0.02, yb + 0.015, "dashed outline: no data",
                fontsize=7, ha="left", va="bottom", color=LINE_GREY)

    info = snapshot["window"]
    title = f"{info['start_utc']} UTC   ·   {info['duration_s']:.0f} s window"
    if layout.queue:
        title += f"   ·   queue {layout.queue}"
    ax.set_title(title, fontsize=11, color=INK, pad=16, loc="left")

    ax.legend(handles=[
        Line2D([], [], color=ACCENT, lw=1.9, label="publish / consume"),
        Line2D([], [], color=LINE_GREY, lw=1.4, label="calls (width = rate)"),
        Line2D([], [], color=PALE_GREY, lw=1.0, ls=(0, (1, 2)),
               label="executes on"),
    ], loc="lower right", frameon=False, fontsize=8.5, ncol=3,
        bbox_to_anchor=(1.0, -0.16))

    ax.set_xlim(-0.06, 1.06)
    ax.set_ylim(-1.10, 3.05)
    ax.axis("off")
    for kind, y in BAND.items():
        ax.text(-0.055, y, BAND_LABEL[kind], fontsize=8,
                color=ACCENT if kind == "queue" else LINE_GREY,
                va="center", ha="right", rotation=90)

    fig.tight_layout()
    base.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix in formats:
        target = base.with_suffix(f".{suffix}")
        fig.savefig(target, dpi=dpi, bbox_inches="tight", facecolor="white")
        written.append(target)
    plt.close(fig)
    return written
