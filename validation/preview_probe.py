"""Expose a disposable preview with a boot marker and an in-memory counter."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from secrets import token_hex


class Preview(BaseHTTPRequestHandler):
    def write(self, body, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def state(self):
        return {"boot": self.server.boot, "count": self.server.count}

    def do_GET(self):
        if self.path == "/":
            body = b"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>OpenHands preview probe</title>
<h1>Live preview</h1><button id="check">Check live process</button><pre id="state"></pre>
<script>
const show = async (path, method) => {
  const response = await fetch(path, {method, cache: 'no-store'});
  document.querySelector('#state').textContent = response.ok
    ? JSON.stringify(await response.json(), null, 2) : 'Preview unavailable';
};
document.querySelector('#check').onclick = () => show('./check', 'POST');
show('./state', 'GET');
</script></html>"""
            self.write(body, "text/html; charset=utf-8")
        elif self.path == "/state":
            self.write(json.dumps(self.state()).encode(), "application/json")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/check":
            self.send_error(404)
            return
        self.server.count += 1
        self.write(json.dumps(self.state()).encode(), "application/json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1", choices=("127.0.0.1", "0.0.0.0"))
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with HTTPServer((args.listen, args.port), Preview) as server:
        server.boot = token_hex(12)
        server.count = 0
        server.serve_forever()
