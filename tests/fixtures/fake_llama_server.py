#!/usr/bin/env python3
"""Minimal llama-server stand-in for LlamaServerProcess tests.

Honours the same flag names the real binary uses (`-m`, `-md`, `--host`,
`--port`, `--draft-max`, `-ngl`, `-ngld`). Modes via FAKE_LLAMA_MODE:

  ready (default)  bind and serve GET /health → 200
  die              print to stderr and exit 1 immediately
  hang             sleep forever without binding
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", required=True)
    parser.add_argument("-md", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--draft-max", type=int, default=None)
    parser.add_argument("-ngl", type=int, default=None)
    parser.add_argument("-ngld", type=int, default=None)
    args = parser.parse_args()

    mode = os.environ.get("FAKE_LLAMA_MODE", "ready")
    if mode == "die":
        print("fake llama-server dying", file=sys.stderr)
        return 1
    if mode == "hang":
        while True:
            time.sleep(60)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write("%s\n" % (format % args))

    httpd = HTTPServer((args.host, args.port), Handler)
    print(
        f"fake llama-server listening on {args.host}:{args.port}",
        file=sys.stderr,
    )
    sys.stderr.flush()
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
