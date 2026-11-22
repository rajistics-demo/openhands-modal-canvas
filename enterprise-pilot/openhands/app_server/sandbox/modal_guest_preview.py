"""VM-side authentication for the pilot's synthetic HTTP preview tunnel."""
import hmac
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PreviewProxy(BaseHTTPRequestHandler):
    def forward(self):
        supplied = self.headers.get('X-OpenHands-Preview-Key', '')
        expected = os.environ['OH_SESSION_API_KEYS_0']
        if not hmac.compare_digest(supplied, expected):
            self.send_error(401)
            return
        if self.path not in ('/', '/state', '/check'):
            self.send_error(404)
            return
        try:
            request = Request('http://127.0.0.1:8012' + self.path, method=self.command)
            with urlopen(request, timeout=5) as response:
                content = response.read(1024 * 1024)
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers['Content-Type'])
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        except HTTPError as error:
            self.send_error(error.code)
        except (URLError, TimeoutError):
            self.send_error(503)

    do_GET = forward
    do_POST = forward

    def log_message(self, format, *args):
        return


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8011), PreviewProxy).serve_forever()
