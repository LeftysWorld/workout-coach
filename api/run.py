"""The workout coach on Vercel: GET /api/run runs one weekly review and saves the report to the app.

Vercel's scheduler calls it every Friday night (vercel.json → crons) with the CRON_SECRET it holds;
Project → Settings → Cron Jobs → Run calls it the same way, any time. Nothing else can start a run.
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

from coach.service import missing_settings, run_weekly, tracing_defaults  # noqa: E402

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def authorized(header: str, secret: str) -> bool:
    return len(secret) >= 16 and hmac.compare_digest(header.encode(), f"Bearer {secret}".encode())


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, indent=1, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - the name http.server expects
        secret = os.environ.get("CRON_SECRET", "")
        if len(secret) < 16:
            return self._send(500, {"error": "Set CRON_SECRET (16+ characters) in this project's Environment Variables, then redeploy."})
        if not authorized(self.headers.get("authorization", ""), secret):
            return self._send(401, {"error": "Not allowed. Runs start from Vercel: Settings → Cron Jobs → Run."})
        missing = missing_settings()
        if missing:
            return self._send(500, {"error": f"Set {', '.join(missing)} in this project's Environment Variables, then redeploy."})
        as_of = (parse_qs(urlparse(self.path).query).get("as_of") or [None])[0]
        if as_of is not None and not ISO.match(as_of):
            return self._send(400, {"error": "as_of must be YYYY-MM-DD"})
        tracing_defaults()
        try:
            result = run_weekly(as_of)
        except Exception as e:  # noqa: BLE001 - the pipeline reports its own failures; this is setup trouble
            return self._send(502, {"error": str(e), "trace": traceback.format_exc(limit=3)})
        print(json.dumps(result))
        return self._send(200, result)
