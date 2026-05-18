"""Phase 0 mini-agents.

- summarizer:          skill wrapper; runs the summarizer LLMSkill
- brain_updater:       consumes summary + upserts brain pages via §C8 provider
- caller_memory_writer: pushes a digest to Supermemory (stub provider until
                       the real adapter lands)
"""

from app.miniagents.brain_updater import BrainUpdater, run_brain_updater
from app.miniagents.caller_memory_writer import write_call_to_caller_memory
from app.miniagents.dashboard_rollup import (
    DashboardRollup,
    DashboardRollupInput,
    DashboardRollupResult,
    run_dashboard_rollup,
)
from app.miniagents.email_drafter import EmailDrafterContext, EmailDrafterMiniAgent
from app.miniagents.scheduler import SchedulerContext, SchedulerMiniAgent
from app.miniagents.summarizer_agent import Summarizer, run_summarizer

__all__ = [
    "BrainUpdater",
    "DashboardRollup",
    "DashboardRollupInput",
    "DashboardRollupResult",
    "EmailDrafterContext",
    "EmailDrafterMiniAgent",
    "SchedulerContext",
    "SchedulerMiniAgent",
    "Summarizer",
    "run_brain_updater",
    "run_dashboard_rollup",
    "run_summarizer",
    "write_call_to_caller_memory",
]
