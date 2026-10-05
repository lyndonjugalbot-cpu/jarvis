"""Google sign-in for Calendar and Gmail, and an authorized HTTP client for their APIs.

Setup is in docs/google-setup.md: your own Google Cloud project with a Desktop OAuth client,
published "In production" (Testing-mode refresh tokens expire after 7 days). The client file and
the token live in ~/.jarvis with owner-only permissions, never in the repo.

When a refresh fails for good (access revoked, password changed, six months unused), every Google
tool says so in plain words and the "google.lost" event lets the HUD offer a Reconnect button.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from events import EventBus
from tools.registry import ToolError

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
LOGIN_TIMEOUT_S = 300
SETUP_DOC = "docs/google-setup.md"


class GoogleNotConnected(ToolError):
    """Google isn't set up, or access was lost; the message says what to do."""


class GoogleAuth:
    def __init__(self, client_file: Path, token_file: Path, events: EventBus | None = None) -> None:
        self.client_file = client_file
        self.token_file = token_file
        self._events = events
        self._creds: Credentials | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.client_file.exists()

    @property
    def connected(self) -> bool:
        return self._load() is not None

    def _load(self) -> Credentials | None:
        if self._creds is None and self.token_file.exists():
            try:
                info = json.loads(self.token_file.read_text())
                self._creds = Credentials.from_authorized_user_info(info, SCOPES)
            except (ValueError, KeyError):
                log.warning("unreadable Google token file %s", self.token_file)
        return self._creds

    def _save(self, creds: Credentials) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(creds.to_json())
        self._creds = creds

    def _not_connected(self) -> GoogleNotConnected:
        if not self.configured:
            return GoogleNotConnected(
                f"Google isn't set up yet. The steps are in {SETUP_DOC}; after that, "
                "run scripts/start.sh google or say 'connect Google'."
            )
        return GoogleNotConnected(
            "I'm not connected to Google. Say 'connect Google', or use Reconnect on the HUD."
        )

    async def _lost(self, reason: str) -> GoogleNotConnected:
        log.warning("lost Google access: %s", reason)
        self._creds = None
        self.token_file.unlink(missing_ok=True)
        if self._events:
            await self._events.publish("google.lost", reason=reason)
        return GoogleNotConnected(
            "I've lost access to Google. Say 'connect Google', or use Reconnect on the HUD."
        )

    async def token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            creds = self._load()
            if creds is None:
                raise self._not_connected()
            if force_refresh or not creds.valid:
                try:
                    await asyncio.to_thread(creds.refresh, Request())
                except RefreshError as e:
                    raise await self._lost(str(e)) from e
                self._save(creds)
            return creds.token

    def login(self) -> None:
        """Run the browser sign-in (blocking; up to 5 minutes) and save the token."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.configured:
            raise self._not_connected()
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_file), SCOPES)
        creds = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            timeout_seconds=LOGIN_TIMEOUT_S,
            success_message="JARVIS is connected to Google. You can close this tab.",
            access_type="offline",
            prompt="consent",
        )
        self._save(creds)


class GoogleApi:
    """Async calls to Google REST APIs with the user's token; one retry after a 401."""

    def __init__(self, auth: Any, http: httpx.AsyncClient | None = None) -> None:
        self._auth = auth
        self._http = http or httpx.AsyncClient(timeout=20)

    async def call(self, method: str, url: str, **kwargs: Any) -> dict:
        extra_headers = kwargs.pop("headers", {})
        for attempt in (1, 2):
            token = await self._auth.token(force_refresh=attempt == 2)
            headers = {"Authorization": f"Bearer {token}", **extra_headers}
            try:
                response = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as e:
                raise ToolError(f"Couldn't reach Google: {e}") from e
            if response.status_code == 401 and attempt == 1:
                continue
            if response.status_code >= 400:
                raise ToolError(_google_error(response))
            return response.json() if response.content else {}
        raise ToolError("Google rejected the request twice.")

    async def close(self) -> None:
        await self._http.aclose()


def _google_error(response: httpx.Response) -> str:
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text[:200]
    if response.status_code == 403 and "has not been used" in message:
        return f"That Google API isn't enabled in your Cloud project yet ({SETUP_DOC}, step 2)."
    return f"Google said {response.status_code}: {message}"
