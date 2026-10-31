"""The agent's only connection to the app: the workout-agent Edge Function.

Read the history snapshot, save a coach report, and ask whose data a key or a sign-in opens. The key is the agent key
you set in Supabase (never the service key). Standard library only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class AppError(RuntimeError):
    pass


class AppClient:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None, timeout: float = 60, bearer: Optional[str] = None):
        """`bearer`: act as a signed-in person instead of the coach (only for `whoami`, to check who started a run)."""
        self.url = (url or os.environ.get("WORKOUT_AGENT_URL", "")).rstrip("/")
        self.key = key or os.environ.get("WORKOUT_AGENT_KEY", "")
        self.bearer = bearer
        self.timeout = timeout
        if not self.url or not (self.key or self.bearer):
            raise AppError("Set WORKOUT_AGENT_URL and WORKOUT_AGENT_KEY (see .env.example).")

    def _request(self, method: str, path: str, body: Optional[dict] = None, query: Optional[dict] = None) -> tuple[int, bytes]:
        url = f"{self.url}/{path}" + (f"?{urllib.parse.urlencode({k: v for k, v in (query or {}).items() if v is not None})}" if query else "")
        data = json.dumps(body).encode() if body is not None else None
        auth = {"Authorization": f"Bearer {self.bearer}"} if self.bearer else {"x-agent-key": self.key}
        req = urllib.request.Request(url, data=data, method=method, headers={**auth, "Content-Type": "application/json", "User-Agent": "workout-coach/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - fixed https URL from config
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise AppError(f"{method} {path}: HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise AppError(f"{method} {path}: {e.reason}") from e

    def history(self, as_of: Optional[str] = None, months: int = 6) -> dict:
        _, body = self._request("GET", "history", query={"as_of": as_of, "months": months})
        return json.loads(body)

    def history_markdown(self, as_of: Optional[str] = None, months: int = 6) -> str:
        _, body = self._request("GET", "history", query={"as_of": as_of, "months": months, "format": "md"})
        return body.decode()

    def whoami(self) -> str:
        """The user id whose data this client opens."""
        _, body = self._request("GET", "whoami")
        return str(json.loads(body)["user_id"])

    def save_report(self, payload: dict) -> dict:
        _, body = self._request("POST", "reports", body=payload)
        return json.loads(body)
