#!/usr/bin/env python
"""Summarizer eval harness.

Measures entity-recall on the golden set: of the entities marked
`expected_entities` for each input, how many appear in the LLM's
`extracted_entities` output (case-insensitive substring match).

Exit 0 if mean recall >= the bar parsed from SKILL.md, else exit 1.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.skills import SkillContext, SkillRegistry, load_all_skills  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
GOLDEN_PATH = SKILL_DIR / "evals" / "golden_set.jsonl"

_BAR_RE = re.compile(r"quality_bar:\s*entity_recall_min:(?P<bar>[0-9.]+)")


def _parse_bar() -> float:
    text = (SKILL_DIR / "SKILL.md").read_text()
    m = _BAR_RE.search(text)
    return float(m.group("bar")) if m else 0.0


async def _main() -> int:
    load_all_skills()
    skill = SkillRegistry.get("summarizer")
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text().splitlines() if line.strip()]
    recalls: list[float] = []
    failures: list[str] = []

    for i, case in enumerate(cases):
        try:
            inputs = skill.input_schema.model_validate(case["input"])
            out = await skill.run(inputs, SkillContext())
        except Exception as e:
            failures.append(f"#{i} skill_raised: {e}")
            recalls.append(0.0)
            continue
        expected = {e.lower() for e in case.get("expected_entities", [])}
        got = {ent.name.lower() for ent in out.extracted_entities}
        # Substring-tolerant match
        hit = 0
        for e in expected:
            if any(e in g or g in e for g in got):
                hit += 1
        recall = hit / len(expected) if expected else 1.0
        recalls.append(recall)
        if recall < 1.0:
            failures.append(f"#{i} recall={recall:.2f} got={got} expected={expected}")

    mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
    bar = _parse_bar()
    report = {
        "skill": "summarizer",
        "cases": len(cases),
        "mean_entity_recall": mean_recall,
        "bar": bar,
        "passed": mean_recall >= bar,
        "failures": failures[:10],
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
