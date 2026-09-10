"""
Terminal output.

One line per event, always in the same shape, so the run can be followed at a
glance and diffed between two executions:

    [2026-09-09 21:45:02] [1/8] PREFLIGHT     verifying runtime
    [2026-09-09 21:45:02]   ->  boto3 1.43.90                             [   OK ]

Everything printed here is also appended to a log file, stripped of colour, so
the log is identical whether the run was interactive or not.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

WIDTH = 100
STATUS_W = 10
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class Console:
    """Prints progress, and keeps a plain-text copy of everything."""

    def __init__(self, total_steps: int, log_path: Path | None = None):
        self.total = total_steps
        self.step_no = 0
        self.started = time.monotonic()
        self.warnings = 0
        self.errors = 0
        self.colour = _supports_colour()
        self.log = None
        self._pending: list[str] = []
        if log_path:
            self.attach_log(log_path)

    def attach_log(self, log_path) -> None:
        """
        Open the log file, and flush whatever was printed before it existed.

        The output directory is named in the configuration, which itself cannot
        be read before the runtime has been checked. Without this buffer the
        first lines of every run would be missing from the log.
        """
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open("a", encoding="utf-8")
        for line in self._pending:
            self.log.write(line + "\n")
        self._pending.clear()
        self.log.flush()

    # ---------------------------------------------------------------- output
    def _c(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.colour else text

    def _emit(self, line: str) -> None:
        print(line, flush=True)
        plain = _ANSI.sub("", line)
        if self.log:
            self.log.write(plain + "\n")
            self.log.flush()
        else:
            self._pending.append(plain)

    def _stamp(self) -> str:
        return self._c(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", DIM)

    # ----------------------------------------------------------------- parts
    def banner(self, title: str, subtitle: str = "") -> None:
        self._emit("")
        self._emit(self._c(title, BOLD) + ("  " + self._c(subtitle, DIM) if subtitle else ""))
        self._emit(self._c("-" * WIDTH, DIM))

    def step(self, name: str, detail: str = "") -> None:
        self.step_no += 1
        counter = f"[{self.step_no}/{self.total}]"
        label = self._c(f"{name.upper():<13}", BOLD)
        self._emit(f"{self._stamp()} {self._c(counter, CYAN)} {label}"
                   + (f" {detail}" if detail else ""))

    def _line(self, text: str, status: str, colour: str) -> None:
        head = f"{self._stamp()}   ->  "
        plain_head = len(_ANSI.sub("", head))
        room = WIDTH - plain_head - STATUS_W
        body = text if len(text) <= room else text[: room - 1] + "…"
        pad = "." * max(1, room - len(body))
        tag = f"[{status:^6}]"
        self._emit(f"{head}{body} {self._c(pad, DIM)} {self._c(tag, colour)}")

    def ok(self, text: str) -> None:
        self._line(text, "OK", GREEN)

    def missing(self, text: str) -> None:
        self._line(text, "MISSING", YELLOW)

    def skip(self, text: str) -> None:
        self._line(text, "SKIP", DIM)

    def fail(self, text: str) -> None:
        self.errors += 1
        self._line(text, "FAIL", RED)

    def warn(self, text: str) -> None:
        self.warnings += 1
        self._line(text, "WARN", YELLOW)

    def info(self, text: str) -> None:
        self._emit(f"{self._stamp()}   ->  {text}")

    def note(self, text: str) -> None:
        """A remark that is not the outcome of an action."""
        self._emit(f"{self._stamp()}       {self._c(text, DIM)}")

    def table(self, header: list[str], rows: list[list[str]],
              widths: list[int] | None = None) -> None:
        widths = widths or [max(len(str(r[i])) for r in [header] + rows) + 2
                            for i in range(len(header))]
        pad = " " * 24
        self._emit(pad + self._c("".join(h.rjust(w) for h, w in zip(header, widths)), DIM))
        for r in rows:
            self._emit(pad + "".join(str(c).rjust(w) for c, w in zip(r, widths)))

    def done(self, summary: str, output: Path | None = None) -> None:
        elapsed = time.monotonic() - self.started
        m, s = divmod(int(elapsed), 60)
        span = f"{m}m {s:02d}s" if m else f"{s}s"
        self._emit(self._c("-" * WIDTH, DIM))
        state = "completed" if not self.errors else "completed with errors"
        def count(n: int, word: str) -> str:
            return f"{n} {word}" if n == 1 else f"{n} {word}s"

        self._emit(f"{self._c(state, BOLD if not self.errors else RED)} in {span}"
                   f" — {summary} — {count(self.warnings, 'warning')}, "
                   f"{count(self.errors, 'error')}")
        if output:
            self._emit(f"output: {output}")
        self._emit("")

    def close(self) -> None:
        if self.log:
            self.log.close()
