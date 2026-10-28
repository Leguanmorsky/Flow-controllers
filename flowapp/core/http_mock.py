"""The simulated card served over real HTTP JSON-RPC on this PC (tests, and trying the client).

  python -m flowapp.core.http_mock [--port 8080]    then use 127.0.0.1:8080 as the card address

Options for tests: shuffle batch replies, wrap numbers as {"value": x}, close the connection
after every N requests (like an embedded server that drops keep-alive).
"""

import argparse
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .card_sim import SimCard


class MockCardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, card, port=0, shuffle=False, objects=False, close_every=0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.card = card
        self.shuffle = shuffle
        self.objects = objects
        self.close_every = close_every
        self.requests = 0
        self.connections = 0
        self._lock = threading.Lock()
        self._thread = None

    @property
    def address(self):
        return f"127.0.0.1:{self.server_address[1]}"

    def start(self):
        self._thread = threading.Thread(target=self.serve_forever, name="MockCard", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        with self.server._lock:
            self.server.connections += 1

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._send(200, b"Simulated UHV SEM control card: POST JSON-RPC to /jsonrpc\n", "text/plain")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path != "/jsonrpc":
            self._send(404, b"not found", "text/plain")
            return
        try:
            payload = json.loads(body)
            replies = self.server.card.post(payload)
        except ConnectionError:
            self.close_connection = True
            self.connection.close()
            return
        except Exception as e:
            self._send(500, str(e).encode(), "text/plain")
            return
        if self.server.objects:
            for reply in replies if isinstance(replies, list) else [replies]:
                if isinstance(reply.get("result"), float):
                    reply["result"] = {"value": reply["result"]}
        if self.server.shuffle and isinstance(replies, list):
            random.shuffle(replies)
        with self.server._lock:
            self.server.requests += 1
            close = self.server.close_every and self.server.requests % self.server.close_every == 0
        self._send(200, json.dumps(replies).encode(), "application/json", close=close)

    def _send(self, status, data, content_type, close=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m flowapp.core.http_mock")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = MockCardServer(SimCard(), port=args.port)
    print(f"Simulated card on http://{server.address}/jsonrpc (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
