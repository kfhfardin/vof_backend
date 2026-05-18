"""Orchestrator - per-call hot-path engine.

Modules:
  session.py            CallSession + Redis-backed RedisSessionStore
  retrieval.py          Parallel CallerMemory + Brain hybrid_search
  prompts.py            Renders the orchestrator skill's templates
  streaming.py          NDJSON streamer + bridge-chunk pattern
  turn_loop.py          The per-turn voice driver
  voice_handler.py      Plugs the voice loop into the webhook dispatcher
  sms_orchestrator.py   SMS counterpart — single-shot reply via send_sms

Side effect of importing this package via app/lifespan.py: registers the
production voice + SMS handlers with the dispatcher. The Phase 0 stub
handlers are replaced at startup.
"""

from app.orchestrator.sms_orchestrator import (
    SMSOrchestratorHandler,
    register_sms_with_dispatcher,
)
from app.orchestrator.voice_handler import OrchestratorVoiceHandler, register_with_dispatcher

__all__ = [
    "OrchestratorVoiceHandler",
    "SMSOrchestratorHandler",
    "register_sms_with_dispatcher",
    "register_with_dispatcher",
]
