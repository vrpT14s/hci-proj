import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class VSCodeBridge:
    """
    Lightweight localhost bridge so editor extensions can control the app.

    Supported POST /command payloads:
      {"action":"select_function","function":"foo"}
      {"action":"select_location","path":"/abs/file.c","line":123}
    """

    def __init__(self, port, on_command):
        self.port = port
        self.on_command = on_command
        self.server = None
        self.thread = None

    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    return self._json(200, {"ok": True})
                return self._json(404, {"error": "Not found"})

            def do_POST(self):
                if self.path != "/command":
                    return self._json(404, {"error": "Not found"})

                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"

                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    return self._json(400, {"error": "Invalid JSON"})

                action = payload.get("action")
                if action not in {"select_function", "select_location"}:
                    return self._json(400, {"error": "Unsupported action"})

                bridge.on_command(payload)
                return self._json(200, {"ok": True})

            def _json(self, status, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=1)
            self.thread = None
