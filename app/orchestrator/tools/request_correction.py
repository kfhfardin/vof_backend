"""request_correction - mid-call Rep-initiated correction.

The Rep says something like "Hey, I want to correct something about Acme -
they actually use Salesforce, not HubSpot." The orchestrator emits this
tool, the CorrectionService applies a `replace_compiled_truth` correction,
and the page is now manager_authoritative for any future auto-extraction.

Targeted by slug. The orchestrator's prompt asks the LLM to verify the
slug from the brain hits before emitting this; the tool itself surfaces
the underlying NotFound back to the caller's reply if the slug is wrong.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.db.app_session import app_session
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import get_brain_provider
from app.errors import NotFound, Validation
from app.logging import get_logger
from app.orchestrator.tools.base import OrchestratorTool, ToolContext, ToolRegistry, ToolResult
from app.services.corrections import CorrectionKind, CorrectionService

log = get_logger(__name__)

CorrectionKindLiteral = Literal[
    "replace_compiled_truth",
    "append_timeline_entry",
]


class RequestCorrectionInput(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    kind: CorrectionKindLiteral = "replace_compiled_truth"
    # For replace_compiled_truth this is the new compiled_truth; for
    # append_timeline_entry it's the note text. Either way the LLM passes
    # the exact text it wants on the page.
    text: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=200)
    rationale: str | None = Field(default=None, max_length=400)


class RequestCorrection(OrchestratorTool):
    name: ClassVar[str] = "request_correction"
    input_schema: ClassVar[type[BaseModel]] = RequestCorrectionInput
    description: ClassVar[str] = (
        "Apply a Manager-authoritative correction to a Workspace Brain page mid-call. "
        "Use when the Rep explicitly corrects something the system has wrong about an "
        "account, person, product, or theme. `slug` must match a known brain page (see "
        "brain hits in the prompt). `kind` is usually 'replace_compiled_truth' for a "
        "fact correction or 'append_timeline_entry' for a forward-looking note. The "
        "page becomes manager_authoritative - the auto-extractor will not overwrite it."
    )

    async def run(self, ctx: ToolContext, inputs: BaseModel) -> ToolResult:
        assert isinstance(inputs, RequestCorrectionInput)
        async with app_session() as session:
            ws = await WorkspacesRepo(session).get_by_id(ctx.workspace_id)
            if ws is None:
                return ToolResult(
                    bridge_text="Couldn't find your workspace - flagging that for later.",
                    end_turn=True,
                )
            manager_user_id = ws.manager_user_id
            if manager_user_id is None:
                return ToolResult(
                    bridge_text="Couldn't apply that correction - no Manager on file. Will flag.",
                    end_turn=True,
                )

            payload: dict[str, str] = {"text": inputs.text}
            if inputs.kind == "replace_compiled_truth":
                payload = {"compiled_truth": inputs.text}
                if inputs.title:
                    payload["title"] = inputs.title

            svc = CorrectionService(session, brain=get_brain_provider())
            try:
                await svc.apply(
                    workspace_id=ctx.workspace_id,
                    target_slug=inputs.slug,
                    kind=CorrectionKind(inputs.kind),
                    payload=payload,
                    rationale=inputs.rationale,
                    corrected_by_user_id=manager_user_id,
                )
            except NotFound:
                return ToolResult(
                    bridge_text=(
                        f"I don't have a page called '{inputs.slug}' yet - I'll "
                        "make a note so we can sort it out post-call."
                    ),
                )
            except Validation as e:
                log.warning(
                    "request_correction_validation",
                    detail=str(e),
                    slug=inputs.slug,
                )
                return ToolResult(
                    bridge_text=(
                        "Couldn't apply that correction the way you described - I'll log it for review."
                    ),
                )
        return ToolResult(
            bridge_text="Got it, I've updated that. Anything else?",
            followup_context={"corrected_slug": inputs.slug, "kind": inputs.kind},
        )


def register() -> None:
    try:
        ToolRegistry.register(RequestCorrection())
    except ValueError:
        pass
