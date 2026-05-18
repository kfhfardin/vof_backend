"""OrchestratorTool registry + Phase 0 tools.

Importing this package registers every Phase 0 tool on the singleton
ToolRegistry. Other sections add more tools and call register() the
same way:
  - Phase 1 §D2 mark_followup
"""

from app.orchestrator.tools.base import (
    OrchestratorTool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    encode_tool_marker,
)
from app.orchestrator.tools.end_call import EndCall
from app.orchestrator.tools.end_call import register as _register_end_call
from app.orchestrator.tools.request_correction import (
    RequestCorrection,
)
from app.orchestrator.tools.request_correction import (
    register as _register_request_correction,
)
from app.orchestrator.tools.request_manager_decision import (
    RequestManagerDecision,
)
from app.orchestrator.tools.request_manager_decision import (
    register as _register_request_manager_decision,
)


def register_all() -> None:
    _register_request_manager_decision()
    _register_request_correction()
    _register_end_call()


# Eager registration - importing the package is enough.
register_all()


__all__ = [
    "EndCall",
    "OrchestratorTool",
    "RequestCorrection",
    "RequestManagerDecision",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "encode_tool_marker",
    "register_all",
]
