"""OrchestratorVoiceHandler - plugs the turn loop into the dispatcher.

On import (via app.orchestrator/__init__.py), register_with_dispatcher()
swaps out the Phase 0 _Phase0VoiceTurnHandler for the production handler
so the webhook endpoint streams real LLM replies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from app.deps import get_brain_provider, get_memory_provider
from app.orchestrator.turn_loop import TurnLoop
from app.telephony.dispatcher import VoiceTurnHandler, get_dispatcher
from app.telephony.events import InboundVoiceTurn


class OrchestratorVoiceHandler:
    """Production VoiceTurnHandler. Builds a TurnLoop per request - cheap
    object construction; providers are singletons."""

    def handle(self, event: InboundVoiceTurn, *, call_id: UUID) -> AsyncIterator[bytes]:
        loop = TurnLoop(memory=get_memory_provider(), brain=get_brain_provider())
        return loop.run(event, call_id=call_id)


def register_with_dispatcher() -> None:
    """Replace the dispatcher's default voice handler with the orchestrator.

    Called once at startup from app/lifespan.py.
    """
    handler: VoiceTurnHandler = OrchestratorVoiceHandler()
    get_dispatcher().set_voice_handler(handler)
