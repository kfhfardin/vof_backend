"""Skill loader - walks the skills/ directory, parses SKILL.md frontmatter,
imports the schema module, and registers an LLMSkill per directory.

Layout per LLD §A10:
    skills/<name>/
        SKILL.md           # YAML frontmatter: name, version, model, ...
        prompt.j2          # Jinja2 template
        schema.py          # module with Input + Output Pydantic classes
        fixtures/          # representative inputs for offline checks
        evals/run.py       # eval harness (CI gate)
        CHANGELOG.md
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.logging import get_logger
from app.skills.base import LLMSkill, SkillRegistry

log = get_logger(__name__)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class _SkillSpec:
    name: str
    version: str
    model: str
    prompt_filename: str
    quality_bar: str | None = None


def parse_skill_md(text: str) -> _SkillSpec:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("SKILL.md missing YAML frontmatter (--- ... ---)")
    frontmatter: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    try:
        return _SkillSpec(
            name=frontmatter["name"],
            version=str(frontmatter["version"]),
            model=frontmatter["model"],
            prompt_filename=frontmatter.get("prompt", "prompt.j2"),
            quality_bar=frontmatter.get("quality_bar"),
        )
    except KeyError as e:
        raise ValueError(f"SKILL.md frontmatter missing required field: {e}") from e


def _import_schema_module(skill_dir: Path) -> tuple[type[BaseModel], type[BaseModel]]:
    schema_path = skill_dir / "schema.py"
    if not schema_path.exists():
        raise FileNotFoundError(f"{schema_path} not found")
    mod_name = f"_skill_schema_{skill_dir.name}"
    spec = importlib.util.spec_from_file_location(mod_name, schema_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {schema_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    # Convention: classes named `Input` and `Output`.
    try:
        input_cls: type[BaseModel] = module.Input
        output_cls: type[BaseModel] = module.Output
    except AttributeError as e:
        raise AttributeError(f"{schema_path} must define `Input` and `Output` Pydantic classes") from e
    return input_cls, output_cls


def load_skill_from_directory(skill_dir: Path) -> LLMSkill:
    md_path = skill_dir / "SKILL.md"
    if not md_path.exists():
        raise FileNotFoundError(f"{md_path} not found")
    spec = parse_skill_md(md_path.read_text())
    input_cls, output_cls = _import_schema_module(skill_dir)
    prompt_path = skill_dir / spec.prompt_filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"{prompt_path} not found")
    return LLMSkill(
        name=spec.name,
        version=spec.version,
        model=spec.model,
        input_schema=input_cls,
        output_schema=output_cls,
        prompt_path=prompt_path,
        quality_bar=spec.quality_bar,
    )


def load_all_skills(root: Path | None = None) -> list[str]:
    """Discover every skills/<name>/ and register on SkillRegistry.

    Returns the list of registered skill names. Idempotent across calls
    (re-registration raises - so this is a once-at-startup operation).
    """
    root = root or SKILLS_ROOT
    if not root.exists():
        log.warning("skills_root_missing", path=str(root))
        return []
    registered: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if not (child / "SKILL.md").exists():
            continue
        try:
            skill = load_skill_from_directory(child)
            try:
                SkillRegistry.register(skill)
            except ValueError:
                # already registered (re-import); skip
                pass
            registered.append(skill.name)
        except Exception:
            log.exception("skill_load_failed", skill_dir=str(child))
    return registered
