#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A throwaway Azure Speech TTS server, for exercising the azure backend.

Serves just enough of the REST surface that `providers/azure.py` talks to:

    GET  /cognitiveservices/voices/list  -> [{ShortName, Gender, Locale, ...}]
    POST /cognitiveservices/v1           -> raw mp3 bytes (echoes a fixed sample)

Both require the `Ocp-Apim-Subscription-Key` header, like the real service.
Used by tests/smoke_test.py so the SSML/HTTP plumbing is verified without a
real Azure key. Run it standalone to poke at it by hand:

    python tests/mock_azure.py 8124
"""

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

FAKE_AUDIO = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 2048

VOICES = [
    {"ShortName": "zh-CN-XiaoxiaoNeural", "DisplayName": "Xiaoxiao",
     "Gender": "Female", "Locale": "zh-CN"},
    {"ShortName": "zh-CN-YunxiNeural", "DisplayName": "Yunxi",
     "Gender": "Male", "Locale": "zh-CN"},
]

_VOICE_RE = re.compile(r"name='([^']+)'")
_LANG_RE = re.compile(r"xml:lang='([^']+)'")


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

    def _authorised(self):
        if not self.headers.get("Ocp-Apim-Subscription-Key"):
            self._json({"error": {"code": "401", "message": "missing subscription key"}},
                       status=401)
            return False
        return True

    def do_GET(self):
        if not self._authorised():
            return
        if self.path.rstrip("/").endswith("/cognitiveservices/voices/list"):
            self._json(VOICES)
        else:
            self._json({"error": {"code": "404", "message": "not found"}}, status=404)

    def do_POST(self):
        if not self._authorised():
            return
        if not self.path.rstrip("/").endswith("/cognitiveservices/v1"):
            self._json({"error": {"code": "404", "message": "not found"}}, status=404)
            return

        if "application/ssml+xml" not in (self.headers.get("Content-Type") or ""):
            self._json({"error": {"code": "415", "message": "expected application/ssml+xml"}},
                       status=415)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        ssml = raw.decode("utf-8", "replace")

        # Mimic the real API's validation so the client's error path is covered.
        match = _VOICE_RE.search(ssml)
        voice = match.group(1) if match else ""
        if voice not in [v["ShortName"] for v in VOICES]:
            self._json({"error": {"code": "BadRequest", "message": "unknown voice"}},
                       status=400)
            return
        if not _LANG_RE.search(ssml):
            self._json({"error": {"code": "BadRequest", "message": "missing xml:lang"}},
                       status=400)
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
    return server, "http://127.0.0.1:%d" % server.server_address[1]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8124
    srv, url = start(port)
    print("mock Azure Speech server on %s" % url)
    print("  GET  %s/cognitiveservices/voices/list" % url)
    print("  POST %s/cognitiveservices/v1" % url)
    print("Ctrl-C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
