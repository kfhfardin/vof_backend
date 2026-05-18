"""Seed a Workspace (+ Manager + optional FieldEmployee) for live testing.

Two modes:

  1. **Workspace-only** (omit --caller-number) — production-style seeding
     for an AP number where many different callers will dial in. The
     dispatcher auto-creates an unprofiled FieldEmployee for each new
     caller phone on first inbound voice turn, so no caller needs to be
     pre-registered.

  2. **Workspace + one known caller** (pass --caller-number) — handy for
     repeatable local tests where the same mobile dials each time. Creates
     a profiled FieldEmployee bound to that phone.

Idempotent: re-running with the same numbers updates the existing rows.

Usage:
    set -a && source .env.local && set +a

    # Production-style: only the workspace + manager
    uv run python -m scripts.seed_test_workspace \\
        --ap-number +14783304859

    # Test-style: also pre-seed a known caller
    uv run python -m scripts.seed_test_workspace \\
        --ap-number +17578314612 \\
        --caller-number +17653506634 \\
        --ap-agent-id cmpa4o1e005ecjz00n7khhuzm
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from sqlalchemy import select

from app.db.app_session import app_session
from app.db.models import FieldEmployee, ManagerWorkspace, Organization, User
from app.security.hashing import hash_password


async def main(
    ap_number: str,
    *,
    caller_number: str | None,
    ap_agent_id: str | None,
    org_name: str,
    workspace_name: str,
    manager_email: str,
) -> int:
    async with app_session() as session:
        # 1. Organization.
        org = (
            await session.execute(select(Organization).where(Organization.name == org_name))
        ).scalar_one_or_none()
        if org is None:
            org = Organization(id=uuid4(), name=org_name)
            session.add(org)
            await session.flush()
            print(f"created  Organization      id={org.id}  name={org_name!r}")
        else:
            print(f"reusing  Organization      id={org.id}  name={org_name!r}")

        # 2. User (manager).
        user = (
            await session.execute(select(User).where(User.email == manager_email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid4(),
                organization_id=org.id,
                email=manager_email,
                password_hash=hash_password("smoke-password-not-secret"),
                role="manager",
            )
            session.add(user)
            await session.flush()
            print(f"created  User              id={user.id}  email={manager_email}")
        else:
            print(f"reusing  User              id={user.id}  email={manager_email}")

        # 3. ManagerWorkspace keyed on primary_number = the AP number.
        ws = (
            await session.execute(
                select(ManagerWorkspace).where(ManagerWorkspace.primary_number == ap_number)
            )
        ).scalar_one_or_none()
        if ws is None:
            ws = ManagerWorkspace(
                id=uuid4(),
                organization_id=org.id,
                manager_user_id=user.id,
                name=workspace_name,
                primary_number=ap_number,
                agentphone_agent_id=ap_agent_id,
                provisioning_state="ready",
            )
            session.add(ws)
            await session.flush()
            print(f"created  ManagerWorkspace  id={ws.id}  primary_number={ap_number}")
        else:
            ws.organization_id = org.id
            ws.manager_user_id = user.id
            ws.name = workspace_name
            if ap_agent_id is not None:
                ws.agentphone_agent_id = ap_agent_id
            ws.provisioning_state = "ready"
            print(f"updated  ManagerWorkspace  id={ws.id}  primary_number={ap_number}")

        # Backlink user → workspace so /me etc. resolve scope.
        if user.workspace_id != ws.id:
            user.workspace_id = ws.id

        # 4. FieldEmployee — only if a caller number was provided. Otherwise
        #    the dispatcher auto-creates unprofiled FEs for each new caller
        #    on first inbound voice turn (see app/telephony/dispatcher.py).
        if caller_number:
            fe = (
                await session.execute(
                    select(FieldEmployee).where(
                        FieldEmployee.workspace_id == ws.id,
                        FieldEmployee.phone == caller_number,
                    )
                )
            ).scalar_one_or_none()
            if fe is None:
                fe = FieldEmployee(
                    id=uuid4(),
                    workspace_id=ws.id,
                    organization_id=org.id,
                    name="Smoke Test Rep",
                    phone=caller_number,
                    role="AE",
                    profiled=True,
                )
                session.add(fe)
                await session.flush()
                print(f"created  FieldEmployee     id={fe.id}  phone={caller_number}")
            else:
                print(f"reusing  FieldEmployee     id={fe.id}  phone={caller_number}")

        await session.commit()

    print()
    print("Seed complete.")
    print(f"  Workspace primary_number: {ap_number}")
    if caller_number:
        print(f"  Pre-seeded caller:        {caller_number}")
    else:
        print("  Pre-seeded caller:        (none — any caller works; FEs auto-created on first call)")
    if ap_agent_id is None:
        print()
        print("  Note: agentphone_agent_id is unset on this workspace.")
        print("  Inbound calls + SMS will route correctly, but outbound SMS")
        print("  (decision pings via DecisionService) won't work until this")
        print("  workspace has an AP agent id. Re-run with --ap-agent-id to wire it.")
    return 0


def _cli() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--ap-number", required=True, help="AP-provisioned phone (E.164)")
    p.add_argument(
        "--caller-number",
        default=None,
        help="Optional. Pre-seed one known caller as a profiled FieldEmployee. "
        "Omit to let the dispatcher auto-create FEs for any caller phone.",
    )
    p.add_argument("--ap-agent-id", default=None, help="AP agent id (cmpa...) for outbound SMS")
    p.add_argument(
        "--org-name", default="VotF Production", help="Organization name (default: VotF Production)"
    )
    p.add_argument(
        "--workspace-name", default="VotF Workspace", help="Workspace display name"
    )
    p.add_argument(
        "--manager-email",
        default="manager@votf.local",
        help="Manager user email (used as login)",
    )
    args = p.parse_args()
    return asyncio.run(
        main(
            ap_number=args.ap_number,
            caller_number=args.caller_number,
            ap_agent_id=args.ap_agent_id,
            org_name=args.org_name,
            workspace_name=args.workspace_name,
            manager_email=args.manager_email,
        )
    )


if __name__ == "__main__":
    raise SystemExit(_cli())
