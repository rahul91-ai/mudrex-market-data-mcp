import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MUDREX_BASE_URL = "https://trade.mudrex.com/fapi/v1/price"
PORT = int(os.environ.get("PORT", "10000"))


def mudrex_get(endpoint, params=None):
    url = MUDREX_BASE_URL + endpoint

    if params:
        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        if clean_params:
            url += "?" + urllib.parse.urlencode(clean_params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "mudrex-market-data-mcp/1.0",
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")

    return json.loads(body)


class Handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Health check for Render
        if path == "/" or path == "/health":
            self.send_json({
                "status": "ok",
                "service": "mudrex-market-data-mcp",
                "market_data": "Mudrex public API",
                "base_url": MUDREX_BASE_URL
            })
            return

        # API information
        if path == "/info":
            self.send_json({
                "name": "Mudrex Market Data MCP",
                "version": "1.0.0",
                "endpoints": {
                    "health": "/health",
                    "info": "/info",
                    "klines": "/klines?symbol=BTC/USDT&interval=4h&limit=500",
                    "mark_klines": "/mark-klines?symbol=BTC/USDT&interval=4h&limit=500"
                }
            })
            return

        # Historical OHLCV candles
        if path == "/klines":
            symbol = query.get("symbol", ["BTC/USDT"])[0]
            interval = query.get("interval", ["1h"])[0]
            limit = query.get("limit", ["500"])[0]

            try:
                limit = min(max(int(limit), 1), 1440)
            except ValueError:
                self.send_json({
                    "error": "limit must be an integer"
                }, 400)
                return

            try:
                data = mudrex_get(
                    "/kline",
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit
                    }
                )

                self.send_json({
                    "success": True,
                    "source": "Mudrex",
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                    "data": data
                })

            except Exception as error:
                self.send_json({
                    "success": False,
                    "error": str(error)
                }, 502)

            return

        # Historical mark-price candles
        if path == "/mark-klines":
            symbol = query.get("symbol", ["BTC/USDT"])[0]
            interval = query.get("interval", ["1h"])[0]
            limit = query.get("limit", ["500"])[0]

            try:
                limit = min(max(int(limit), 1), 1440)
            except ValueError:
                self.send_json({
                    "error": "limit must be an integer"
                }, 400)
                return

            try:
                data = mudrex_get(
                    "/mark-kline",
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit
                    }
                )

                self.send_json({
                    "success": True,
                    "source": "Mudrex",
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                    "data": data
                })

            except Exception as error:
                self.send_json({
                    "success": False,
                    "error": str(error)
                }, 502)

            return

        self.send_json({
            "error": "Not found",
            "available_endpoints": [
                "/health",
                "/info",
                "/klines",
                "/mark-klines"
            ]
        }, 404)

    def log_message(self, format, *args):
        print(format % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)

    print(f"Mudrex market-data server running on port {PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    
