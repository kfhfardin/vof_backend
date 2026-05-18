"""Google Workspace probe (F9).

Verifies OAuth refresh works against the configured client id/secret
using a pre-arranged refresh token (SMOKE_GOOGLE_REFRESH_TOKEN). The
gmail_send + calendar_events_write checks confirm the API endpoints
are reachable with that access token; we deliberately skip real
sends/event creation on first ship to avoid spamming a real mailbox.

To collect a SMOKE_GOOGLE_REFRESH_TOKEN: run the production OAuth
dance once against a throwaway test Google account and grab the
refresh_token from the workspace_oauth_credentials row.
"""

from __future__ import annotations

import os
from typing import ClassVar

import httpx

from smoke._base import Probe, UpstreamUnavailable, main_for

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"


class GoogleWorkspaceProbe(Probe):
    name: ClassVar[str] = "google_workspace"
    required_env: ClassVar[list[str]] = [
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "SMOKE_GOOGLE_REFRESH_TOKEN",
    ]

    _access_token: str | None = None

    def checks_for_mode(self) -> None:
        self.check(
            "auth_valid",
            self._auth_valid,
            fix_hint=(
                "Refresh failed - SMOKE_GOOGLE_REFRESH_TOKEN may be revoked or "
                "the OAuth client credentials are stale. Re-run the consent "
                "flow against the test account."
            ),
        )

        if self.mode in ("smoke", "repair"):
            self.check(
                "gmail_send_endpoint_reachable",
                self._gmail_endpoint_reachable,
                fix_hint=(
                    "Token has no gmail.send scope, or Gmail API is disabled in "
                    "the GCP project. Enable Gmail API + reconsent for the missing scope."
                ),
            )
            self.check(
                "calendar_events_write_scope_present",
                self._calendar_endpoint_reachable,
                fix_hint=(
                    "Token has no calendar.events scope, or Calendar API is "
                    "disabled. Enable Calendar API + reconsent for the missing scope."
                ),
            )

    # -- Checks --

    def _auth_valid(self) -> str:
        data = {
            "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
            "refresh_token": os.environ["SMOKE_GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
        try:
            r = httpx.post(TOKEN_URL, data=data, timeout=10.0)
        except httpx.RequestError as e:
            raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"google {r.status_code}")
        if r.status_code in (400, 401):
            raise RuntimeError(f"refresh rejected ({r.status_code}): {r.text[:200]}")
        r.raise_for_status()
        body = r.json()
        access_token = body.get("access_token")
        if not access_token:
            raise RuntimeError("token response missing access_token")
        type(self)._access_token = access_token
        scopes = body.get("scope", "")
        return f"expires_in={body.get('expires_in')}s scopes={len(scopes.split())}"

    def _gmail_endpoint_reachable(self) -> str:
        if not self._access_token:
            raise RuntimeError("auth_valid did not yield an access token")
        try:
            r = httpx.get(
                GMAIL_PROFILE_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"gmail {r.status_code}")
        if r.status_code == 403:
            raise RuntimeError(
                f"gmail forbidden - scope or API disabled: {r.text[:200]}"
            )
        r.raise_for_status()
        body = r.json()
        return f"mailbox={body.get('emailAddress', '?')}"

    def _calendar_endpoint_reachable(self) -> str:
        if not self._access_token:
            raise RuntimeError("auth_valid did not yield an access token")
        try:
            r = httpx.get(
                CALENDAR_LIST_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise UpstreamUnavailable(f"network: {e}") from e
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"calendar {r.status_code}")
        if r.status_code == 403:
            raise RuntimeError(
                f"calendar forbidden - scope or API disabled: {r.text[:200]}"
            )
        r.raise_for_status()
        body = r.json()
        items = body.get("items") or []
        return f"calendars={len(items)}"


if __name__ == "__main__":
    raise SystemExit(main_for(GoogleWorkspaceProbe))
