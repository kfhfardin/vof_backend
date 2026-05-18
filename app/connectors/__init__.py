"""Third-party connector package. Phase 1 §F9 ships google_workspace only.

`base.py` holds shared helpers (refresh-if-needed). Per-vendor adapters
(google_workspace.py, future microsoft_365.py, slack.py) implement the
OAuth dance + provider API calls and expose a uniform surface to the
mini-agents that consume them (scheduler, email_drafter, email_delivery).
"""
