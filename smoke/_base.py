"""Probe base class — every smoke script subclasses Probe.

Handles: config loading, timing, output formatting (JSON+pretty),
exit codes, secrets redaction.

See LLD section B1 for the full spec.
"""

from __future__ import annotations

import json
import os
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any, ClassVar


class ExitCode(IntEnum):
    PASS = 0
    FAIL = 1
    CONFIG = 2
    UPSTREAM = 3


class UpstreamUnavailable(Exception):
    """Raised when the third-party service is itself down (5xx, timeout)."""


@dataclass
class CheckResult:
    name: str
    passed: bool
    latency_ms: float
    detail: str = ""
    fix_hint: str = ""


@dataclass
class ProbeReport:
    probe: str
    mode: str
    overall: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    started_at: str = ""
    duration_ms: float = 0.0


_ANSI = {
    "GREEN": "\033[32m",
    "RED": "\033[31m",
    "YELLOW": "\033[33m",
    "BLUE": "\033[34m",
    "DIM": "\033[2m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m",
}


def _color(text: str, color: str) -> str:
    if not sys.stderr.isatty():
        return text
    return f"{_ANSI[color]}{text}{_ANSI['RESET']}"


def _redact(text: str, secret_values: list[str]) -> str:
    out = text
    for v in secret_values:
        if v and len(v) > 4:
            out = out.replace(v, f"{v[:2]}***{v[-2:]}")
    return out


class Probe(ABC):
    name: ClassVar[str] = "unnamed"
    required_env: ClassVar[list[str]] = []

    def __init__(self, mode: str = "check") -> None:
        if mode not in ("check", "smoke", "repair"):
            raise ValueError(f"mode must be check|smoke|repair, got {mode!r}")
        self.mode = mode
        self.report = ProbeReport(
            probe=self.name,
            mode=mode,
            started_at=datetime.now(UTC).isoformat(),
        )

    # -- Public API --

    def run(self) -> ExitCode:
        # 1. Verify required env vars
        missing = [v for v in self.required_env if not os.environ.get(v)]
        if missing:
            self._emit_config_error(missing)
            return ExitCode.CONFIG

        # 2. Run probe-specific checks
        t0 = time.time()
        try:
            self.checks_for_mode()
        except UpstreamUnavailable as e:
            self.report.duration_ms = (time.time() - t0) * 1000
            self._emit_upstream(str(e))
            return ExitCode.UPSTREAM
        except Exception as e:
            # Unexpected error - treat as functional failure with full traceback in repair mode
            self.report.duration_ms = (time.time() - t0) * 1000
            self.report.checks.append(
                CheckResult(
                    name="_unexpected_error",
                    passed=False,
                    latency_ms=0,
                    detail=f"{type(e).__name__}: {e}",
                )
            )
        finally:
            self.report.duration_ms = (time.time() - t0) * 1000

        # 3. Emit report
        all_passed = bool(self.report.checks) and all(c.passed for c in self.report.checks)
        self.report.overall = "pass" if all_passed else "fail"
        self._emit_report()
        return ExitCode.PASS if all_passed else ExitCode.FAIL

    @abstractmethod
    def checks_for_mode(self) -> None:
        """Override in subclass. Use self.check() to run individual checks."""

    # -- Helpers for subclasses --

    def check(
        self,
        name: str,
        fn: Callable[[], str | None],
        fix_hint: str = "",
    ) -> bool:
        """Run one named check, time it, capture pass/fail."""
        t0 = time.time()
        try:
            detail = fn() or ""
            self.report.checks.append(
                CheckResult(name=name, passed=True, latency_ms=(time.time() - t0) * 1000, detail=detail)
            )
            return True
        except UpstreamUnavailable:
            # Re-raise so run() can catch it and exit with UPSTREAM code
            raise
        except Exception as e:
            self.report.checks.append(
                CheckResult(
                    name=name,
                    passed=False,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"{type(e).__name__}: {e}",
                    fix_hint=fix_hint,
                )
            )
            # In repair mode, continue running other checks for max diagnostic info
            if self.mode != "repair":
                # Stop running further checks in this probe (fail-fast within probe)
                # but DON'T raise - the run() loop should still emit the report
                return False
            return False

    def check_with_return(
        self,
        name: str,
        fn: Callable[[], Any],
        fix_hint: str = "",
    ) -> Any:
        """Like check(), but returns the fn's value so chained checks can use it."""
        t0 = time.time()
        try:
            value = fn()
            self.report.checks.append(
                CheckResult(
                    name=name,
                    passed=True,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=str(value) if value else "",
                )
            )
            return value
        except UpstreamUnavailable:
            raise
        except Exception as e:
            self.report.checks.append(
                CheckResult(
                    name=name,
                    passed=False,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"{type(e).__name__}: {e}",
                    fix_hint=fix_hint,
                )
            )
            return None

    # -- Output --

    def _secret_values(self) -> list[str]:
        return [
            os.environ[k]
            for k in self.required_env
            if k in os.environ and k.endswith(("_KEY", "_SECRET", "_PASSWORD", "_TOKEN"))
        ]

    def _emit_report(self) -> None:
        secrets = self._secret_values()
        # JSON to stdout (machine-readable)
        report_dict = asdict(self.report)
        # Redact in detail strings
        for c in report_dict["checks"]:
            c["detail"] = _redact(c["detail"], secrets)
        sys.stdout.write(json.dumps(report_dict) + "\n")
        sys.stdout.flush()

        # Pretty to stderr (human-readable)
        header = f"=== probe: {self.report.probe} mode={self.report.mode} ==="
        sys.stderr.write(_color(header, "BOLD") + "\n")
        for c in self.report.checks:
            status_tag = _color("[PASS]", "GREEN") if c.passed else _color("[FAIL]", "RED")
            latency = f"{c.latency_ms:>6.0f}ms"
            detail = _redact(c.detail, secrets) if c.detail else ""
            line = f"  {status_tag} {c.name:<35} {latency}  {detail}"
            sys.stderr.write(line + "\n")
            if not c.passed and c.fix_hint:
                sys.stderr.write(_color(f"         fix: {c.fix_hint}", "YELLOW") + "\n")
        total_tag = _color("PASS", "GREEN") if self.report.overall == "pass" else _color("FAIL", "RED")
        sys.stderr.write(f"  -> {total_tag} in {self.report.duration_ms:.0f}ms\n\n")
        sys.stderr.flush()

    def _emit_config_error(self, missing: list[str]) -> None:
        payload = {
            "probe": self.name,
            "mode": self.mode,
            "overall": "config_error",
            "missing_env": missing,
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
        sys.stderr.write(_color(f"=== probe: {self.name} mode={self.mode} ===\n", "BOLD"))
        sys.stderr.write(_color("  [CONFIG] required env vars missing:\n", "YELLOW"))
        for v in missing:
            sys.stderr.write(f"    - {v}\n")
        sys.stderr.write("\n")
        sys.stderr.flush()

    def _emit_upstream(self, message: str) -> None:
        payload = {
            "probe": self.name,
            "mode": self.mode,
            "overall": "upstream_down",
            "message": message,
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
        sys.stderr.write(_color(f"=== probe: {self.name} mode={self.mode} ===\n", "BOLD"))
        sys.stderr.write(_color(f"  [UPSTREAM] {message}\n", "BLUE"))
        sys.stderr.flush()


def main_for(probe_class: type[Probe]) -> int:
    """Boilerplate for probe modules' `if __name__ == '__main__'` block."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["check", "smoke", "repair"], default="check")
    args = parser.parse_args()
    return int(probe_class(mode=args.mode).run())
