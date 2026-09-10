# otel-graph

Builds a heterogeneous temporal graph from OpenTelemetry archives: from the
object store to the figure, in one command.

```bash
python3 run.py
```

Everything is set in `config.yaml`. Nothing is hard-coded elsewhere.

## What it does

```
  1  preflight   runtime, configuration, dependencies
  2  fetch       download the time range from the object store
  3  window      cut the range into windows
  4  nodes       list what exists, with a stable identity
  5  features    compute the numbers each node carries
  6  edges       reconstruct who talks to whom
  7  export      write the snapshots, and optionally the tensors
  8  render      draw the requested windows
```

## The graph

Three kinds of node, four relations, following the formalisation:

| node | components | what it is |
|------|-----------|------------|
| `instance` | 19 | one running copy of a service — a pod |
| `queue` | 6 | one message queue |
| `host` | 5 | one machine of the cluster — a node |

| relation | direction | components |
|----------|-----------|-----------|
| `calls` | instance → instance | 5 |
| `publishes` | instance → queue | 1 |
| `consumes` | queue → instance | 1 |
| `executes_on` | instance → host | 0, purely structural |

## Output

One timestamped directory per run; nothing is ever overwritten.

```
runs/20260909-214710/
    run.log                     everything the terminal printed
    raw/                        the fetched archives, plus origin.json
    graph/
        manifest.json           settings, provenance, dimensions, departures
        window_0001.json ...    the snapshots
        graph.pt                PyTorch Geometric tensors (optional)
        environment.json        versions and device used
    figures/
        window_0001_food_delivery.png
```

## Installation

None. On first run, missing packages are installed automatically — but only
inside a virtual environment; on a system interpreter the run stops and prints
the command to type.

```bash
python3 -m venv .venv
./.venv/bin/python run.py
```

`--no-install` disables that entirely.

## Credentials

Leave `source.access_key` and `source.secret_key` empty in `config.yaml` and set
`OBS_S3_ACCESS_KEY` / `OBS_S3_SECRET_KEY` in the environment instead. A secret
written into a configuration file eventually gets committed. `config.yaml` is
listed in `.gitignore` for the same reason.

## Two settings that decide the science

**Window width and step.** `step = width` gives back-to-back windows; a smaller
step makes them overlap. Overlap matters only when the fault lasts about as long
as a window: a fault at least twice the window width is measured at full
strength either way. Rule of thumb:

> width ≤ fault duration / 2, then step = width.

Never choose a width equal to the fault duration — that is the worst case, and
no step guarantees seeing the fault whole.

**Scaling.** `export.scaler: write` fits means and standard deviations on the
current campaign; `apply` reuses them. Fit on the **healthy** campaign only,
then apply to the faulty one. Fitting on both lets the anomaly into the
normalisation, which then partly erases it, and nothing signals that the results
are wrong.

## Departures from the paper

Recorded in every `manifest.json`, so the dataset documents itself.

1. **Queue component 3, publish rate.** `rabbitmq_queue_messages_published_total`
   does not exist on RabbitMQ 3.8. The rate is derived from publication spans,
   symmetrically to component 4, which the paper already reconstructs from
   consumption spans. Both rates are then measured the same way, so their
   difference is homogeneous.
2. **The `increase` operator.** Defined in the paper as last minus first, which
   goes negative when a restart resets a counter. Rises between consecutive
   samples are summed instead.
3. **Duplicated consumptions.** One consumed message emits two identical spans.
   They are deduplicated; otherwise the consume rate doubles and the imbalance
   turns negative on a healthy queue.
4. **Reported, not fixed.** Instance component 4 and consumption relation
   component 1 are the same quantity. It appears twice in the representation.

## Notes on the figures

**The layout is decided once, over the whole campaign** — which nodes appear as
much as where they sit. A first version picked the queue's neighbours window by
window and fell back to the whole graph when a window had no traffic: the same
run then produced two incomparable kinds of figure, some with four nodes and
some with sixty-five. Selecting the nodes once, over the union of every window,
keeps the series flippable like the frames of a film, which is the only way a
fault developing over time can be seen. A node that exists in the campaign but
not in the window being drawn keeps its place, pale and dotted; removing it
would shift everything else.

Positions come from names, never from a force-directed solver, so two
consecutive windows are superimposable. Greys rather than colours,
so the figure survives black-and-white printing; the single colour accent is
reserved for the queue. The grey scale spans the whole campaign, not the window
being drawn, so an unchanged instance keeps its shade across windows.

### Labels

A pod name carries three parts:

```
   ts-delivery-service-7fdf74bc6-8jxvq
   |____ service _____| |__ rs __| |_ id _|
```

Only the service is worth reading, so the rest is dropped — `delivery`. But
three replicas of one service would then produce three identical labels, and the
reader could not tell which circle is which. That is exactly the question that
matters when a single replica falls behind.

The trailing identifier is therefore added back **only where a label would
otherwise be ambiguous**:

```
   delivery·tpd8z    delivery·8j82t    delivery·rxtnr    food
```

Unique services stay short.

### Redrawing without refetching

```bash
python3 run.py --render-only runs/20260910-034521
```

Changing which component fills the nodes, or the output format, does not need
the archives again — the snapshots hold everything the figures use. Seven
seconds instead of a full fetch.

Text goes where nodes are few (queues, hosts); the node fill carries the value
where they are many (instances). `figures.node_value` and `figures.host_value`
accept any component name.

Two views are drawn per window by default:

```yaml
figures:
  queue: food_delivery
  views: [queue, full]      # queue - the queue and who touches it
                            # full  - every node of the namespace
```

Eleven windows then give twenty-two figures. Each view has its own layout, both
fixed over the campaign, so the frames of one view stay comparable with each
other. `views: [full]` or `queue: null` leaves only the full graph.

### Format

```yaml
figures:
  format: [svg]             # svg | pdf | png, one or several
  dpi: 170                  # png only
```

`svg` and `pdf` keep the drawing as geometry: it enlarges without pixels and its
text stays selectable and searchable, which is what a paper needs. `png` is a
flat image, fine for a quick look or a slide. Measured on the close-up view of
one window:

| format | size | |
|--------|------|---|
| pdf | 20 KB | smallest, and what LaTeX prefers |
| svg | 56 KB | opens in any browser, editable in Inkscape |
| png | 93 KB | largest, and pixelated when enlarged |

Windows are selected separately:

```yaml
figures:
  windows: all              # every window (default)
  windows: [1, 5, -1]       # the first, the fifth and the last
  windows: [4]              # one only
```

A window where the queue has no traffic still gets its close-up, with the same
nodes in the same places and no arrows. That is the point: the difference
between two frames is what shows a fault appearing.
