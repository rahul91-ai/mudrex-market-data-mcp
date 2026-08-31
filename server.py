import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MUDREX_BASE_URL = "https://trade.mudrex.com/fapi/v1/price"
PORT = int(os.environ.get("PORT", "10000"))


def mudrex_get(endpoint, params=None):
    url = MUDREX_BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")

    if params:
        params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }

        if params:
            url += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mudrex-Market-Data-MCP/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = body

            return {
                "http_status": response.status,
                "url": url,
                "data": data,
            }

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")

        try:
            error_data = json.loads(error_body)
        except json.JSONDecodeError:
            error_data = error_body

        raise MudrexAPIError(
            error.code,
            url,
            error_data,
        )

    except urllib.error.URLError as error:
        raise MudrexAPIError(
            502,
            url,
            {
                "error": "Unable to connect to Mudrex",
                "details": str(error.reason),
            },
        )


class MudrexAPIError(Exception):

    def __init__(self, status, url, body):
        self.status = status
        self.url = url
        self.body = body

        super().__init__(
            f"Mudrex API returned HTTP {status}"
        )


def get_query(query, name, default=None):
    values = query.get(name)

    if not values:
        return default

    return values[0]


class Handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):

        body = json.dumps(
            data,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Cache-Control",
            "no-cache",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        parsed = urllib.parse.urlparse(self.path)

        path = parsed.path

        query = urllib.parse.parse_qs(
            parsed.query
        )

        # --------------------------------------------------
        # HEALTH
        # --------------------------------------------------

        if path in ("/", "/health"):

            self.send_json({
                "status": "ok",
                "service": "mudrex-market-data-mcp",
                "provider": "Mudrex",
            })

            return

        # --------------------------------------------------
        # INFORMATION
        # --------------------------------------------------

        if path == "/info":

            self.send_json({
                "name": "Mudrex Market Data MCP",
                "version": "2.0.0",
                "provider": "Mudrex",
                "public_market_data": True,
                "endpoints": {
                    "health": "/health",
                    "info": "/info",
                    "klines": "/klines",
                    "mark_klines": "/mark-klines",
                },
                "example": (
                    "/klines"
                    "?symbol=BTC%2FUSDT"
                    "&interval=4h"
                    "&limit=10"
                ),
            })

            return

        # --------------------------------------------------
        # HISTORICAL KLINES
        # --------------------------------------------------

        if path == "/klines":

            symbol = get_query(
                query,
                "symbol",
                "BTC/USDT",
            )

            interval = get_query(
                query,
                "interval",
                "1h",
            )

            limit = get_query(
                query,
                "limit",
                "500",
            )

            # Normalize common symbol formats.
            symbol = symbol.strip().upper()

            symbol = symbol.replace(
                "-",
                "/",
            )

            if "/" not in symbol and symbol.endswith("USDT"):

                symbol = (
                    symbol[:-4]
                    + "/USDT"
                )

            try:

                limit_int = int(limit)

            except ValueError:

                self.send_json({
                    "success": False,
                    "error": "limit must be an integer",
                }, 400)

                return

            if limit_int < 1:

                limit_int = 1

            if limit_int > 1440:

                limit_int = 1440

            try:

                result = mudrex_get(
                    "/kline",
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit_int,
                    },
                )

                self.send_json({
                    "success": True,
                    "source": "Mudrex",
                    "endpoint": "/price/kline",
                    "request": {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit_int,
                    },
                    "data": result["data"],
                })

            except MudrexAPIError as error:

                self.send_json({
                    "success": False,
                    "source": "Mudrex",
                    "mudrex_http_status": error.status,
                    "request_url": error.url,
                    "mudrex_response": error.body,
                }, error.status)

            except Exception as error:

                self.send_json({
                    "success": False,
                    "error": str(error),
                }, 500)

            return

        # --------------------------------------------------
        # MARK PRICE KLINES
        # --------------------------------------------------

        if path == "/mark-klines":

            symbol = get_query(
                query,
                "symbol",
                "BTC/USDT",
            )

            interval = get_query(
                query,
                "interval",
                "1h",
            )

            limit = get_query(
                query,
                "limit",
                "500",
            )

            symbol = symbol.strip().upper()

            symbol = symbol.replace(
                "-",
                "/",
            )

            if "/" not in symbol and symbol.endswith("USDT"):

                symbol = (
                    symbol[:-4]
                    + "/USDT"
                )

            try:

                limit_int = int(limit)

            except ValueError:

                self.send_json({
                    "success": False,
                    "error": "limit must be an integer",
                }, 400)

                return

            limit_int = max(
                1,
                min(limit_int, 1440),
            )

            try:

                result = mudrex_get(
                    "/mark-kline",
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit_int,
                    },
                )

                self.send_json({
                    "success": True,
                    "source": "Mudrex",
                    "endpoint": "/price/mark-kline",
                    "request": {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit_int,
                    },
                    "data": result["data"],
                })

            except MudrexAPIError as error:

                self.send_json({
                    "success": False,
                    "source": "Mudrex",
                    "mudrex_http_status": error.status,
                    "request_url": error.url,
                    "mudrex_response": error.body,
                }, error.status)

            except Exception as error:

                self.send_json({
                    "success": False,
                    "error": str(error),
                }, 500)

            return

        # --------------------------------------------------
        # 404
        # --------------------------------------------------

        self.send_json({
            "success": False,
            "error": "Endpoint not found",
            "available_endpoints": [
                "/health",
                "/info",
                "/klines",
                "/mark-klines",
            ],
        }, 404)

    def log_message(self, format, *args):

        print(
            "[HTTP]",
            format % args,
        )


if __name__ == "__main__":

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        Handler,
    )

    print(
        "Mudrex Market Data server started"
    )

    print(
        f"Listening on 0.0.0.0:{PORT}"
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "Server shutting down..."
        )

    finally:

        server.server_close()
    
