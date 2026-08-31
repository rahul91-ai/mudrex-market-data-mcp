import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


MUDREX_BASE_URL = "https://trade.mudrex.com/fapi/v1/price"

PORT = int(os.environ.get("PORT", "10000"))


INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
}


class MudrexAPIError(Exception):

    def __init__(self, status, url, body):
        self.status = status
        self.url = url
        self.body = body

        super().__init__(
            f"Mudrex API returned HTTP {status}"
        )


def mudrex_get(endpoint, params):

    url = (
        MUDREX_BASE_URL.rstrip("/")
        + "/"
        + endpoint.lstrip("/")
    )

    url += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mudrex-Market-Data-MCP/6.0",
        },
        method="GET",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            body = response.read().decode(
                "utf-8"
            )

            try:
                data = json.loads(body)

            except json.JSONDecodeError:
                data = body

            return response.status, data

    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="replace"
        )

        try:
            data = json.loads(body)

        except json.JSONDecodeError:
            data = body

        raise MudrexAPIError(
            error.code,
            url,
            data
        )

    except urllib.error.URLError as error:

        raise MudrexAPIError(
            502,
            url,
            {
                "error":
                    "Unable to connect to Mudrex",
                "details":
                    str(error.reason),
            }
        )


def normalize_asset(asset):

    asset = asset.strip().upper()

    asset = asset.replace("-", "/")

    if (
        "/" not in asset
        and asset.endswith("USDT")
    ):
        asset = (
            asset[:-4]
            + "/USDT"
        )

    return asset


def get_time_range(interval, limit):

    if interval not in INTERVAL_SECONDS:

        raise ValueError(
            "Unsupported interval: "
            + interval
        )

    end_time = int(time.time())

    start_time = (
        end_time
        - INTERVAL_SECONDS[interval] * limit
    )

    if start_time <= 0:

        raise ValueError(
            "start_time must be greater than 0"
        )

    if end_time <= 0:

        raise ValueError(
            "end_time must be greater than 0"
        )

    return start_time, end_time


def fetch_klines(
    assets="BTC/USDT",
    interval="1h",
    limit=500,
):

    assets = normalize_asset(assets)

    interval = interval.lower()

    limit = int(limit)

    limit = max(
        1,
        min(limit, 1440)
    )

    start_time, end_time = (
        get_time_range(
            interval,
            limit
        )
    )

    params = {

        "assets":
            assets,

        "aggregation":
            interval,

        "start_time":
            start_time,

        "end_time":
            end_time,
    }

    _, data = mudrex_get(
        "/kline",
        params
    )

    return {
        "success": True,
        "source": "Mudrex",
        "request": params,
        "data": data,
    }


def fetch_mark_klines(
    assets="BTC/USDT",
    interval="1h",
    limit=500,
):

    assets = normalize_asset(assets)

    interval = interval.lower()

    limit = int(limit)

    limit = max(
        1,
        min(limit, 1440)
    )

    start_time, end_time = (
        get_time_range(
            interval,
            limit
        )
    )

    params = {

        "assets":
            assets,

        "aggregation":
            interval,

        "start_time":
            start_time,

        "end_time":
            end_time,
    }

    _, data = mudrex_get(
        "/mark-kline",
        params
    )

    return {
        "success": True,
        "source": "Mudrex",
        "request": params,
        "data": data,
    }


# --------------------------------------------------
# MCP SERVER
# --------------------------------------------------

mcp = FastMCP(
    "Mudrex Market Data"
)


@mcp.tool()
def get_klines(
    assets: str = "BTC/USDT",
    interval: str = "1h",
    limit: int = 500,
) -> dict:
    """
    Get historical OHLCV candlestick data
    from the public Mudrex market-data API.

    assets examples:
    BTC/USDT
    ETH/USDT
    SOL/USDT

    Supported intervals:
    1m, 3m, 5m, 15m, 30m,
    1h, 2h, 4h, 6h, 8h,
    12h, 1d, 3d, 1w

    Maximum 1440 candles.
    """

    try:

        return fetch_klines(
            assets,
            interval,
            limit
        )

    except MudrexAPIError as error:

        return {
            "success": False,
            "source": "Mudrex",
            "http_status": error.status,
            "request_url": error.url,
            "error": error.body,
        }

    except Exception as error:

        return {
            "success": False,
            "error": str(error),
        }


@mcp.tool()
def get_mark_price_klines(
    assets: str = "BTC/USDT",
    interval: str = "1h",
    limit: int = 500,
) -> dict:
    """
    Get historical mark-price candles
    from Mudrex.
    """

    try:

        return fetch_mark_klines(
            assets,
            interval,
            limit
        )

    except MudrexAPIError as error:

        return {
            "success": False,
            "source": "Mudrex",
            "http_status": error.status,
            "request_url": error.url,
            "error": error.body,
        }

    except Exception as error:

        return {
            "success": False,
            "error": str(error),
        }


@mcp.tool()
def get_market_data(
    assets: str = "BTC/USDT",
    interval: str = "4h",
    limit: int = 500,
) -> dict:
    """
    Convenience tool for crypto market analysis.

    Returns OHLCV candle data from Mudrex.
    """

    return get_klines(
        assets,
        interval,
        limit
    )


# --------------------------------------------------
# HEALTH ENDPOINT
# --------------------------------------------------

async def health(request: Request):

    return JSONResponse({

        "status": "ok",

        "service":
            "mudrex-market-data-mcp",

        "provider":
            "Mudrex",

        "mcp":
            "/mcp",

        "version":
            "6.0.0",
    })


# --------------------------------------------------
# ASGI APPLICATION
# --------------------------------------------------

mcp_app = mcp.streamable_http_app()


async def application(
    scope,
    receive,
    send
):

    if scope["type"] == "http":

        path = scope.get(
            "path",
            ""
        )

        if path == "/health":

            response = await health(
                Request(
                    scope,
                    receive
                )
            )

            await response(
                scope,
                receive,
                send
            )

            return

    await mcp_app(
        scope,
        receive,
        send
    )


if __name__ == "__main__":

    import uvicorn

    print(
        "Starting Mudrex Market Data MCP"
    )

    print(
        f"Port: {PORT}"
    )

    print(
        "MCP endpoint: /mcp"
    )

    uvicorn.run(
        application,
        host="0.0.0.0",
        port=PORT,
    )
