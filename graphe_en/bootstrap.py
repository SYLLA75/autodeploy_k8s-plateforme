"""
Make sure the libraries this pipeline needs are present.

Reproducibility means a fresh machine must be able to run this without a manual
setup ritual, so missing packages are installed automatically. Two guard rails,
both deliberate:

  * Installation only happens inside a virtual environment. On a system Python
    the run stops and prints the command to type. Installing into a system
    Python breaks the operating system's own tools, and no script should decide
    that on the user's behalf.

  * Every package is pinned in REQUIREMENTS with the exact index it comes from.
    PyTorch in particular must come from the CPU index unless a GPU build is
    wanted, otherwise pip pulls two gigabytes of CUDA that will never be used.

Nothing here is imported by the pipeline itself: this module only checks and
installs, so it must stay importable with the standard library alone.
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from dataclasses import dataclass

CPU_INDEX = "https://download.pytorch.org/whl/cpu"


@dataclass(frozen=True)
class Requirement:
    module: str                  # what `import` expects
    package: str                 # what pip expects
    purpose: str
    index: str | None = None
    optional: bool = False


REQUIREMENTS = {
    "config": Requirement("yaml", "PyYAML", "reading config.yaml"),
    "fetch": Requirement("boto3", "boto3", "reading the object store"),
    "figures": Requirement("matplotlib", "matplotlib", "rendering figures",
                           optional=True),
    "torch": Requirement("torch", "torch", "tensors", index=CPU_INDEX,
                         optional=True),
    "pyg": Requirement("torch_geometric", "torch_geometric",
                       "heterogeneous graph objects", optional=True),
}


def in_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


def version_of(module: str) -> str:
    try:
        m = importlib.import_module(module)
        return getattr(m, "__version__", "present")
    except Exception:
        return "present"


def is_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def install(req: Requirement) -> tuple[bool, str]:
    """Install one requirement. Returns (succeeded, message)."""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", req.package]
    if req.index:
        cmd += ["--index-url", req.index]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, "timed out after 30 minutes"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return False, tail[-1] if tail else f"pip exited {proc.returncode}"
    importlib.invalidate_caches()
    return True, version_of(req.module)


def manual_command(req: Requirement) -> str:
    index = f" --index-url {req.index}" if req.index else ""
    return f"pip install {req.package}{index}"
