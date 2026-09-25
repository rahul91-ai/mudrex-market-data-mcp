import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings


# ============================================================
# CONFIGURATION
# ============================================================

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

ALL_TIMEFRAMES = list(INTERVAL_SECONDS.keys())

BATCH_SIZE = 25
DEFAULT_CANDLE_LIMIT = 500
MAX_CANDLE_LIMIT = 1440

PIVOT_LEFT = 3
PIVOT_RIGHT = 3

MAX_DIVERGENCE_AGE = 50


# ============================================================
# MCP SERVER
# ============================================================

mcp = FastMCP(
    "mudrex-market-data-mcp"
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def normalize_asset(asset: str) -> str:

    asset = asset.strip().upper()

    if "/" in asset:
        return asset

    if asset.endswith("USDT"):
        return asset[:-4] + "/USDT"

    return asset


def get_time_range(interval: str, limit: int):

    seconds = INTERVAL_SECONDS[interval]

    end_time = int(time.time())

    start_time = end_time - (
        seconds * limit
    )

    return start_time, end_time


# ============================================================
# MUDREX HTTP
# ============================================================

def mudrex_get(
    path: str,
    params: dict | None = None,
    retries: int = 3
):

    if params is None:
        params = {}

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    url = (
        MUDREX_BASE_URL
        + path
    )

    if query:
        url += "?" + query

    last_error = None

    for attempt in range(retries):

        try:

            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "mudrex-market-data-mcp/8.0"
                    )
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

                return json.loads(raw)

        except Exception as exc:

            last_error = exc

            if attempt < retries - 1:
                time.sleep(
                    1.5 * (attempt + 1)
                )

    raise RuntimeError(
        f"Mudrex request failed: {last_error}"
    )


# ============================================================
# ASSET DISCOVERY
# ============================================================

def fetch_futures_assets():

    result = mudrex_get("/futures")

    data = result.get(
        "data",
        result
    )

    assets = []

    if isinstance(data, dict):

        for key in (
            "items",
            "assets",
            "results",
            "data"
        ):

            if isinstance(
                data.get(key),
                list
            ):

                data = data[key]
                break

    if not isinstance(data, list):
        return []

    for item in data:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = (
            item.get("symbol")
            or item.get("asset")
            or item.get("name")
        )

        if not symbol:
            continue

        symbol = str(
            symbol
        ).upper().strip()

        if (
            symbol.endswith("USDT")
            and "/" not in symbol
        ):
            symbol = (
                symbol[:-4]
                + "/USDT"
            )

        if symbol.endswith(
            "/USDT"
        ):
            assets.append(symbol)

    return sorted(
        set(assets)
    )


# ============================================================
# KLINE FETCHING
# ============================================================

def extract_ticks(
    response: Any,
    asset: str
):

    normalized = normalize_asset(
        asset
    )

    possible = response

    if isinstance(
        response,
        dict
    ):

        possible = (
            response.get(
                "asset_ticks"
            )
            or response.get(
                "data"
            )
            or response.get(
                "result"
            )
            or response
        )

    # Dictionary response
    if isinstance(
        possible,
        dict
    ):

        candidates = [
            normalized,
            normalized.replace(
                "/",
                ""
            ),
            normalized.lower(),
            normalized.replace(
                "/",
                ""
            ).lower()
        ]

        for key in candidates:

            if key in possible:

                value = possible[key]

                if isinstance(
                    value,
                    dict
                ):

                    value = (
                        value.get(
                            "ticks"
                        )
                        or value.get(
                            "data"
                        )
                        or value.get(
                            "klines"
                        )
                        or value.get(
                            "candles"
                        )
                        or []
                    )

                if isinstance(
                    value,
                    list
                ):
                    return value

    # Single-asset list
    if isinstance(
        possible,
        list
    ):
        return possible

    return []


def fetch_klines(
    assets="BTC/USDT",
    interval="1h",
    limit=500
):

    if interval not in INTERVAL_SECONDS:
        raise ValueError(
            f"Unsupported interval: {interval}"
        )

    limit = min(
        max(
            int(limit),
            10
        ),
        MAX_CANDLE_LIMIT
    )

    asset_list = [
        normalize_asset(x)
        for x in assets.split(",")
        if x.strip()
    ]

    # Mudrex allows maximum 25 assets/request.
    if len(asset_list) > BATCH_SIZE:

        combined = {}

        for i in range(
            0,
            len(asset_list),
            BATCH_SIZE
        ):

            batch = asset_list[
                i:i + BATCH_SIZE
            ]

            batch_result = fetch_klines(
                assets=",".join(batch),
                interval=interval,
                limit=limit
            )

            combined.update(
                batch_result
            )

        return combined

    start_time, end_time = get_time_range(
        interval,
        limit
    )

    params = {
        "assets": ",".join(asset_list),
        "aggregation": interval,
        "start_time": start_time,
        "end_time": end_time
    }

    response = mudrex_get(
        "/kline",
        params
    )

    result = {}

    for asset in asset_list:

        result[asset] = extract_ticks(
            response,
            asset
        )

    return result


# ============================================================
# MARK PRICE
# ============================================================

def fetch_mark_klines(
    assets="BTC/USDT",
    interval="1h",
    limit=500
):

    limit = min(
        max(
            int(limit),
            10
        ),
        MAX_CANDLE_LIMIT
    )

    asset_list = [
        normalize_asset(x)
        for x in assets.split(",")
        if x.strip()
    ]

    if len(asset_list) > BATCH_SIZE:

        combined = {}

        for i in range(
            0,
            len(asset_list),
            BATCH_SIZE
        ):

            batch = asset_list[
                i:i + BATCH_SIZE
            ]

            combined.update(
                fetch_mark_klines(
                    assets=",".join(batch),
                    interval=interval,
                    limit=limit
                )
            )

        return combined

    start_time, end_time = get_time_range(
        interval,
        limit
    )

    params = {
        "assets": ",".join(asset_list),
        "aggregation": interval,
        "start_time": start_time,
        "end_time": end_time
    }

    response = mudrex_get(
        "/mark-kline",
        params
    )

    result = {}

    for asset in asset_list:

        result[asset] = extract_ticks(
            response,
            asset
        )

    return result


# ============================================================
# INDICATORS
# ============================================================

def calculate_ema(
    values,
    period
):

    result = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(
        values[:period]
    ) / period

    result[period - 1] = seed

    multiplier = (
        2 /
        (period + 1)
    )

    previous = seed

    for i in range(
        period,
        len(values)
    ):

        previous = (
            (
                values[i]
                - previous
            )
            * multiplier
            + previous
        )

        result[i] = previous

    return result


def calculate_rsi(
    closes,
    period=14
):

    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    gains = []
    losses = []

    for i in range(
        1,
        len(closes)
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = (
            avg_gain /
            avg_loss
        )

        result[period] = (
            100 -
            (
                100 /
                (1 + rs)
            )
        )

    for i in range(
        period + 1,
        len(closes)
    ):

        gain = gains[i - 1]
        loss = losses[i - 1]

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gain
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + loss
        ) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:

            rs = (
                avg_gain /
                avg_loss
            )

            result[i] = (
                100 -
                (
                    100 /
                    (1 + rs)
                )
            )

    return result


def calculate_momentum(
    closes,
    period=10
):

    result = [None] * len(closes)

    for i in range(
        period,
        len(closes)
    ):

        result[i] = (
            closes[i]
            - closes[i - period]
        )

    return result


def calculate_macd(
    closes
):

    ema12 = calculate_ema(
        closes,
        12
    )

    ema26 = calculate_ema(
        closes,
        26
    )

    macd = [None] * len(closes)

    for i in range(
        len(closes)
    ):

        if (
            ema12[i] is not None
            and ema26[i] is not None
        ):

            macd[i] = (
                ema12[i]
                - ema26[i]
            )

    return macd


def calculate_obv(
    closes,
    volumes
):

    if not closes:
        return []

    result = [0.0]

    for i in range(
        1,
        len(closes)
    ):

        previous = result[-1]

        if (
            closes[i]
            > closes[i - 1]
        ):

            result.append(
                previous
                + volumes[i]
            )

        elif (
            closes[i]
            < closes[i - 1]
        ):

            result.append(
                previous
                - volumes[i]
            )

        else:

            result.append(
                previous
            )

    return result


def calculate_mfi(
    highs,
    lows,
    closes,
    volumes,
    period=14
):

    result = [None] * len(closes)

    typical = []

    for h, l, c in zip(
        highs,
        lows,
        closes
    ):

        typical.append(
            (h + l + c) / 3
        )

    raw_money_flow = [
        typical[i]
        * volumes[i]
        for i in range(
            len(typical)
        )
    ]

    for i in range(
        period,
        len(closes)
    ):

        positive = 0.0
        negative = 0.0

        for j in range(
            i - period + 1,
            i + 1
        ):

            if (
                typical[j]
                > typical[j - 1]
            ):

                positive += (
                    raw_money_flow[j]
                )

            elif (
                typical[j]
                < typical[j - 1]
            ):

                negative += (
                    raw_money_flow[j]
                )

        if negative == 0:

            result[i] = 100.0

        else:

            ratio = (
                positive
                / negative
            )

            result[i] = (
                100 -
                (
                    100 /
                    (1 + ratio)
                )
            )

    return result


def calculate_stoch_rsi(
    rsi,
    period=14
):

    result = [None] * len(rsi)

    for i in range(
        period,
        len(rsi)
    ):

        window = [
            x
            for x in rsi[
                i - period + 1:
                i + 1
            ]
            if x is not None
        ]

        if len(window) < period:
            continue

        lowest = min(window)
        highest = max(window)

        if highest == lowest:

            result[i] = 0.0

        else:

            result[i] = (
                (
                    rsi[i]
                    - lowest
                )
                /
                (
                    highest
                    - lowest
                )
            ) * 100

    return result


# ============================================================
# PIVOTS
# ============================================================

def find_pivot_lows(
    values,
    left=PIVOT_LEFT,
    right=PIVOT_RIGHT
):

    pivots = []

    for i in range(
        left,
        len(values) - right
    ):

        current = values[i]

        if current is None:
            continue

        valid = True

        for j in range(
            i - left,
            i + right + 1
        ):

            if j == i:
                continue

            if (
                values[j] is None
                or values[j] <= current
            ):

                valid = False
                break

        if valid:
            pivots.append(i)

    return pivots


def find_pivot_highs(
    values,
    left=PIVOT_LEFT,
    right=PIVOT_RIGHT
):

    pivots = []

    for i in range(
        left,
        len(values) - right
    ):

        current = values[i]

        if current is None:
            continue

        valid = True

        for j in range(
            i - left,
            i + right + 1
        ):

            if j == i:
                continue

            if (
                values[j] is None
                or values[j] >= current
            ):

                valid = False
                break

        if valid:
            pivots.append(i)

    return pivots


# ============================================================
# DIVERGENCE
# ============================================================

def detect_divergences(
    closes,
    indicator,
    indicator_name
):

    signals = []

    price_lows = find_pivot_lows(
        closes
    )

    price_highs = find_pivot_highs(
        closes
    )

    # -------------------------
    # BULLISH
    # -------------------------

    for n in range(
        1,
        len(price_lows)
    ):

        p1 = price_lows[n - 1]
        p2 = price_lows[n]

        if (
            indicator[p1] is None
            or indicator[p2] is None
        ):
            continue

        # Regular bullish:
        # Price LL
        # Indicator HL

        if (
            closes[p2] < closes[p1]
            and indicator[p2]
            > indicator[p1]
        ):

            signals.append({
                "indicator":
                    indicator_name,
                "type":
                    "regular_bullish",
                "pivot_1":
                    p1,
                "pivot_2":
                    p2,
                "price_1":
                    closes[p1],
                "price_2":
                    closes[p2],
                "indicator_1":
                    indicator[p1],
                "indicator_2":
                    indicator[p2]
            })

        # Hidden bullish:
        # Price HL
        # Indicator LL

        if (
            closes[p2] > closes[p1]
            and indicator[p2]
            < indicator[p1]
        ):

            signals.append({
                "indicator":
                    indicator_name,
                "type":
                    "hidden_bullish",
                "pivot_1":
                    p1,
                "pivot_2":
                    p2,
                "price_1":
                    closes[p1],
                "price_2":
                    closes[p2],
                "indicator_1":
                    indicator[p1],
                "indicator_2":
                    indicator[p2]
            })

    # -------------------------
    # BEARISH
    # -------------------------

    for n in range(
        1,
        len(price_highs)
    ):

        p1 = price_highs[n - 1]
        p2 = price_highs[n]

        if (
            indicator[p1] is None
            or indicator[p2] is None
        ):
            continue

        # Regular bearish:
        # Price HH
        # Indicator LH

        if (
            closes[p2] > closes[p1]
            and indicator[p2]
            < indicator[p1]
        ):

            signals.append({
                "indicator":
                    indicator_name,
                "type":
                    "regular_bearish",
                "pivot_1":
                    p1,
                "pivot_2":
                    p2,
                "price_1":
                    closes[p1],
                "price_2":
                    closes[p2],
                "indicator_1":
                    indicator[p1],
                "indicator_2":
                    indicator[p2]
            })

        # Hidden bearish:
        # Price LH
        # Indicator HH

        if (
            closes[p2] < closes[p1]
            and indicator[p2]
            > indicator[p1]
        ):

            signals.append({
                "indicator":
                    indicator_name,
                "type":
                    "hidden_bearish",
                "pivot_1":
                    p1,
                "pivot_2":
                    p2,
                "price_1":
                    closes[p1],
                "price_2":
                    closes[p2],
                "indicator_1":
                    indicator[p1],
                "indicator_2":
                    indicator[p2]
            })

    return signals


# ============================================================
# SINGLE ASSET / TIMEFRAME SCANNER
# ============================================================

def scan_single(
    asset,
    interval,
    candles
):

    if not candles:

        return {
            "asset": asset,
            "interval": interval,
            "signals": [],
            "error": "No candles"
        }

    # Remove incomplete/current candle.
    candles = candles[:-1]

    if len(candles) < 100:

        return {
            "asset": asset,
            "interval": interval,
            "signals": [],
            "error": "Not enough closed candles"
        }

    try:

        opens = [
            float(x[1])
            for x in candles
        ]

        highs = [
            float(x[2])
            for x in candles
        ]

        lows = [
            float(x[3])
            for x in candles
        ]

        closes = [
            float(x[4])
            for x in candles
        ]

        volumes = [
            float(x[5])
            for x in candles
        ]

    except Exception as exc:

        return {
            "asset": asset,
            "interval": interval,
            "signals": [],
            "error":
                f"Candle parse error: {exc}"
        }

    rsi = calculate_rsi(
        closes
    )

    momentum = calculate_momentum(
        closes
    )

    macd = calculate_macd(
        closes
    )

    obv = calculate_obv(
        closes,
        volumes
    )

    mfi = calculate_mfi(
        highs,
        lows,
        closes,
        volumes
    )

    stoch_rsi = calculate_stoch_rsi(
        rsi
    )

    indicators = {
        "rsi": rsi,
        "momentum": momentum,
        "macd": macd,
        "obv": obv,
        "mfi": mfi,
        "stoch_rsi": stoch_rsi
    }

    signals = []

    for name, values in indicators.items():

        detected = detect_divergences(
            closes,
            values,
            name
        )

        for signal in detected:

            bars_ago = (
                len(closes)
                - 1
                - signal["pivot_2"]
            )

            if (
                bars_ago
                <= MAX_DIVERGENCE_AGE
            ):

                signal["asset"] = asset
                signal["interval"] = interval
                signal["bars_ago"] = bars_ago

                signals.append(
                    signal
                )

    return {
        "asset": asset,
        "interval": interval,
        "candle_count":
            len(candles),
        "signals":
            signals
    }


# ============================================================
# MULTI-TIMEFRAME SCANNER
# ============================================================

def scan_divergence_market(
    assets,
    timeframes,
    limit=500
):

    all_results = []

    for interval in timeframes:

        for start in range(
            0,
            len(assets),
            BATCH_SIZE
        ):

            batch = assets[
                start:
                start + BATCH_SIZE
            ]

            try:

                market_data = fetch_klines(
                    assets=",".join(batch),
                    interval=interval,
                    limit=limit
                )

                for asset in batch:

                    candles = (
                        market_data.get(
                            asset,
                            []
                        )
                    )

                    result = scan_single(
                        asset,
                        interval,
                        candles
                    )

                    if (
                        result.get(
                            "signals"
                        )
                    ):

                        all_results.append(
                            result
                        )

            except Exception as exc:

                all_results.append({
                    "interval":
                        interval,
                    "batch":
                        batch,
                    "signals": [],
                    "error":
                        str(exc)
                })

    return all_results


# ============================================================
# CONFLUENCE
# ============================================================

def build_confluence(
    results
):

    grouped = {}

    for result in results:

        asset = result.get(
            "asset"
        )

        interval = result.get(
            "interval"
        )

        if not asset:
            continue

        key = (
            asset,
            interval
        )

        if key not in grouped:

            grouped[key] = {
                "asset": asset,
                "interval": interval,
                "regular_bullish": [],
                "hidden_bullish": [],
                "regular_bearish": [],
                "hidden_bearish": []
            }

        for signal in result.get(
            "signals",
            []
        ):

            signal_type = signal[
                "type"
            ]

            if signal_type in grouped[key]:

                grouped[key][
                    signal_type
                ].append(
                    signal["indicator"]
                )

    output = []

    for item in grouped.values():

        bullish = (
            item["regular_bullish"]
            + item["hidden_bullish"]
        )

        bearish = (
            item["regular_bearish"]
            + item["hidden_bearish"]
        )

        item["bullish_count"] = len(
            bullish
        )

        item["bearish_count"] = len(
            bearish
        )

        item["bullish_indicators"] = sorted(
            set(bullish)
        )

        item["bearish_indicators"] = sorted(
            set(bearish)
        )

        output.append(
            item
        )

    output.sort(
        key=lambda x:
            max(
                x["bullish_count"],
                x["bearish_count"]
            ),
        reverse=True
    )

    return output


# ============================================================
# MCP TOOLS
# ============================================================

@mcp.tool()
def get_klines(
    assets: str = "BTC/USDT",
    interval: str = "1h",
    limit: int = 500
):

    """
    Fetch historical Mudrex futures OHLCV candles.
    """

    return fetch_klines(
        assets,
        interval,
        limit
    )


@mcp.tool()
def get_mark_price_klines(
    assets: str = "BTC/USDT",
    interval: str = "1h",
    limit: int = 500
):

    """
    Fetch historical Mudrex futures mark-price candles.
    """

    return fetch_mark_klines(
        assets,
        interval,
        limit
    )


@mcp.tool()
def get_futures_assets():

    """
    Return all currently tradable Mudrex
    futures assets.
    """

    return fetch_futures_assets()


@mcp.tool()
def scan_divergences(
    assets: str = "",
    timeframes: str = "all",
    limit: int = 500
):

    """
    Scan Mudrex futures for regular and hidden
    bullish/bearish divergences using:

    RSI
    Momentum
    MACD
    OBV
    MFI
    Stochastic RSI

    If assets is empty, automatically discover
    Mudrex futures assets.

    If timeframes is 'all', scan every supported
    Mudrex timeframe.
    """

    if assets.strip():

        asset_list = [
            normalize_asset(x)
            for x in assets.split(",")
            if x.strip()
        ]

    else:

        asset_list = (
            fetch_futures_assets()
        )

    if not asset_list:

        return {
            "success": False,
            "error":
                "No futures assets found"
        }

    if (
        timeframes.lower().strip()
        == "all"
    ):

        timeframe_list = (
            ALL_TIMEFRAMES
        )

    else:

        timeframe_list = [
            x.strip()
            for x in timeframes.split(",")
            if x.strip()
            in ALL_TIMEFRAMES
        ]

    if not timeframe_list:

        return {
            "success": False,
            "error":
                "No valid timeframes supplied",
            "available_timeframes":
                ALL_TIMEFRAMES
        }

    limit = min(
        max(
            int(limit),
            100
        ),
        MAX_CANDLE_LIMIT
    )

    results = scan_divergence_market(
        asset_list,
        timeframe_list,
        limit
    )

    confluence = build_confluence(
        results
    )

    return {
        "success": True,
        "asset_count":
            len(asset_list),
        "assets_scanned":
            asset_list,
        "timeframes":
            timeframe_list,
        "candle_limit":
            limit,
        "batch_size":
            BATCH_SIZE,
        "indicators": [
            "rsi",
            "momentum",
            "macd",
            "obv",
            "mfi",
            "stoch_rsi"
        ],
        "divergence_types": [
            "regular_bullish",
            "hidden_bullish",
            "regular_bearish",
            "hidden_bearish"
        ],
        "results":
            results,
        "confluence":
            confluence
    }


# ============================================================
# HEALTH
# ============================================================

@mcp.custom_route(
    "/health",
    methods=["GET"]
)
async def health(request):

    from starlette.responses import JSONResponse

    return JSONResponse({
        "status": "ok",
        "service":
            "mudrex-market-data-mcp",
        "provider":
            "Mudrex",
        "version":
            "8.0.0"
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    app = mcp.streamable_http_app()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT
    )
