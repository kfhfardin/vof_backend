#!/usr/bin/env python
"""Eval harness for the classifier skill.

Runs `golden_set.jsonl` through the registered classifier; computes precision
on (scope, kind). Exits 0 if metric >= the bar parsed from SKILL.md, else 1.
CI uses the exit code to gate merges (LLD §A10, §C9).

Usage:
    uv run python skills/classifier/evals/run.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

# Repo root on path so `import app...` works when this is run as a script.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.skills import SkillContext, SkillRegistry, load_all_skills  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
GOLDEN_PATH = SKILL_DIR / "evals" / "golden_set.jsonl"

_BAR_RE = re.compile(r"quality_bar:\s*precision_min:(?P<bar>[0-9.]+)")


def _parse_bar() -> float:
    text = (SKILL_DIR / "SKILL.md").read_text()
    m = _BAR_RE.search(text)
    if not m:
        # Fall back to YAML-frontmatter parse
        from app.skills.loader import parse_skill_md

        spec = parse_skill_md(text)
        if spec.quality_bar and spec.quality_bar.startswith("precision_min:"):
            return float(spec.quality_bar.split(":", 1)[1])
        return 0.0
    return float(m.group("bar"))


async def _main() -> int:
    load_all_skills()
    skill = SkillRegistry.get("classifier")
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text().splitlines() if line.strip()]
    correct = 0
    total = 0
    failures: list[str] = []

    for i, case in enumerate(cases):
        inputs = skill.input_schema.model_validate(case["input"])
        try:
            out = await skill.run(inputs, SkillContext(workspace_id=inputs.workspace_id))
        except Exception as e:
            failures.append(f"#{i} skill_raised: {e}")
            total += 1
            continue
        total += 1
        expected = case["expected"]
        # Match on (scope, kind) since that's the load-bearing decision
        if out.scope == expected["scope"] and out.kind == expected["kind"]:
            correct += 1
        else:
            failures.append(
                f"#{i} got=({out.scope},{out.kind}) expected=({expected['scope']},{expected['kind']})"
            )

    precision = correct / total if total else 0.0
    bar = _parse_bar()
    report = {
        "skill": "classifier",
        "total": total,
        "correct": correct,
        "precision": precision,
        "bar": bar,
        "passed": precision >= bar,
        "failures": failures[:10],
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
