"""Skill loader + SKILL.md frontmatter + LLMSkill round-trip."""

from pathlib import Path

import pytest

from app.skills import FakeLLMClient, SkillContext, SkillRegistry, set_llm_client
from app.skills.loader import load_all_skills, load_skill_from_directory, parse_skill_md


def test_parse_skill_md_minimal() -> None:
    text = """---
name: foo
version: 0.1.0
model: claude-haiku-4-5
---

Body text after frontmatter is ignored by the parser.
"""
    spec = parse_skill_md(text)
    assert spec.name == "foo"
    assert spec.version == "0.1.0"
    assert spec.model == "claude-haiku-4-5"
    assert spec.prompt_filename == "prompt.j2"


def test_parse_skill_md_missing_frontmatter() -> None:
    with pytest.raises(ValueError):
        parse_skill_md("no frontmatter here")


def test_parse_skill_md_missing_required_field() -> None:
    text = """---
name: foo
version: 0.1.0
---

(no model field)
"""
    with pytest.raises(ValueError, match="missing required field"):
        parse_skill_md(text)


def test_load_classifier_skill_from_repo() -> None:
    """The repo ships skills/classifier/ - load it and assert shape."""
    skill_dir = Path(__file__).resolve().parents[2] / "skills" / "classifier"
    skill = load_skill_from_directory(skill_dir)
    assert skill.name == "classifier"
    assert skill.version == "0.1.0"
    assert "claude" in skill.model
    # Input + Output classes registered correctly
    assert "content" in skill.input_schema.model_fields
    assert "scope" in skill.output_schema.model_fields


async def test_llmskill_runs_with_fake_client() -> None:
    """Round-trip: load classifier, swap in a FakeLLMClient, run an input."""
    SkillRegistry.clear()
    load_all_skills()
    skill = SkillRegistry.get("classifier")

    canned = (
        '{"scope":"ORG_WIDE","kind":"account","target_caller_id":null,'
        '"suggested_slug":"accounts/acme-corp","extracted_entities":'
        '[{"type":"company","name":"Acme Corp"}],"confidence":0.92,'
        '"reasoning":"explicit account mention with stage info"}'
    )
    set_llm_client(FakeLLMClient(responses=[canned]))

    inputs = skill.input_schema.model_validate(
        {
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "workspace_name": "Acme Sales",
            "content": "Acme Corp is renewing Q3, stage 3.",
            "source": "form",
        }
    )
    out = await skill.run(inputs, SkillContext())
    assert out.scope == "ORG_WIDE"
    assert out.kind == "account"
    assert out.confidence == 0.92


async def test_llmskill_retries_once_on_invalid_json() -> None:
    SkillRegistry.clear()
    load_all_skills()
    skill = SkillRegistry.get("classifier")

    bad = "this is not json"
    good = (
        '{"scope":"ORG_WIDE","kind":"theme","target_caller_id":null,'
        '"suggested_slug":null,"extracted_entities":[],"confidence":0.8,'
        '"reasoning":"recurring theme across calls"}'
    )
    set_llm_client(FakeLLMClient(responses=[bad, good]))

    inputs = skill.input_schema.model_validate(
        {
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "workspace_name": "Acme Sales",
            "content": "Buyers keep asking about integration timeline.",
            "source": "form",
        }
    )
    out = await skill.run(inputs, SkillContext())
    assert out.kind == "theme"


async def test_llmskill_gives_up_after_one_retry() -> None:
    SkillRegistry.clear()
    load_all_skills()
    skill = SkillRegistry.get("classifier")
    set_llm_client(FakeLLMClient(responses=["bad-json-1", "still-bad-json-2"]))
    inputs = skill.input_schema.model_validate(
        {
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "workspace_name": "Acme Sales",
            "content": "anything",
            "source": "form",
        }
    )
    with pytest.raises(RuntimeError, match="invalid JSON after retry"):
        await skill.run(inputs, SkillContext())
