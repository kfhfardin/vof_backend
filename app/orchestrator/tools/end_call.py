"""end_call - the LLM signals that the conversation is done.

The orchestrator yields a hangup NDJSON chunk + closes the turn. AgentPhone
takes that as the signal to drop the line.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from app.orchestrator.tools.base import OrchestratorTool, ToolContext, ToolRegistry, ToolResult


class EndCallInput(BaseModel):
    reason: str = Field(default="completed", max_length=64)


class EndCall(OrchestratorTool):
    name: ClassVar[str] = "end_call"
    input_schema: ClassVar[type[BaseModel]] = EndCallInput
    description: ClassVar[str] = (
        "End the call when the Rep clearly indicates they're done. Provide a short reason "
        "(e.g. 'completed', 'rep_hung_up_intent')."
    )

    async def run(self, ctx: ToolContext, inputs: BaseModel) -> ToolResult:
        assert isinstance(inputs, EndCallInput)
        return ToolResult(
            bridge_text="Thanks - I've got what I need. Talk soon.",
            end_turn=True,
            hangup=True,
            followup_context={"hangup_reason": inputs.reason},
        )


def register() -> None:
    try:
        ToolRegistry.register(EndCall())
    except ValueError:
        pass
