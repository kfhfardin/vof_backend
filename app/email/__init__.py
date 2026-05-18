"""Email surface (Phase 1 §F6).

EmailProvider Protocol + two implementations (AgentMail-hosted Workspace
inbox and Gmail-via-personal-OAuth), Jinja templates for outbound
composition, and a small renderer helper.

Mini-agents (`app.miniagents.email_delivery`, `app.miniagents.email_reply_handler`)
consume this package; the AgentMail webhook router lives at
`app.api.webhooks.agentmail`.
"""
