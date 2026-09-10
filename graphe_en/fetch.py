"""
Fetching a time range from the object store.

The store lays files out by date:

    otel-data/year=2026/month=09/day=09/hour=15/minute=01/traces_*.json.gz

That layout is used to request only the slice that is wanted, instead of listing
the whole bucket.

This module does not window anything. It fetches a range and stops there.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from pathlib import Path

KEY = re.compile(r"year=(\d{4})/month=(\d{2})/day=(\d{2})/hour=(\d{2})/minute=(\d{2})/")


@dataclass
class Fetched:
    files: list[Path]
    traces: int
    metrics: int
    compressed_bytes: int
    manifest: Path


def _client(source: dict):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=source["endpoint"],
        aws_access_key_id=source["access_key"],
        aws_secret_access_key=source["secret_key"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name=source.get("region") or "us-east-1",
    )


def _minute_of_day(key: str) -> int | None:
    m = KEY.search(key)
    return int(m.group(4)) * 60 + int(m.group(5)) if m else None


def _hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def list_objects(source: dict, day: Date, start: str, end: str) -> list[dict]:
    """List the objects of the range. Only the day's prefix is walked."""
    s3 = _client(source)
    prefix = (f"{source['prefix'].rstrip('/')}/"
              f"year={day.year:04d}/month={day.month:02d}/day={day.day:02d}/")
    lo, hi = _hhmm(start), _hhmm(end)
    found = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=source["bucket"], Prefix=prefix):
        for obj in page.get("Contents", []):
            pos = _minute_of_day(obj["Key"])
            if pos is None or not (lo <= pos <= hi):
                continue
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.startswith("traces_"):
                kind = "traces"
            elif name.startswith("metrics_"):
                kind = "metrics"
            else:
                continue
            found.append({"key": obj["Key"], "size": obj["Size"],
                          "kind": kind, "position": pos})
    return sorted(found, key=lambda o: (o["position"], o["key"]))


def download(source: dict, objects: list[dict], target: Path,
             progress=None) -> Fetched:
    """
    Download, decompress, and keep the original name in the local one.

    A local file whose origin cannot be traced makes the analysis
    unrepeatable, so a manifest recording every key is written alongside.
    """
    target.mkdir(parents=True, exist_ok=True)
    s3 = _client(source)
    paths: list[Path] = []
    for i, obj in enumerate(objects, 1):
        m = KEY.search(obj["key"])
        name = obj["key"].rsplit("/", 1)[-1].removesuffix(".gz")
        local = target / f"{m.group(4)}-{m.group(5)}_{name}"
        if not local.exists():
            raw = s3.get_object(Bucket=source["bucket"], Key=obj["key"])["Body"].read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            local.write_bytes(raw)
        paths.append(local)
        if progress:
            progress(i, len(objects))

    manifest = target / "origin.json"
    manifest.write_text(json.dumps({
        "store": source["endpoint"],
        "bucket": source["bucket"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [{"local": p.name, "key": o["key"], "bytes": o["size"]}
                  for o, p in zip(objects, paths)],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return Fetched(
        files=paths,
        traces=sum(1 for o in objects if o["kind"] == "traces"),
        metrics=sum(1 for o in objects if o["kind"] == "metrics"),
        compressed_bytes=sum(o["size"] for o in objects),
        manifest=manifest,
    )
