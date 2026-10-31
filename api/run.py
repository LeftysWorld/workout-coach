"""The workout coach on Vercel: /api/run runs one weekly review and saves the report to the app.

Two ways to start a run, nothing else:
- Vercel's scheduler, every Friday night (vercel.json → crons), with the CRON_SECRET it holds.
  Settings → Cron Jobs → Run does the same, any time.
- "Run the coach now" in the app: a POST with your sign-in. The coach asks the app whose data your
  sign-in opens and whose its own key opens, and runs only when they're the same person.
Optional: ?as_of=YYYY-MM-DD reviews a past week.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.client import AppClient, AppError  # noqa: E402
from coach.service import missing_settings, run_weekly, tracing_defaults  # noqa: E402

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Max-Age": "600",
}


def authorized(header: str, secret: str) -> bool:
    return len(secret) >= 16 and hmac.compare_digest(header.encode(), f"Bearer {secret}".encode())


def signed_in_owner(token: str) -> tuple[bool, str]:
    """Is this sign-in the person the coach's key belongs to? (ok, why not)"""
    try:
        me = AppClient(bearer=token).whoami()
        owner = AppClient().whoami()
    except AppError as e:
        return False, f"Couldn't check your sign-in with the app: {e}"
    return (me == owner), "" if me == owner else "This coach runs for another account."


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, indent=1, ensure_ascii=False).encode()
        self.send_response(status)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802 - the browser's check before "Run the coach now"
        self.send_response(204)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - the name http.server expects
        self._run(from_app=False)

    def do_POST(self) -> None:  # noqa: N802
        self._run(from_app=True)

    def _run(self, from_app: bool) -> None:
        missing = missing_settings()
        if missing:
            return self._send(500, {"error": f"Set {', '.join(missing)} in the coach's Vercel project (Settings → Environment Variables), then redeploy."})
        header = self.headers.get("authorization", "")
        secret = os.environ.get("CRON_SECRET", "")
        if authorized(header, secret):
            pass  # Vercel's scheduler (or Cron Jobs → Run)
        elif from_app and header.lower().startswith("bearer ") and len(header) > 20:
            ok, why = signed_in_owner(header[7:].strip())
            if not ok:
                return self._send(403, {"error": why})
        elif not from_app and len(secret) < 16:
            return self._send(500, {"error": "Set CRON_SECRET (16+ characters) in this project's Environment Variables, then redeploy."})
        else:
            return self._send(401, {"error": "Not allowed. Runs start from Vercel (Settings → Cron Jobs → Run) or from the app (Run the coach now)."})
        as_of = (parse_qs(urlparse(self.path).query).get("as_of") or [None])[0]
        if as_of is not None and not ISO.match(as_of):
            return self._send(400, {"error": "as_of must be YYYY-MM-DD"})
        tracing_defaults()
        try:
            result = run_weekly(as_of)
        except Exception as e:  # noqa: BLE001 - the pipeline reports its own failures; this is setup trouble
            return self._send(502, {"error": str(e), "trace": traceback.format_exc(limit=3)})
        print(json.dumps({**result, "started_by": "app" if from_app and not authorized(header, secret) else "schedule"}))
        return self._send(200, result)
