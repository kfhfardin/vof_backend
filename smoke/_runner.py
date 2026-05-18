"""Aggregating runner: `python -m smoke run --all --mode smoke`.

Each probe runs in its own subprocess for true isolation (a probe that
crashes the interpreter doesn't kill the whole suite). JSON reports are
collected from stdout and a summary is emitted.

See LLD section B9.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

MANIFEST_PATH = Path(__file__).parent / "manifests" / "probes.yaml"


def _load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open() as f:
        return yaml.safe_load(f)


def _select_probes(manifest: dict[str, Any], filter_: str | None, only: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for category, probes in manifest["probes"].items():
        if filter_ and filter_ != category:
            continue
        for p in probes:
            module_short = p["module"].split(".")[-1]
            if only and only != module_short:
                continue
            out.append({**p, "category": category})
    return out


async def _run_probe(module: str, mode: str) -> dict[str, Any]:
    """Spawn `python -m <module> --mode <mode>`, capture stdout/stderr/exit."""
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        "--mode",
        mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    duration_ms = (time.time() - t0) * 1000

    stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_b.decode("utf-8", errors="replace")

    report: dict[str, Any] | None = None
    # The probe emits one JSON line on stdout - parse the last one.
    for line in reversed(stdout_text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                report = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return {
        "module": module,
        "exit_code": proc.returncode,
        "duration_ms": duration_ms,
        "report": report,
        "stderr": stderr_text,
    }


async def _run_all(probes: list[dict[str, Any]], mode: str, parallel: bool) -> list[dict[str, Any]]:
    if parallel:
        results = await asyncio.gather(*[_run_probe(p["module"], mode) for p in probes])
    else:
        results = []
        for p in probes:
            results.append(await _run_probe(p["module"], mode))
    return list(results)


def _summarize(results: list[dict[str, Any]], mode: str) -> int:
    counts = {"pass": 0, "fail": 0, "config_error": 0, "upstream_down": 0}
    worst = 0
    total_ms = 0.0
    for r in results:
        ec = r["exit_code"] or 0
        if ec == 0:
            counts["pass"] += 1
        elif ec == 1:
            counts["fail"] += 1
        elif ec == 2:
            counts["config_error"] += 1
        elif ec == 3:
            counts["upstream_down"] += 1
        worst = max(worst, ec)
        total_ms += r["duration_ms"]

    # Pretty per-probe summary to stderr
    sys.stderr.write("\n=== SMOKE SUITE SUMMARY ===\n")
    for r in results:
        ec = r["exit_code"] or 0
        tag = {0: "PASS", 1: "FAIL", 2: "CONFIG", 3: "UPSTREAM"}.get(ec, f"EXIT{ec}")
        name = r["module"].split(".")[-1]
        sys.stderr.write(f"  [{tag:<8}] {name:<20} {r['duration_ms']:>6.0f}ms\n")
    sys.stderr.write("\n")

    summary_line = (
        f"SMOKE_SUMMARY mode={mode} "
        f"probes={len(results)} pass={counts['pass']} fail={counts['fail']} "
        f"config_error={counts['config_error']} upstream_down={counts['upstream_down']} "
        f"duration_ms={total_ms:.0f}"
    )
    sys.stderr.write(summary_line + "\n")
    sys.stdout.write(json.dumps({"summary": counts, "mode": mode, "duration_ms": total_ms}) + "\n")
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m smoke")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run probes (aggregated)")
    run.add_argument("--mode", choices=["check", "smoke", "repair"], default="check")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Run every probe in the manifest")
    group.add_argument("--filter", choices=["third_party", "infrastructure"], help="Run one category")
    group.add_argument("--only", help="Run a single probe by short name (e.g., agentphone)")
    run.add_argument("--serial", action="store_true", help="Run probes serially (default: parallel)")

    args = parser.parse_args()
    manifest = _load_manifest()
    probes = _select_probes(manifest, args.filter, args.only)
    if not probes:
        sys.stderr.write("no probes selected\n")
        return 2

    results = asyncio.run(_run_all(probes, args.mode, parallel=not args.serial))
    return _summarize(results, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
