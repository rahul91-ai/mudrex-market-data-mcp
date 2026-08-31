import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

MUDREX_API_BASE = os.getenv(
    "MUDREX_API_BASE",
    "https://api.mudrex.com"
)

PORT = int(os.getenv("PORT", "10000"))


def api_request(path):
    url = MUDREX_API_BASE.rstrip("/") + "/" + path.lstrip("/")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "mudrex-market-data-mcp/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8")

    return json.loads(data)


class Handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        if self.path == "/" or self.path == "/health":
            self.send_json({
                "status": "ok",
                "service": "mudrex-market-data-mcp"
            })
            return

        if self.path == "/market":
            try:
                data = api_request("/v1/market")
                self.send_json(data)
            except Exception as e:
                self.send_json({
                    "error": str(e)
                }, 502)
            return

        self.send_json({
            "error": "Not found"
        }, 404)

    def log_message(self, format, *args):
        print(format % args)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)

    print(f"Server running on port {PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
