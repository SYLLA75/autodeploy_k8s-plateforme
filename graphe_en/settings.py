"""
Read and validate config.yaml.

Every parameter of the pipeline lives in that one file. Nothing is hard-coded
anywhere else, and nothing is silently defaulted without saying so: an unknown
key is an error rather than a value quietly ignored, because a typo in a
configuration file is otherwise indistinguishable from a setting that had no
effect.

Credentials may be left empty in the file, in which case they are read from the
environment. A secret written into a configuration file eventually gets
committed; the file is created with restrictive permissions and listed in
.gitignore, but the environment remains the safer place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    "source": {
        "endpoint": None, "bucket": None, "prefix": "otel-data",
        "region": "us-east-1", "access_key": "", "secret_key": "",
    },
    "range": {"date": None, "from": "00:00", "to": "23:59", "max_files": 400},
    "windows": {"width_s": 60.0, "step_s": None, "max": None, "edge_margin": 0},
    "graph": {
        "namespace": None, "slope_horizon": 3, "sampling_rate": 1.0,
        "quantiles": [0.50, 0.95, 0.99],
    },
    "export": {
        "pytorch_geometric": False, "missing": "mask", "scaler": "none",
        "scaler_file": "scaler.json", "device": "cpu",
        "add_reverse_edges": False,
    },
    "figures": {
        "enabled": True, "windows": "all", "queue": None,
        "views": ["queue", "full"],
        "format": ["svg"],
        "node_value": "cpu_rate", "host_value": "cpu_busy", "dpi": 170,
    },
    "runtime": {"auto_install": True, "output_dir": "runs"},
}

ENV_FALLBACK = {
    "endpoint": "OBS_S3_ENDPOINT", "bucket": "OBS_S3_BUCKET",
    "prefix": "OBS_S3_PREFIX", "region": "OBS_S3_REGION",
    "access_key": "OBS_S3_ACCESS_KEY", "secret_key": "OBS_S3_SECRET_KEY",
}

CHOICES = {
    ("export", "missing"): ("mask", "mean", "zero"),
    ("export", "scaler"): ("write", "apply", "none"),
    ("export", "device"): ("cpu", "cuda", "auto"),
}


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    source: dict
    range: dict
    windows: dict
    graph: dict
    export: dict
    figures: dict
    runtime: dict
    path: Path
    raw: dict = field(repr=False, default_factory=dict)

    # -- convenience -------------------------------------------------------
    @property
    def day(self) -> Date:
        return self.range["date"]

    @property
    def width(self) -> float:
        return float(self.windows["width_s"])

    @property
    def step(self) -> float:
        s = self.windows["step_s"]
        return float(self.width if s in (None, "", 0) else s)

    def describe(self) -> list[tuple[str, str]]:
        """What to print back to the user, so the run is self-documenting."""
        return [
            ("store", f"{self.source['endpoint']}/{self.source['bucket']}/"
                      f"{self.source['prefix']}"),
            ("range", f"{self.day} {self.range['from']} -> {self.range['to']}"),
            ("windows", f"width {self.width:g} s, step {self.step:g} s"
                        + ("" if self.step == self.width else "  (sliding)")),
            ("namespace", self.graph["namespace"] or "all"),
            ("slope horizon", f"{self.graph['slope_horizon']} windows"),
            ("sampling rate", f"{self.graph['sampling_rate']:g}"),
        ]


def _merge(defaults: dict, given: dict, section: str) -> dict:
    unknown = set(given) - set(defaults)
    if unknown:
        raise ConfigError(
            f"unknown key(s) in section '{section}': {', '.join(sorted(unknown))}\n"
            f"  accepted: {', '.join(sorted(defaults))}")
    out = dict(defaults)
    out.update({k: v for k, v in given.items() if v is not None or k in given})
    return out


def load(path: Path) -> Settings:
    import yaml

    if not path.exists():
        raise ConfigError(f"{path} not found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a mapping")

    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown))}\n"
                          f"  accepted: {', '.join(DEFAULTS)}")

    merged = {name: _merge(DEFAULTS[name], raw.get(name) or {}, name)
              for name in DEFAULTS}

    src = merged["source"]
    for key, var in ENV_FALLBACK.items():
        if not src.get(key):
            src[key] = os.environ.get(var) or src.get(key)
    for key in ("endpoint", "bucket"):
        if not src.get(key):
            raise ConfigError(f"source.{key} is required "
                              f"(or set {ENV_FALLBACK[key]} in the environment)")
    for key in ("access_key", "secret_key"):
        if not src.get(key):
            raise ConfigError(
                f"source.{key} is empty and {ENV_FALLBACK[key]} is not set")

    rng = merged["range"]
    if rng["date"] in (None, "", "today"):
        rng["date"] = Date.today()
    elif isinstance(rng["date"], str):
        rng["date"] = Date.fromisoformat(rng["date"])
    for key in ("from", "to"):
        value = str(rng[key])
        try:
            h, m = value.split(":")
            if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                raise ValueError
        except ValueError:
            raise ConfigError(f"range.{key} must be HH:MM, got {value!r}")
        rng[key] = value

    w = merged["windows"]
    if float(w["width_s"]) <= 0:
        raise ConfigError("windows.width_s must be positive")
    step = w["step_s"] if w["step_s"] not in (None, "", 0) else w["width_s"]
    if float(step) > float(w["width_s"]):
        raise ConfigError(
            f"windows.step_s ({step}) is larger than windows.width_s "
            f"({w['width_s']}): gaps would be left between windows")

    g = merged["graph"]
    if int(g["slope_horizon"]) < 2:
        raise ConfigError("graph.slope_horizon must be at least 2")
    if not 0 < float(g["sampling_rate"]) <= 1:
        raise ConfigError("graph.sampling_rate must be within ]0, 1]")

    fig = merged["figures"]
    chosen = fig["windows"]
    if chosen in (None, "", "all"):
        fig["windows"] = "all"
    elif isinstance(chosen, int):
        fig["windows"] = [chosen]
    elif isinstance(chosen, list):
        if not chosen:
            raise ConfigError("figures.windows is an empty list; use \"all\" "
                              "to draw every window")
        for item in chosen:
            if not isinstance(item, int) or item == 0:
                raise ConfigError(
                    f"figures.windows accepts \"all\" or a list of non-zero "
                    f"integers (1 is the first, -1 the last); got {item!r}")
    else:
        raise ConfigError(f"figures.windows must be \"all\" or a list of "
                          f"integers, got {chosen!r}")

    views = fig["views"]
    if isinstance(views, str):
        views = [views]
    if not isinstance(views, list) or not views:
        raise ConfigError('figures.views must be a non-empty list drawn from '
                          '"queue" and "full"')
    unknown = [v for v in views if v not in ("queue", "full")]
    if unknown:
        raise ConfigError(f'figures.views accepts only "queue" and "full"; '
                          f'got {", ".join(map(repr, unknown))}')
    if "queue" in views and not fig["queue"]:
        views = [v for v in views if v != "queue"] or ["full"]
    fig["views"] = list(dict.fromkeys(views))

    formats = fig["format"]
    if isinstance(formats, str):
        formats = [formats]
    if not isinstance(formats, list) or not formats:
        raise ConfigError('figures.format must be a non-empty list drawn from '
                          '"svg", "pdf" and "png"')
    unknown = [f for f in formats if f not in ("svg", "pdf", "png")]
    if unknown:
        raise ConfigError(f'figures.format accepts only "svg", "pdf" and "png"; '
                          f'got {", ".join(map(repr, unknown))}')
    fig["format"] = list(dict.fromkeys(formats))

    for (section, key), allowed in CHOICES.items():
        value = merged[section][key]
        if value not in allowed:
            raise ConfigError(f"{section}.{key} must be one of "
                              f"{', '.join(allowed)}, got {value!r}")

    if merged["export"]["pytorch_geometric"] is False and \
            merged["export"]["scaler"] == "write":
        merged["export"]["scaler"] = "none"

    return Settings(path=path, raw=raw, **merged)
