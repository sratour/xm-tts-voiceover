#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A throwaway OpenAI-compatible TTS server, for exercising the openai backend.

Serves just enough of the surface that `providers/openai_compat.py` talks to:

    GET  /v1/audio/voices   -> {"data": [{"id": "mock-voice", ...}, ...]}
    POST /v1/audio/speech   -> raw mp3 bytes (echoes back a fixed sample)

Used by tests/smoke_test.py so the HTTP plumbing is verified without a real API
key. Run it standalone to poke at it by hand:

    python tests/mock_openai.py 8123
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# A minimal but valid silent-ish mp3 payload is not needed: the client only
# checks that bytes came back and writes them to disk, so any blob works.
FAKE_AUDIO = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 2048

VOICES = ["mock-voice", "mock-voice-alt"]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep test output clean

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/audio/voices"):
            self._json({"data": [{"id": v, "name": v} for v in VOICES]})
        else:
            self._json({"error": {"message": "not found"}}, status=404)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/audio/speech"):
            self._json({"error": {"message": "not found"}}, status=404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            self._json({"error": {"message": "bad json"}}, status=400)
            return

        # Mimic the real API's validation so the client's error path is covered.
        if not payload.get("input"):
            self._json({"error": {"message": "input is required"}}, status=400)
            return
        if payload.get("voice") not in VOICES and payload.get("voice") != "alloy":
            self._json({"error": {"message": "unknown voice"}}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(FAKE_AUDIO)))
        self.end_headers()
        self.wfile.write(FAKE_AUDIO)


def start(port=0):
    """Start the server on a background thread; return (server, base_url)."""
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d/v1" % server.server_address[1]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    srv, url = start(port)
    print("mock OpenAI-compatible TTS server on %s" % url)
    print("  GET  %s/audio/voices" % url)
    print("  POST %s/audio/speech" % url)
    print("Ctrl-C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
