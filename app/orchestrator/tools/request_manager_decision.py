"""request_manager_decision - the first real OrchestratorTool.

The LLM emits this when it determines a question needs Manager judgment
(e.g. "Caller asks for 20% discount. Approve a counter at 10%?"). The tool
opens a DecisionRequest, publishes a decision.opened frame to the WS bus,
sends an SMS ping to the Manager's mobile (if configured), and returns a
class-appropriate bridge phrase.

The next turn's prompt (via session.pending_decisions + the conversation
context renderer) lets the LLM weave the eventual answer back into the
conversation when the Manager responds.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.db.app_session import app_session
from app.db.repositories.field_employees_repo import FieldEmployeesRepo
from app.db.repositories.users_repo import UsersRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.deps import get_telephony_provider
from app.logging import get_logger
from app.orchestrator.tools.base import OrchestratorTool, ToolContext, ToolRegistry, ToolResult
from app.services.decisions import DEFAULT_TIMEOUTS_SECONDS, DecisionService

log = get_logger(__name__)

DecisionClass = Literal["inline", "bridged", "async"]


class RequestManagerDecisionInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=1, max_length=6)
    decision_class: DecisionClass = "inline"
    rationale: str | None = Field(default=None, max_length=500)


_BRIDGE_BY_CLASS: dict[DecisionClass, str] = {
    "inline": "Let me check with leadership on that real quick - while I do, what else came up?",
    "bridged": "I'll run that by leadership. Anything else from the meeting we should capture first?",
    "async": "Got it, I'll flag that for leadership to review - moving on.",
}


class RequestManagerDecision(OrchestratorTool):
    name: ClassVar[str] = "request_manager_decision"
    input_schema: ClassVar[type[BaseModel]] = RequestManagerDecisionInput
    description: ClassVar[str] = (
        "Open a decision request that the Manager must answer. Use when a question genuinely "
        "needs the Manager's judgment (pricing concessions, scope changes, customer asks "
        "outside policy). Three classes: 'inline' (Rep is waiting; 45s timeout, bridge to "
        "an adjacent question while we wait); 'bridged' (can defer a few turns; 2min); "
        "'async' (no live wait; surfaces post-call)."
    )

    async def run(self, ctx: ToolContext, inputs: BaseModel) -> ToolResult:
        assert isinstance(inputs, RequestManagerDecisionInput)
        # New session for the tool - the orchestrator's stream is in flight and
        # we don't want to share the streaming session.
        async with app_session() as session:
            workspaces = WorkspacesRepo(session)
            ws = await workspaces.get_by_id(ctx.workspace_id)
            if ws is None:
                log.warning("decision_tool_workspace_missing", workspace_id=str(ctx.workspace_id))
                return ToolResult(bridge_text="(internal: workspace not found)", end_turn=True)

            manager_phone: str | None = None
            if ws.manager_user_id is not None:
                # Phase 0: SMS the Manager's mobile if their FieldEmployee row
                # carries a phone. The Phase 0 signup doesn't auto-create a
                # FieldEmployee for the Manager, so this is a no-op until the
                # Manager is added to the roster.
                fes = FieldEmployeesRepo(session)
                # Try lookup by user_id reverse-link
                user = await UsersRepo(session).get_by_id(ws.manager_user_id)
                if user is not None and user.field_employee_id is not None:
                    fe = await fes.get(user.field_employee_id)
                    if fe is not None:
                        manager_phone = fe.phone

            svc = DecisionService(session, telephony=get_telephony_provider())
            decision = await svc.open(
                call_id=ctx.call_id,
                workspace_id=ctx.workspace_id,
                prompt=inputs.prompt,
                options=inputs.options,
                decision_class=inputs.decision_class,
                context={"rationale": inputs.rationale} if inputs.rationale else None,
                manager_phone=manager_phone,
                agentphone_agent_id=ws.agentphone_agent_id,
            )

        end_turn = inputs.decision_class != "async"
        bridge = _BRIDGE_BY_CLASS[inputs.decision_class]
        followup = {
            "decision_id": str(decision.id),
            "decision_class": inputs.decision_class,
            "timeout_seconds": DEFAULT_TIMEOUTS_SECONDS[inputs.decision_class],
        }
        return ToolResult(
            bridge_text=bridge,
            end_turn=end_turn,
            hangup=False,
            followup_context=followup,
        )


def register() -> None:
    try:
        ToolRegistry.register(RequestManagerDecision())
    except ValueError:
        pass
