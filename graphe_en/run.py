#!/usr/bin/env python3
"""
otel-graph — build a heterogeneous temporal graph from OpenTelemetry archives.

    python3 run.py                    use config.yaml
    python3 run.py -c other.yaml      use another configuration
    python3 run.py --no-install       never install anything

Every parameter lives in the configuration file. This script only orchestrates:

    1  preflight   runtime, configuration, dependencies
    2  fetch       download the time range from the object store
    3  window      cut the range into windows
    4  nodes       list what exists, with a stable identity
    5  features    compute the numbers each node carries
    6  edges       reconstruct who talks to whom
    7  export      write the snapshots, and optionally the tensors
    8  render      draw the requested windows

Each run writes into its own timestamped directory. Nothing is overwritten, and
a run can be replayed exactly as it was.

Only the standard library is imported at module level, because step 1 may have
to install the rest.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import bootstrap
from console import Console

HERE = Path(__file__).resolve().parent
STEPS = 8


def _preflight(console: Console, args) -> "settings_module.Settings":
    console.step("preflight", "verifying runtime")

    venv = bootstrap.in_virtualenv()
    console.ok(f"python {sys.version.split()[0]}, "
               f"{'virtual environment' if venv else 'system interpreter'}")
    if not venv:
        console.warn("not in a virtual environment, installation is disabled")

    def require(name: str, allow_install: bool) -> bool:
        req = bootstrap.REQUIREMENTS[name]
        if bootstrap.is_available(req.module):
            console.ok(f"{req.package} {bootstrap.version_of(req.module)}")
            return True
        console.missing(f"{req.package} — needed for {req.purpose}")
        if not allow_install:
            console.fail(f"install it with: {bootstrap.manual_command(req)}")
            return False
        done, detail = bootstrap.install(req)
        if done:
            console.ok(f"installed {req.package} {detail}")
        else:
            console.fail(f"could not install {req.package}: {detail}")
        return done

    may_install = venv and not args.no_install
    if not require("config", may_install):
        raise SystemExit(1)

    import settings as settings_module
    try:
        conf = settings_module.load(Path(args.config))
    except settings_module.ConfigError as exc:
        console.fail(f"configuration: {exc}")
        raise SystemExit(1)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    conf.run_dir = Path(conf.runtime["output_dir"]).expanduser()
    if not conf.run_dir.is_absolute():
        conf.run_dir = HERE / conf.run_dir
    conf.run_dir = conf.run_dir / stamp
    console.attach_log(conf.run_dir / "run.log")
    console.ok(f"configuration {args.config}")

    may_install = may_install and conf.runtime["auto_install"]
    needed = ["fetch"]
    if conf.figures["enabled"]:
        needed.append("figures")
    if conf.export["pytorch_geometric"]:
        needed += ["torch", "pyg"]
    for name in needed:
        if not require(name, may_install):
            req = bootstrap.REQUIREMENTS[name]
            if req.optional:
                console.warn(f"continuing without {req.package}")
            else:
                raise SystemExit(1)

    for label, value in conf.describe():
        console.note(f"{label:<16}{value}")
    return conf


def _fetch(console: Console, conf) -> "fetch.Fetched":
    import fetch as fetch_module

    source = conf.source
    console.step("fetch", f"{source['endpoint']}/{source['bucket']}")
    objects = fetch_module.list_objects(source, conf.day, conf.range["from"],
                                        conf.range["to"])
    if not objects:
        console.fail("no object in that range")
        raise SystemExit(1)

    size = fetch_module.human_bytes(sum(o["size"] for o in objects))
    traces = sum(1 for o in objects if o["kind"] == "traces")
    metrics = len(objects) - traces
    console.ok(f"{len(objects)} objects ({traces} traces, {metrics} metrics), "
               f"{size} compressed")

    limit = conf.range["max_files"]
    if limit and len(objects) > limit:
        console.fail(f"{len(objects)} objects exceed range.max_files ({limit})")
        raise SystemExit(1)

    target = conf.run_dir / "raw"
    shown = {"last": -1}

    def progress(done: int, total: int) -> None:
        pct = 100 * done // total
        if pct >= shown["last"] + 25 or done == total:
            shown["last"] = pct
            console.info(f"downloading {done}/{total}")

    got = fetch_module.download(source, objects, target, progress)
    console.ok(f"fetched into {target.relative_to(conf.run_dir)}/")
    console.ok(f"provenance recorded in {got.manifest.name}")
    return got


def _window(console: Console, conf, got):
    import windows as windows_module

    console.step("window", f"width {conf.width:g} s, step {conf.step:g} s")
    spans, samples = windows_module.load(got.files)
    console.ok(f"{len(spans)} spans, {len(samples)} samples")

    kept, report = windows_module.cut(
        spans, samples, conf.width, conf.step,
        margin=int(conf.windows["edge_margin"] or 0),
        limit=conf.windows["max"])

    console.ok(f"{report['built']} built, {report['kept']} retained")
    console.note(f"discarded: {report['dropped_coverage']} outside coverage, "
                 f"{report['dropped_margin']} margin, "
                 f"{report['dropped_limit']} over limit")
    if not kept:
        console.fail("no usable window — widen the range or reduce the width")
        raise SystemExit(1)

    for w, reason in report["discarded"]:
        console.note(f"discarded {w.label}  covered {w.covered_s:5.1f} s  "
                     f"{len(w.spans):6d} spans  ({reason})")

    thin = [w for w in kept if w.covered_s < 0.9 * conf.width]
    if thin:
        subject = "window covers" if len(thin) == 1 else "windows cover"
        console.warn(f"{len(thin)} retained {subject} under 90% of their width")
    return kept, report


def _nodes(console: Console, conf, kept):
    import nodes as nodes_module

    scope = conf.graph["namespace"] or "all namespaces"
    console.step("nodes", f"instances, queues, hosts — {scope}")
    series = [nodes_module.collect(w, conf.graph["namespace"]) for w in kept]

    rows = []
    for w, found in zip(kept, series):
        counts = {k: sum(1 for n in found.values() if n.kind == k)
                  for k in nodes_module.KINDS}
        rows.append([w.label, counts["instance"], counts["queue"],
                     counts["host"], len(found)])
    console.ok(f"{sum(len(s) for s in series)} node-instances over "
               f"{len(kept)} windows")
    console.table(["window", "instances", "queues", "hosts", "total"], rows)

    seen: dict[str, int] = {}
    for found in series:
        for key in found:
            seen[key] = seen.get(key, 0) + 1
    intermittent = sum(1 for v in seen.values() if v < len(kept))
    if intermittent:
        console.warn(f"{intermittent} nodes absent from at least one window")
        console.note("usually a source that started late, not instability")
    return series


def _features(console: Console, conf, kept, node_series):
    import features as features_module

    console.step("features", ", ".join(
        f"{len(features_module.COLUMNS[k])} {k}" for k in ("instance", "queue", "host")
    ) + " components")
    vectors = features_module.compute(
        kept, conf.graph["namespace"], conf.width,
        int(conf.graph["slope_horizon"]),
        float(conf.graph["sampling_rate"]),
        tuple(conf.graph["quantiles"]),
        node_series=node_series)

    rows = []
    for w, vecs in zip(kept, vectors):
        row = [w.label]
        for kind in features_module.COLUMNS:
            group = [v for v in vecs.values() if v.node.kind == kind]
            row.append(f"{100*sum(v.completeness for v in group)/len(group):.0f}%"
                       if group else "-")
        rows.append(row)
    console.ok("computed")
    console.table(["window", "instance", "queue", "host"], rows)

    never = []
    for kind, columns in features_module.COLUMNS.items():
        for j, name in enumerate(columns):
            if not any(v.values[j] is not None for vecs in vectors
                       for v in vecs.values() if v.node.kind == kind):
                never.append(f"{kind}.{name}")
    if never:
        console.warn(f"never produced: {', '.join(never)}")
    else:
        console.ok("every component produced at least once")
    return vectors


def _edges(console: Console, conf, kept, vectors):
    import edges as edges_module

    console.step("edges", "calls, publishes, consumes, executes on")
    built = []
    rows = []
    for w, vecs in zip(kept, vectors):
        found = {key: v.node for key, v in vecs.items()}
        group, report = edges_module.build(
            w, found, conf.width, float(conf.graph["sampling_rate"]),
            tuple(conf.graph["quantiles"]))
        built.append((group, report))
        counts = {r: sum(1 for e in group if e.relation == r)
                  for r in edges_module.RELATIONS}
        res = report["resolution"]
        rows.append([w.label, counts["calls"], counts["publishes"],
                     counts["consumes"], counts["executes_on"],
                     f"{100*res:.1f}%" if res is not None else "-"])
    console.ok(f"{sum(len(g) for g, _ in built)} edges over {len(kept)} windows")
    console.table(["window", "calls", "publishes", "consumes", "executes on",
                   "resolved"], rows)

    worst = min((r["resolution"] for _, r in built
                 if r["resolution"] is not None), default=None)
    if worst is not None and worst < 0.95:
        console.warn(f"call resolution drops to {100*worst:.1f}% — some parent "
                     f"spans fall outside the fetched range")
    return built


def _export(console: Console, conf, kept, vectors, built, got, cut_report):
    import snapshot as snapshot_module

    console.step("export", "snapshots and manifest")
    snapshots = [snapshot_module.build(w, vecs, group, report)
                 for w, vecs, (group, report) in zip(kept, vectors, built)]
    graph_dir = conf.run_dir / "graph"
    paths = snapshot_module.write(snapshots, graph_dir)
    (graph_dir / "manifest.json").write_text(
        __import__("json").dumps(
            snapshot_module.manifest(conf, got, cut_report, len(paths),
                                     snapshots),
            ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(p.stat().st_size for p in graph_dir.glob("*.json"))
    console.ok(f"{len(paths)} snapshots + manifest, {total/1024:.0f} KB")

    holes = sum(1 for s in snapshots for kind in s["nodes"]
                for row in s["nodes"][kind]["X"] for v in row if v is None)
    cells = sum(len(row) for s in snapshots for kind in s["nodes"]
                for row in s["nodes"][kind]["X"])
    console.ok(f"{holes}/{cells} node values absent "
               f"({100*holes/cells:.1f}%), written null, never 0")

    if not conf.export["pytorch_geometric"]:
        console.skip("pytorch geometric export disabled")
        return snapshots

    import export_pyg

    device = export_pyg.resolve_device(conf.export["device"])
    console.ok(f"device {device}")

    scaler = None
    mode = conf.export["scaler"]
    scaler_path = Path(conf.export["scaler_file"])
    if not scaler_path.is_absolute():
        scaler_path = HERE / scaler_path
    if mode == "write":
        scaler = export_pyg.fit_scaler(snapshots)
        scaler_path.write_text(__import__("json").dumps(
            {"source": str(graph_dir), "scaler": scaler},
            ensure_ascii=False, indent=1), encoding="utf-8")
        console.ok(f"scaling fitted on this campaign -> {scaler_path.name}")
        console.note("only correct if this campaign is the healthy baseline")
    elif mode == "apply":
        if not scaler_path.exists():
            console.fail(f"{scaler_path} not found")
            raise SystemExit(1)
        loaded = __import__("json").loads(scaler_path.read_text())
        scaler = loaded["scaler"]
        console.ok(f"scaling applied, fitted on {loaded.get('source')}")
    else:
        console.warn("no scaling — magnitudes span 1e-2 to 1e8, a model trained "
                     "as is would only see memory")

    tensors = export_pyg.convert(snapshots, scaler, conf.export["missing"],
                                 bool(conf.export["add_reverse_edges"]), device)
    target = export_pyg.save(tensors, graph_dir / "graph.pt", device, False)
    console.ok(f"{target.name}, {target.stat().st_size/1024:.0f} KB "
               f"(cpu tensors, portable)")

    import torch
    first = tensors[0]["instance"].x
    console.note(f"instance tensor {tuple(first.shape)}  "
                 f"min {float(first.min()):+.3g}  max {float(first.max()):+.3g}  "
                 f"nan {bool(torch.isnan(first).any())}")
    return snapshots


def _render(console: Console, conf, snapshots):
    console.step("render", "figures")
    if not conf.figures["enabled"]:
        console.skip("figures disabled")
        return
    try:
        import render
    except ImportError:
        console.fail("matplotlib unavailable, skipping figures")
        return

    encoded = {"instance": conf.figures["node_value"],
               "host": conf.figures["host_value"]}
    for kind, column in encoded.items():
        available = snapshots[0]["nodes"][kind]["columns"]
        if column not in available:
            console.fail(f"figures.{'node' if kind == 'instance' else 'host'}"
                         f"_value '{column}' is not a {kind} component")
            console.note(f"available: {', '.join(available)}")
            return

    def count(n: int, word: str) -> str:
        return f"{n} {word}" if n == 1 else f"{n} {word}s"

    queue = conf.figures["queue"]
    # One layout per view, each fixed over the whole campaign. Two views of the
    # same window answer different questions: the close-up shows the queue and
    # who touches it, the full graph shows where that sits in the system.
    layouts = []
    for view in conf.figures["views"]:
        focus = queue if view == "queue" else None
        try:
            layout = render.plan(snapshots, focus)
        except SystemExit as exc:
            console.fail(str(exc))
            return
        size = layout.size
        suffix = queue if view == "queue" else "full"
        layouts.append((suffix, layout))
        console.ok(f"{view} layout: "
                   + ", ".join(count(size[k], k)
                               for k in ("instance", "queue", "host")))
    console.note("each layout is fixed over the campaign — the same nodes in "
                 "the same places in every figure of that view")

    bounds = render.scale_bounds(snapshots, encoded)
    for kind, pair in bounds.items():
        if pair and kind in encoded:
            console.note(f"{kind} fill: {encoded[kind]}  "
                         f"[{pair[0]:.4g}, {pair[1]:.4g}] over the campaign")

    figures = conf.run_dir / "figures"
    wanted = conf.figures["windows"]
    if wanted == "all":
        wanted = list(range(1, len(snapshots) + 1))
    # Beyond a dozen figures, one line each buries the rest of the run; the log
    # keeps every path anyway.
    verbose = len(wanted) <= 12
    formats = tuple(conf.figures["format"])
    total_figures = len(wanted) * len(layouts) * len(formats)
    plural = "format" if len(formats) == 1 else "formats"
    console.info(f"drawing {total_figures} files — {len(wanted)} windows x "
                 f"{len(layouts)} views x {len(formats)} {plural} "
                 f"({', '.join(formats)})")

    drawn = 0
    for position, choice in enumerate(wanted, 1):
        index = choice - 1 if choice > 0 else len(snapshots) + choice
        if not 0 <= index < len(snapshots):
            console.warn(f"window {choice} does not exist (1..{len(snapshots)})")
            continue
        made = []
        for suffix, layout in layouts:
            name = f"window_{index+1:04d}_{suffix}"
            try:
                paths = render.draw(snapshots[index], layout, figures / name,
                                    encoded, bounds, int(conf.figures["dpi"]),
                                    formats)
            except SystemExit as exc:
                console.fail(str(exc))
                continue
            drawn += len(paths)
            made.append(f"{suffix} "
                        + "/".join(f"{p.stat().st_size/1024:.0f}" for p in paths)
                        + " KB")
        if verbose and made:
            console.ok(f"window {index+1:04d}  ->  " + " · ".join(made))
        elif position % max(1, len(wanted) // 4) == 0 or position == len(wanted):
            console.info(f"drawn {position}/{len(wanted)} windows")

    total = sum(p.stat().st_size for p in figures.iterdir() if p.is_file())
    console.ok(f"{drawn} files in figures/, {total/1024:.0f} KB")


def _render_only(args) -> int:
    """
    Redraw an existing run's figures.

    Changing which component fills the nodes, or the output format, does not
    need the archives to be fetched again — the snapshots hold everything the
    figures use. Refetching a campaign to change a colour would be absurd.
    """
    import json

    console = Console(1)
    console.banner("otel-graph 1.0", "redrawing figures")
    run_dir = Path(args.render_only)
    graph_dir = run_dir / "graph"
    if not graph_dir.is_dir():
        graph_dir = run_dir                      # the graph directory itself
    files = sorted(graph_dir.glob("window_*.json"))
    if not files:
        console.fail(f"no snapshot in {graph_dir}")
        return 1

    import settings as settings_module
    try:
        conf = settings_module.load(Path(args.config))
    except settings_module.ConfigError as exc:
        console.fail(f"configuration: {exc}")
        return 1
    conf.run_dir = graph_dir.parent
    console.ok(f"{len(files)} snapshots in {graph_dir}")

    snapshots = [json.loads(f.read_text()) for f in files]
    _render(console, conf, snapshots)
    console.done(f"{len(snapshots)} windows redrawn", output=conf.run_dir)
    console.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--config", default=str(HERE / "config.yaml"))
    parser.add_argument("--no-install", action="store_true",
                        help="never install a missing package")
    parser.add_argument("--render-only", metavar="RUN_DIR",
                        help="redraw the figures of an existing run, without "
                             "fetching anything again")
    args = parser.parse_args()

    if args.render_only:
        return _render_only(args)

    console = Console(STEPS)
    console.banner("otel-graph 1.0",
                   "heterogeneous temporal graph builder")
    try:
        conf = _preflight(console, args)
        got = _fetch(console, conf)
        kept, cut_report = _window(console, conf, got)
        node_series = _nodes(console, conf, kept)
        vectors = _features(console, conf, kept, node_series)
        built = _edges(console, conf, kept, vectors)
        snapshots = _export(console, conf, kept, vectors, built, got, cut_report)
        _render(console, conf, snapshots)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code:
            console.done("aborted")
            console.close()
            return code
    except KeyboardInterrupt:
        console.fail("interrupted")
        console.done("aborted")
        console.close()
        return 130

    counts = snapshots[-1]["nodes"]
    console.done(
        f"{len(snapshots)} windows, "
        f"{len(counts['instance']['keys'])}/{len(counts['queue']['keys'])}/"
        f"{len(counts['host']['keys'])} nodes",
        output=conf.run_dir)
    console.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
