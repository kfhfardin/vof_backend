"""Data layer — sessions, models, repositories.

Two logical Postgres databases (HLD §5.8 / LLD §A4):
  - App DB: workspaces, users, calls, decisions, action items, transcripts, intake.
  - Brain DB: schema-per-Workspace (`brain_w_{workspace_id}`) for pages, embeddings, edges.

Only repositories (under app/db/repositories/) are allowed to write raw SQL.
A lint rule enforces this.
"""
