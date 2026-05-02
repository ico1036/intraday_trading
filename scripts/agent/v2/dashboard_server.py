#!/usr/bin/env python3
"""HTTP server for the React dashboard.

Serves:
    GET /                 → dashboard.html (single-file React + Tailwind CDN)
    GET /api/runs         → list of runs under archive/
    GET /api/state?run_id → probe() snapshot as JSON

Usage:
    uv run python scripts/agent/v2/dashboard_server.py
    # open http://localhost:8765/

    uv run python scripts/agent/v2/dashboard_server.py --port 9000

No external deps. ``probe()`` is re-used from ``dashboard.py`` (TUI).
"""
from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import urllib.parse
import webbrowser
from functools import partial
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.agent.v2.dashboard import (  # noqa: E402
    equity_curve,
    list_runs,
    list_strategies,
    probe,
    state_to_dict,
    strategy_detail,
)


DASHBOARD_HTML_PATH = Path(__file__).with_name("dashboard.html")


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    server_version = "v2-dashboard/0.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Suppress the default per-request log spam; we're interactive.
        return

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, f"missing {path.name}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._send_file(DASHBOARD_HTML_PATH, "text/html; charset=utf-8")
            return

        if parsed.path == "/api/runs":
            self._send_json(list_runs())
            return

        if parsed.path == "/api/state":
            run_id = qs.get("run_id", [None])[0]
            if not run_id:
                runs = list_runs()
                if not runs:
                    self._send_json(
                        {"error": "no runs"}, status=404
                    )
                    return
                run_id = runs[0]["run_id"]
            state = probe(run_id)
            self._send_json(state_to_dict(state))
            return

        if parsed.path == "/api/strategies":
            self._send_json(list_strategies())
            return

        if parsed.path == "/api/strategy":
            run_id = qs.get("run_id", [None])[0]
            thesis_id = qs.get("thesis_id", [None])[0]
            expression_id = qs.get("expression_id", [None])[0]
            if not (run_id and thesis_id and expression_id):
                self._send_json(
                    {"error": "run_id, thesis_id, expression_id required"},
                    status=400,
                )
                return
            self._send_json(strategy_detail(run_id, thesis_id, expression_id))
            return

        if parsed.path == "/api/equity":
            run_id = qs.get("run_id", [None])[0]
            thesis_id = qs.get("thesis_id", [None])[0]
            expression_id = qs.get("expression_id", [None])[0]
            if not (run_id and thesis_id and expression_id):
                self._send_json(
                    {"error": "run_id, thesis_id, expression_id required"},
                    status=400,
                )
                return
            try:
                self._send_json(equity_curve(run_id, thesis_id, expression_id))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        self.send_error(404, f"unknown path: {parsed.path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v2 dashboard web server")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-open", action="store_true", help="don't auto-open browser")
    args = p.parse_args(argv)

    addr = (args.host, args.port)

    if not DASHBOARD_HTML_PATH.is_file():
        print(
            f"[dashboard] missing {DASHBOARD_HTML_PATH}; UI cannot render.",
            file=sys.stderr,
        )
        return 1

    with ReusableTCPServer(addr, DashboardHandler) as httpd:
        url = f"http://{args.host}:{args.port}/"
        print(f"[dashboard] serving {url}", flush=True)
        if not args.no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[dashboard] stopped", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
