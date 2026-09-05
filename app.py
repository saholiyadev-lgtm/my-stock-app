import math
import os
import time
from urllib.parse import quote

import requests
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


# ============================================================
# CONFIG
# ============================================================

PORT = int(os.environ.get("PORT", 5000))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# ROBUST HTTP HELPER
# ============================================================

def yahoo_get(url, timeout=10, retries=2):
    """
    Yahoo HTTP helper.

    Handles:
    - 429 rate limiting
    - 5xx server errors
    - request errors
    - invalid JSON

    IMPORTANT:
    HTTP 401 is returned as an exception.
    Individual endpoints decide whether 401 is fatal or optional.
    """

    last_error = None

    for attempt in range(retries + 1):

        try:
            response = SESSION.get(
                url,
                timeout=timeout
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in (
                429,
                500,
                502,
                503,
                504
            ):
                last_error = RuntimeError(
                    f"Yahoo Finance HTTP {response.status_code}"
                )

                if attempt < retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue

            text = response.text[:500].replace("\n", " ")

            raise RuntimeError(
                f"Yahoo Finance HTTP {response.status_code}: {text}"
            )

        except requests.RequestException as exc:

            last_error = exc

            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue

        except ValueError as exc:

            last_error = RuntimeError(
                f"Yahoo returned invalid JSON: {exc}"
            )

            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue

    raise last_error or RuntimeError(
        "Yahoo Finance request failed"
    )


# ============================================================
# SAFE NUMBER HELPERS
# ============================================================

def safe_number(value, default=0):
    try:

        if value is None:
            return default

        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def raw_value(obj, key, default=0):

    if not isinstance(obj, dict):
        return default

    value = obj.get(key)

    if isinstance(value, dict):
        return safe_number(
            value.get("raw"),
            default
        )

    return safe_number(
        value,
        default
    )


# ============================================================
# SYMBOL NORMALIZER
# ============================================================

def normalize_symbol(symbol):

    symbol = (symbol or "").strip().upper()

    if not symbol:
        return ""

    # Already Yahoo format
    if "." in symbol:
        return symbol

    # Common Indian exchanges
    indian_symbols = (
        ".NS",
        ".BO"
    )

    # If frontend sends a normal Indian ticker,
    # defaulting to NSE is useful for this application.
    #
    # Examples:
    # RELIANCE -> RELIANCE.NS
    # TCS -> TCS.NS
    # INFY -> INFY.NS

    common_indian = {
        "TCS",
        "INFY",
        "RELIANCE",
        "ICEMAKER",
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "ITC",
        "LT",
        "AXISBANK",
        "MARUTI",
        "TATAMOTORS",
        "TATASTEEL",
        "HINDUNILVR",
        "BHARTIARTL",
        "ADANIENT",
        "ADANIPORTS",
        "SUNPHARMA",
        "WIPRO",
    )

    if symbol in common_indian:
        return symbol + ".NS"

    return symbol


# ============================================================
# 1. LIVE STOCK SEARCH API
# ============================================================

@app.route("/api/search", methods=["GET"])
def search_stocks():

    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify([])

    try:

        url = (
            "https://query2.finance.yahoo.com/v1/finance/search"
            f"?q={quote(query)}"
            "&quotesCount=10"
            "&newsCount=0"
        )

        data = yahoo_get(
            url,
            timeout=8,
            retries=2
        )

        suggestions = []

        for item in data.get("quotes", []):

            symbol = item.get("symbol")

            quote_type = item.get(
                "quoteType",
                ""
            )

            if not symbol:
                continue

            name = (
                item.get("shortname")
                or item.get("longname")
                or symbol
            )

            exchange = (
                item.get("exchDisp")
                or item.get("exchange")
                or ""
            )

            suggestions.append({
                "symbol": symbol,
                "name": name,
                "exchange": exchange,
                "type": quote_type,
            })

        return jsonify(suggestions)

    except Exception as exc:

        app.logger.exception(
            "Search error"
        )

        return jsonify({
            "status": "error",
            "message": (
                f"Search failed: {str(exc)}"
            )
        }), 502


# ============================================================
# 2. YAHOO CHART DATA
# ============================================================

def get_chart_data(symbol):

    """
    Uses Yahoo Chart API instead of /v7/finance/quote.

    This is the important 401 workaround.
    """

    chart_url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}"
        "?range=5d"
        "&interval=1d"
        "&events=div%2Csplits"
    )

    return yahoo_get(
        chart_url,
        timeout=10,
        retries=2
    )


# ============================================================
# 3. EXTRACT BASIC DATA FROM CHART
# ============================================================

def extract_chart_quote(chart_data, symbol):

    result = (
        chart_data
        .get("chart", {})
        .get("result", [])
    )

    if not result:
        return {}

    result = result[0]

    meta = result.get(
        "meta",
        {}
    ) or {}

    current_price = (
        safe_number(
            meta.get("regularMarketPrice")
        )
        or safe_number(
            meta.get("currentPrice")
        )
        or safe_number(
            meta.get("previousClose")
        )
        or safe_number(
            meta.get("chartPreviousClose")
        )
    )

    company_name = (
        meta.get("longName")
        or meta.get("shortName")
        or symbol
    )

    currency = (
        meta.get("currency")
        or ""
    )

    previous_close = (
        safe_number(
            meta.get("previousClose")
        )
        or safe_number(
            meta.get("chartPreviousClose")
        )
    )

    return {
        "symbol": (
            meta.get("symbol")
            or symbol
        ),

        "longName": company_name,

        "shortName": (
            meta.get("shortName")
            or company_name
        ),

        "currency": currency,

        "regularMarketPrice": current_price,

        "previousClose": previous_close,
    }


# ============================================================
# 4. OPTIONAL FUNDAMENTAL DATA
# ============================================================

def get_optional_fundamentals(symbol):

    """
    quoteSummary is OPTIONAL.

    If Yahoo returns 401 / 403 / 429 here,
    the main stock analysis will NOT fail.

    Returns safe defaults.
    """

    result = {
        "eps": 0.0,
        "bvps": 0.0,
        "pe": 0.0,
        "forward_pe": 0.0,
        "peg": 0.0,
        "free_cash_flow": 0.0,
        "operating_cash_flow": 0.0,
        "growth_rate": 0.12,
        "roe": 0.0,
    }

    try:

        summary_url = (
            "https://query2.finance.yahoo.com/v10/finance/"
            "quoteSummary/"
            f"{quote(symbol)}"
            "?modules="
            "defaultKeyStatistics,"
            "financialData,"
            "summaryDetail,"
            "price"
        )

        summary = yahoo_get(
            summary_url,
            timeout=8,
            retries=1
        )

        modules_list = (
            summary
            .get("quoteSummary", {})
            .get("result", [])
        )

        if not modules_list:
            return result

        modules = modules_list[0] or {}

        financial = (
            modules.get(
                "financialData",
                {}
            )
            or {}
        )

        statistics = (
            modules.get(
                "defaultKeyStatistics",
                {}
            )
            or {}
        )

        summary_detail = (
            modules.get(
                "summaryDetail",
                {}
            )
            or {}
        )

        price_module = (
            modules.get(
                "price",
                {}
            )
            or {}
        )

        result["eps"] = (
            raw_value(
                statistics,
                "trailingEps",
                0
            )
            or raw_value(
                price_module,
                "epsTrailingTwelveMonths",
                0
            )
        )

        result["bvps"] = raw_value(
            statistics,
            "bookValue",
            0
        )

        result["pe"] = (
            raw_value(
                summary_detail,
                "trailingPE",
                0
            )
            or raw_value(
                statistics,
                "trailingPE",
                0
            )
        )

        result["forward_pe"] = (
            raw_value(
                summary_detail,
                "forwardPE",
                0
            )
            or raw_value(
                statistics,
                "forwardPE",
                0
            )
        )

        result["peg"] = raw_value(
            statistics,
            "pegRatio",
            0
        )

        result["free_cash_flow"] = raw_value(
            financial,
            "freeCashflow",
            0
        )

        result["operating_cash_flow"] = raw_value(
            financial,
            "operatingCashflow",
            0
        )

        result["growth_rate"] = raw_value(
            financial,
            "earningsGrowth",
            0.12
        )

        result["roe"] = raw_value(
            financial,
            "returnOnEquity",
            0
        )

        return result

    except Exception as exc:

        app.logger.warning(
            "Optional fundamentals unavailable for %s: %s",
            symbol,
            exc
        )

        # IMPORTANT:
        # Do NOT raise here.
        # Main analysis continues.

        return result


# ============================================================
# 5. MAIN STOCK ANALYZER
# ============================================================

@app.route("/api/analyze", methods=["GET"])
def analyze():

    original_symbol = (
        request.args
        .get("symbol", "")
        .strip()
        .upper()
    )

    if not original_symbol:

        return jsonify({
            "status": "error",
            "message": "Symbol is required."
        }), 400

    symbol = normalize_symbol(
        original_symbol
    )

    try:

        # ====================================================
        # PRIMARY DATA SOURCE
        # ====================================================
        #
        # IMPORTANT:
        # /v7/finance/quote has been completely removed.
        #
        # Current price comes from Chart API.
        #

        try:

            chart_data = get_chart_data(
                symbol
            )

            q = extract_chart_quote(
                chart_data,
                symbol
            )

        except Exception as chart_error:

            app.logger.exception(
                "Chart API failed for %s",
                symbol
            )

            return jsonify({
                "status": "error",
                "message": (
                    f"{symbol} નો market data મળ્યો નથી. "
                    f"Yahoo error: {str(chart_error)}"
                )
            }), 502


        # ====================================================
        # CHECK BASIC DATA
        # ====================================================

        if not q:

            return jsonify({
                "status": "error",
                "message": (
                    f"{symbol} નો data મળ્યો નથી. "
                    "કૃપા કરીને searchમાંથી exact stock પસંદ કરો."
                )
            }), 404


        # ====================================================
        # CURRENT PRICE
        # ====================================================

        current_price = (
            safe_number(
                q.get("regularMarketPrice")
            )
            or safe_number(
                q.get("previousClose")
            )
        )

        if current_price <= 0:

            return jsonify({
                "status": "error",
                "message": (
                    f"{symbol} નો current price "
                    "Yahoo Finance પર ઉપલબ્ધ નથી."
                )
            }), 404


        # ====================================================
        # CURRENCY
        # ====================================================

        currency_code = (
            q.get("currency")
            or ""
        ).upper()

        if (
            currency_code == "INR"
            or symbol.endswith(".NS")
            or symbol.endswith(".BO")
        ):
            currency = "₹"
        else:
            currency = "$"


        # ====================================================
        # COMPANY NAME
        # ====================================================

        company_name = (
            q.get("longName")
            or q.get("shortName")
            or symbol
        )


        # ====================================================
        # OPTIONAL FUNDAMENTALS
        # ====================================================

        fundamentals = get_optional_fundamentals(
            symbol
        )

        eps = safe_number(
            fundamentals.get("eps")
        )

        bvps = safe_number(
            fundamentals.get("bvps")
        )

        pe = safe_number(
            fundamentals.get("pe")
        )

        forward_pe = safe_number(
            fundamentals.get("forward_pe")
        )

        peg = safe_number(
            fundamentals.get("peg")
        )

        free_cash_flow = safe_number(
            fundamentals.get("free_cash_flow")
        )

        operating_cash_flow = safe_number(
            fundamentals.get(
                "operating_cash_flow"
            )
        )

        growth_rate = safe_number(
            fundamentals.get(
                "growth_rate"
            ),
            0.12
        )

        roe_raw = safe_number(
            fundamentals.get(
                "roe"
            )
        )


        # ====================================================
        # DEFAULT GROWTH
        # ====================================================

        if not math.isfinite(
            growth_rate
        ):
            growth_rate = 0.12

        growth_rate = max(
            -0.90,
            min(
                growth_rate,
                2.0
            )
        )


        # ====================================================
        # ROE
        # ====================================================

        if roe_raw:

            # Yahoo usually provides ROE as decimal.
            if abs(roe_raw) <= 5:
                roe = roe_raw * 100
            else:
                roe = roe_raw

        elif pe > 0:

            # Conservative fallback.
            roe = 15.0

        else:

            roe = 0.0


        # ====================================================
        # GRAHAM INTRINSIC VALUE
        # ====================================================

        graham_val = None

        if eps > 0 and bvps > 0:

            graham_calc = (
                22.5
                * eps
                * bvps
            )

            if graham_calc > 0:

                graham_val = math.sqrt(
                    graham_calc
                )


        # ====================================================
        # BEST BUY PRICE
        # ====================================================

        if graham_val:

            best_buy_price = round(
                graham_val * 0.80,
                2
            )

        elif pe > 30:

            best_buy_price = round(
                current_price * 0.80,
                2
            )

        else:

            best_buy_price = round(
                current_price * 0.90,
                2
            )


        # ====================================================
        # PROJECTED TARGETS
        # ====================================================

        dcf_1yr_target = round(
            current_price
            * (1 + growth_rate),
            2
        )

        dcf_3yr_target = round(
            current_price
            * ((1 + growth_rate) ** 3),
            2
        )


        # ====================================================
        # VALUATION STATUS
        # ====================================================

        if (
            graham_val
            and current_price
            < graham_val * 0.85
        ):

            status = (
                "UNDERVALUED 🟢 "
                "(Strong Buying Zone)"
            )

            status_type = "success"


        elif (
            graham_val
            and current_price
            > graham_val * 1.20
        ):

            status = (
                "OVERVALUED 🔴 "
                "(High Valuation Risk)"
            )

            status_type = "danger"


        elif (
            peg
            and 0 < peg < 1
        ):

            status = (
                "UNDERVALUED 🟢 "
                "(Good Growth Potential)"
            )

            status_type = "success"


        elif (
            pe
            and pe > 40
        ):

            status = (
                "OVERVALUED 🔴 "
                "(Expensive Stock)"
            )

            status_type = "danger"


        else:

            status = (
                "FAIRLY VALUED 🟡 "
                "(Fair Price Zone)"
            )

            status_type = "warning"


        # ====================================================
        # DISCOUNT / MARGIN
        # ====================================================

        if current_price > 0:

            discount_margin = (
                (
                    best_buy_price
                    - current_price
                )
                / current_price
            ) * 100

        else:

            discount_margin = 0


        # ====================================================
        # RESPONSE
        # ====================================================

        return jsonify({

            "status": "success",

            "symbol": symbol,

            "company_name": company_name,

            "currency": currency,

            "current_price": round(
                current_price,
                2
            ),

            "valuation": {

                "status": status,

                "status_type": status_type,

                "intrinsic_value": (
                    f"{currency}"
                    f"{round(graham_val, 2)}"
                    if graham_val
                    else "N/A"
                ),

                "best_buy_price": (
                    f"{currency}"
                    f"{best_buy_price}"
                ),

                "discount_margin": (
                    f"{round(discount_margin, 2)}%"
                ),
            },

            "cash_flow_analysis": {

                "free_cash_flow": (

                    f"{currency}"
                    f"{free_cash_flow:,.0f}"

                    if free_cash_flow
                    else "N/A"
                ),

                "operating_cash_flow": (

                    f"{currency}"
                    f"{operating_cash_flow:,.0f}"

                    if operating_cash_flow
                    else "N/A"
                ),

                "expected_1yr_target": (

                    f"{currency}"
                    f"{dcf_1yr_target}"
                ),

                "expected_3yr_target": (

                    f"{currency}"
                    f"{dcf_3yr_target}"
                ),

                "projected_growth_rate": (

                    f"{round(growth_rate * 100, 2)}%"
                ),
            },

            "ratios": {

                "pe_ratio": (
                    round(pe, 2)
                    if pe
                    else "N/A"
                ),

                "forward_pe": (

                    round(
                        forward_pe,
                        2
                    )

                    if forward_pe
                    else "N/A"
                ),

                "peg_ratio": (

                    round(
                        peg,
                        2
                    )

                    if peg
                    else "N/A"
                ),

                "roe": (
                    f"{round(roe, 2)}%"
                    if roe
                    else "N/A"
                ),
            },
        })


    except Exception as exc:

        app.logger.exception(
            "Analysis error for %s",
            symbol
        )

        return jsonify({

            "status": "error",

            "message": (
                f"Fetch Error for {symbol}: "
                f"{str(exc)}"
            )

        }), 502


# ============================================================
# 6. HEALTH CHECK
# ============================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({

        "status": "ok",

        "service": (
            "Institutional Stock "
            "Valuation Portal"
        )
    })


# ============================================================
# 7. FRONTEND
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>

<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>
        Institutional Valuation Portal
    </title>

    <script src="https://cdn.tailwindcss.com"></script>

    <link
        href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
        rel="stylesheet"
    >

    <style>

        .glass-card {

            background:
                rgba(15, 23, 42, 0.75);

            backdrop-filter:
                blur(16px);

            -webkit-backdrop-filter:
                blur(16px);

            border:
                1px solid
                rgba(255, 255, 255, 0.08);
        }

    </style>

</head>


<body

    class="
        bg-slate-950
        text-slate-100
        min-h-screen
        font-sans
        flex
        flex-col
        justify-between
        bg-fixed
        bg-cover
        bg-center
        relative
    "

    style="
        background-image:
        linear-gradient(
            to bottom,
            rgba(2, 6, 23, 0.88),
            rgba(15, 23, 42, 0.94)
        ),
        url(
            'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1920&auto=format&fit=crop'
        );
    "
>


<div
    class="
        max-w-4xl
        mx-auto
        w-full
        px-4
        pt-8
        md:pt-12
        flex-grow
    "
>


    <!-- HEADER -->

    <div
        class="text-center mb-10"
    >

        <div
            class="
                inline-flex
                items-center
                gap-3
                bg-slate-900/80
                border
                border-emerald-500/30
                px-5
                py-2
                rounded-full
                mb-4
                shadow-xl
                backdrop-blur-md
            "
        >

            <i
                class="
                    fa-solid
                    fa-arrow-trend-up
                    text-emerald-400
                    text-lg
                    animate-pulse
                "
            ></i>


            <span
                class="
                    text-xs
                    md:text-sm
                    font-semibold
                    tracking-wider
                    text-emerald-400
                    uppercase
                "
            >
                Institutional Market Analytics
            </span>

        </div>


        <h1
            class="
                text-3xl
                md:text-5xl
                font-black
                text-white
                tracking-tight
                mb-3
                drop-shadow-md
            "
        >
            STOCK VALUATION & LIQUIDITY PORTAL
        </h1>


        <p
            class="
                text-slate-300
                text-sm
                md:text-base
                font-medium
                max-w-xl
                mx-auto
            "
        >
            Discover Intrinsic Value, Margin of Safety Buy Target &
            Institutional Cash Flow Analysis
        </p>

    </div>



    <!-- SEARCH -->

    <div
        class="relative mb-10"
    >

        <div
            class="relative"
        >

            <input

                type="text"

                id="searchInput"

                placeholder="
                    Search Stock
                    (e.g. Tata Consultancy,
                    Reliance, Apple)...
                "

                class="
                    w-full
                    p-4
                    pl-12
                    rounded-2xl
                    glass-card
                    text-white
                    placeholder-slate-400
                    focus:outline-none
                    focus:ring-2
                    focus:ring-emerald-400/80
                    text-lg
                    shadow-2xl
                    transition-all
                "

                autocomplete="off"
            >


            <i
                class="
                    fa-solid
                    fa-magnifying-glass
                    absolute
                    left-4
                    top-5
                    text-slate-400
                    text-xl
                "
            ></i>

        </div>


        <ul

            id="suggestions"

            class="
                absolute
                left-0
                right-0
                mt-2
                glass-card
                border
                border-slate-700/80
                rounded-2xl
                max-h-64
                overflow-y-auto
                hidden
                z-50
                shadow-2xl
            "

        ></ul>

    </div>



    <!-- LOADER -->

    <div
        id="loader"
        class="
            hidden
            text-center
            my-12
        "
    >

        <div
            class="
                inline-block
                animate-spin
                rounded-full
                h-12
                w-12
                border-t-2
                border-b-2
                border-emerald-400
            "
        ></div>


        <p
            class="
                mt-3
                text-emerald-300
                font-semibold
                tracking-wide
            "
        >
            Evaluating Intrinsic Value & Liquidity Flows...
        </p>

    </div>



    <!-- RESULTS -->

    <div
        id="results"
        class="
            hidden
            space-y-6
            mb-12
        "
    >


        <!-- COMPANY HEADER -->

        <div
            class="
                glass-card
                p-6
                rounded-3xl
                border
                border-slate-700/50
                flex
                flex-col
                md:flex-row
                justify-between
                items-start
                md:items-center
                gap-4
                shadow-2xl
            "
        >

            <div>

                <h2
                    id="companyName"
                    class="
                        text-2xl
                        md:text-3xl
                        font-extrabold
                        text-white
                    "
                ></h2>


                <p
                    id="stockSymbol"
                    class="
                        text-slate-400
                        font-mono
                        text-sm
                        mt-1
                    "
                ></p>

            </div>


            <div
                class="text-left md:text-right"
            >

                <span
                    class="
                        text-xs
                        uppercase
                        tracking-wider
                        text-slate-400
                        block
                        mb-1
                        font-semibold
                    "
                >
                    Current Market Price
                </span>


                <span
                    id="currentPrice"
                    class="
                        text-3xl
                        md:text-4xl
                        font-black
                        text-emerald-400
                        drop-shadow
                    "
                ></span>

            </div>

        </div>



        <!-- STATUS -->

        <div
            id="statusBadgeContainer"
            class="
                p-4
                rounded-2xl
                text-center
                font-extrabold
                text-lg
                shadow-lg
                tracking-wide
            "
        >

            <span
                id="valuationStatus"
            ></span>

        </div>



        <!-- TWO CARDS -->

        <div
            class="
                grid
                grid-cols-1
                md:grid-cols-2
                gap-6
            "
        >


            <!-- VALUATION -->

            <div
                class="
                    glass-card
                    p-6
                    rounded-3xl
                    border
                    border-slate-700/50
                    shadow-xl
                "
            >

                <h3
                    class="
                        text-lg
                        font-bold
                        text-emerald-400
                        mb-4
                        flex
                        items-center
                        gap-2
                    "
                >

                    <i
                        class="fa-solid fa-bullseye"
                    ></i>

                    Valuation Targets

                </h3>


                <div
                    class="space-y-3"
                >

                    <div
                        class="
                            flex
                            justify-between
                            border-b
                            border-slate-800
                            pb-2
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            Intrinsic Value (Graham):
                        </span>


                        <span
                            id="intrinsicVal"
                            class="
                                font-bold
                                text-white
                            "
                        ></span>

                    </div>


                    <div
                        class="
                            flex
                            justify-between
                            border-b
                            border-slate-800
                            pb-2
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            Best Buy Target (20% Disc.):
                        </span>


                        <span
                            id="bestBuyPrice"
                            class="
                                font-bold
                                text-emerald-400
                                text-base
                            "
                        ></span>

                    </div>


                    <div
                        class="
                            flex
                            justify-between
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            Required Margin Discount:
                        </span>


                        <span
                            id="discountMargin"
                            class="
                                font-bold
                                text-amber-400
                            "
                        ></span>

                    </div>

                </div>

            </div>



            <!-- CASH FLOW -->

            <div
                class="
                    glass-card
                    p-6
                    rounded-3xl
                    border
                    border-slate-700/50
                    shadow-xl
                "
            >

                <h3
                    class="
                        text-lg
                        font-bold
                        text-blue-400
                        mb-4
                        flex
                        items-center
                        gap-2
                    "
                >

                    <i
                        class="fa-solid fa-chart-line"
                    ></i>

                    Cash Flow Price Targets

                </h3>


                <div
                    class="space-y-3"
                >

                    <div
                        class="
                            flex
                            justify-between
                            border-b
                            border-slate-800
                            pb-2
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            1-Year Projected Target:
                        </span>


                        <span
                            id="target1Yr"
                            class="
                                font-bold
                                text-blue-400
                            "
                        ></span>

                    </div>


                    <div
                        class="
                            flex
                            justify-between
                            border-b
                            border-slate-800
                            pb-2
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            3-Year Projected Target:
                        </span>


                        <span
                            id="target3Yr"
                            class="
                                font-bold
                                text-indigo-400
                            "
                        ></span>

                    </div>


                    <div
                        class="
                            flex
                            justify-between
                        "
                    >

                        <span
                            class="
                                text-slate-400
                                text-sm
                            "
                        >
                            Annual Free Cash Flow:
                        </span>


                        <span
                            id="freeCashFlow"
                            class="
                                font-bold
                                text-slate-200
                            "
                        ></span>

                    </div>

                </div>

            </div>

        </div>



        <!-- RATIOS -->

        <div
            class="
                glass-card
                p-6
                rounded-3xl
                border
                border-slate-700/50
                shadow-xl
            "
        >

            <h3
                class="
                    text-lg
                    font-bold
                    text-purple-400
                    mb-4
                    flex
                    items-center
                    gap-2
                "
            >

                <i
                    class="fa-solid fa-scale-balanced"
                ></i>

                Core Ratios

            </h3>


            <div
                class="
                    grid
                    grid-cols-2
                    md:grid-cols-4
                    gap-4
                    text-center
                "
            >

                <div
                    class="
                        bg-slate-900/80
                        p-3
                        rounded-2xl
                        border
                        border-slate-800
                    "
                >

                    <p
                        class="
                            text-xs
                            text-slate-400
                            font-medium
                        "
                    >
                        Trailing P/E
                    </p>


                    <p
                        id="peRatio"
                        class="
                            text-lg
                            font-bold
                            text-white
                            mt-1
                        "
                    ></p>

                </div>


                <div
                    class="
                        bg-slate-900/80
                        p-3
                        rounded-2xl
                        border
                        border-slate-800
                    "
                >

                    <p
                        class="
                            text-xs
                            text-slate-400
                            font-medium
                        "
                    >
                        Forward P/E
                    </p>


                    <p
                        id="forwardPe"
                        class="
                            text-lg
                            font-bold
                            text-white
                            mt-1
                        "
                    ></p>

                </div>


                <div
                    class="
                        bg-slate-900/80
                        p-3
                        rounded-2xl
                        border
                        border-slate-800
                    "
                >

                    <p
                        class="
                            text-xs
                            text-slate-400
                            font-medium
                        "
                    >
                        PEG Ratio
                    </p>


                    <p
                        id="pegRatio"
                        class="
                            text-lg
                            font-bold
                            text-white
                            mt-1
                        "
                    ></p>

                </div>


                <div
                    class="
                        bg-slate-900/80
                        p-3
                        rounded-2xl
                        border
                        border-slate-800
                    "
                >

                    <p
                        class="
                            text-xs
                            text-slate-400
                            font-medium
                        "
                    >
                        ROE
                    </p>


                    <p
                        id="roeRatio"
                        class="
                            text-lg
                            font-bold
                            text-white
                            mt-1
                        "
                    ></p>

                </div>

            </div>

        </div>

    </div>

</div>



<!-- FOOTER -->

<footer
    class="
        w-full
        mt-12
        border-t
        border-slate-800/80
        bg-slate-950/90
        backdrop-blur-xl
        py-8
        text-center
        shadow-2xl
    "
>

    <div
        class="
            max-w-4xl
            mx-auto
            px-4
        "
    >

        <h2
            class="
                text-2xl
                md:text-4xl
                font-black
                tracking-widest
                text-transparent
                bg-clip-text
                bg-gradient-to-r
                from-emerald-400
                via-amber-300
                to-yellow-500
                hover:scale-105
                transition-transform
                duration-300
                drop-shadow-xl
            "
        >
            MADE BY DEV SAHOLIYA
        </h2>


        <p
            class="
                text-xs
                text-slate-400
                mt-2
                tracking-wider
                uppercase
                font-semibold
            "
        >
            Institutional Stock Valuation & Algorithmic Analytics Platform
        </p>

    </div>

</footer>



<script>

const searchInput =
    document.getElementById("searchInput");

const suggestions =
    document.getElementById("suggestions");

const loader =
    document.getElementById("loader");

const results =
    document.getElementById("results");


let debounceTimer = null;



// ============================================================
// READ JSON
// ============================================================

async function readJson(response) {

    const text =
        await response.text();

    let data;

    try {

        data = JSON.parse(text);

    } catch (e) {

        throw new Error(
            `Server returned HTTP ${response.status} with invalid JSON.`
        );

    }


    if (!response.ok) {

        throw new Error(
            data.message ||
            `Server error: HTTP ${response.status}`
        );

    }


    return data;
}



// ============================================================
// SEARCH
// ============================================================

searchInput.addEventListener(
    "input",
    (e) => {

        clearTimeout(
            debounceTimer
        );


        const query =
            e.target.value.trim();


        if (query.length < 2) {

            suggestions.classList.add(
                "hidden"
            );

            suggestions.innerHTML = "";

            return;
        }


        debounceTimer =
            setTimeout(
                async () => {

                    try {

                        const response =
                            await fetch(
                                `/api/search?q=${encodeURIComponent(query)}`,
                                {
                                    cache:
                                        "no-store"
                                }
                            );


                        const data =
                            await readJson(
                                response
                            );


                        suggestions.innerHTML =
                            "";


                        if (
                            !Array.isArray(data)
                            ||
                            data.length === 0
                        ) {

                            suggestions.classList.add(
                                "hidden"
                            );

                            return;
                        }


                        data.forEach(
                            (item) => {

                                const li =
                                    document.createElement(
                                        "li"
                                    );


                                li.className =
                                    "p-3 hover:bg-slate-800/90 " +
                                    "cursor-pointer flex " +
                                    "justify-between " +
                                    "items-center border-b " +
                                    "border-slate-800 " +
                                    "last:border-0 " +
                                    "transition-colors";


                                const left =
                                    document.createElement(
                                        "div"
                                    );


                                const nameSpan =
                                    document.createElement(
                                        "span"
                                    );


                                nameSpan.className =
                                    "font-bold text-white";


                                nameSpan.textContent =
                                    item.name ||
                                    item.symbol;


                                const symbolSpan =
                                    document.createElement(
                                        "span"
                                    );


                                symbolSpan.className =
                                    "text-xs text-slate-400 ml-2";


                                symbolSpan.textContent =
                                    `(${item.symbol || ""})`;


                                left.appendChild(
                                    nameSpan
                                );

                                left.appendChild(
                                    symbolSpan
                                );


                                const exchangeSpan =
                                    document.createElement(
                                        "span"
                                    );


                                exchangeSpan.className =
                                    "text-xs bg-slate-900 " +
                                    "text-emerald-400 px-2.5 " +
                                    "py-1 rounded-full " +
                                    "font-semibold border " +
                                    "border-emerald-500/20";


                                exchangeSpan.textContent =
                                    item.exchange ||
                                    item.type ||
                                    "";


                                li.appendChild(
                                    left
                                );

                                li.appendChild(
                                    exchangeSpan
                                );


                                li.addEventListener(
                                    "click",
                                    () => {

                                        selectStock(
                                            item.symbol,
                                            item.name ||
                                            item.symbol
                                        );

                                    }
                                );


                                suggestions.appendChild(
                                    li
                                );

                            }
                        );


                        suggestions.classList.remove(
                            "hidden"
                        );


                    } catch (err) {

                        console.error(
                            "Search error:",
                            err
                        );


                        suggestions.innerHTML =
                            "";


                        const li =
                            document.createElement(
                                "li"
                            );


                        li.className =
                            "p-3 text-rose-300 text-sm";


                        li.textContent =
                            err.message ||
                            "Search failed.";


                        suggestions.appendChild(
                            li
                        );


                        suggestions.classList.remove(
                            "hidden"
                        );

                    }

                },
                350
            );

    }
);



// ============================================================
// SELECT STOCK
// ============================================================

async function selectStock(
    symbol,
    name
) {

    searchInput.value =
        name || symbol;


    suggestions.classList.add(
        "hidden"
    );


    results.classList.add(
        "hidden"
    );


    loader.classList.remove(
        "hidden"
    );


    try {

        const response =
            await fetch(
                `/api/analyze?symbol=${encodeURIComponent(symbol)}`,
                {
                    cache:
                        "no-store"
                }
            );


        const data =
            await readJson(
                response
            );


        if (
            data.status === "error"
        ) {

            throw new Error(
                data.message ||
                "Analysis failed."
            );

        }


        // ====================================================
        // COMPANY
        // ====================================================

        document.getElementById(
            "companyName"
        ).innerText =
            data.company_name;


        document.getElementById(
            "stockSymbol"
        ).innerText =
            data.symbol;


        document.getElementById(
            "currentPrice"
        ).innerText =
            `${data.currency}${data.current_price}`;



        // ====================================================
        // STATUS
        // ====================================================

        const badgeContainer =
            document.getElementById(
                "statusBadgeContainer"
            );


        const badgeText =
            document.getElementById(
                "valuationStatus"
            );


        badgeText.innerText =
            data.valuation.status;


        if (
            data.valuation.status_type
            === "success"
        ) {

            badgeContainer.className =
                "p-4 rounded-2xl text-center " +
                "font-extrabold text-lg " +
                "bg-emerald-950/80 " +
                "text-emerald-300 " +
                "border border-emerald-500/40 " +
                "backdrop-blur-md " +
                "shadow-emerald-950/50";

        }

        else if (
            data.valuation.status_type
            === "danger"
        ) {

            badgeContainer.className =
                "p-4 rounded-2xl text-center " +
                "font-extrabold text-lg " +
                "bg-rose-950/80 " +
                "text-rose-300 " +
                "border border-rose-500/40 " +
                "backdrop-blur-md " +
                "shadow-rose-950/50";

        }

        else {

            badgeContainer.className =
                "p-4 rounded-2xl text-center " +
                "font-extrabold text-lg " +
                "bg-amber-950/80 " +
                "text-amber-300 " +
                "border border-amber-500/40 " +
                "backdrop-blur-md " +
                "shadow-amber-950/50";

        }



        // ====================================================
        // VALUATION
        // ====================================================

        document.getElementById(
            "intrinsicVal"
        ).innerText =
            data.valuation.intrinsic_value;


        document.getElementById(
            "bestBuyPrice"
        ).innerText =
            data.valuation.best_buy_price;


        document.getElementById(
            "discountMargin"
        ).innerText =
            data.valuation.discount_margin;



        // ====================================================
        // CASH FLOW
        // ====================================================

        document.getElementById(
            "target1Yr"
        ).innerText =
            data.cash_flow_analysis
                .expected_1yr_target;


        document.getElementById(
            "target3Yr"
        ).innerText =
            data.cash_flow_analysis
                .expected_3yr_target;


        document.getElementById(
            "freeCashFlow"
        ).innerText =
            data.cash_flow_analysis
                .free_cash_flow;



        // ====================================================
        // RATIOS
        // ====================================================

        document.getElementById(
            "peRatio"
        ).innerText =
            data.ratios.pe_ratio;


        document.getElementById(
            "forwardPe"
        ).innerText =
            data.ratios.forward_pe;


        document.getElementById(
            "pegRatio"
        ).innerText =
            data.ratios.peg_ratio;


        document.getElementById(
            "roeRatio"
        ).innerText =
            data.ratios.roe;



        // ====================================================
        // SHOW RESULTS
        // ====================================================

        results.classList.remove(
            "hidden"
        );


    } catch (err) {

        console.error(
            "Analysis error:",
            err
        );


        alert(
            err.message ||
            "ડેટા ફેચ કરવામાં પ્રોબ્લેમ આવ્યો છે."
        );


    } finally {

        loader.classList.add(
            "hidden"
        );

    }

}



// ============================================================
// CLOSE SEARCH DROPDOWN
// ============================================================

document.addEventListener(
    "click",
    (e) => {

        if (
            !searchInput.contains(e.target)
            &&
            !suggestions.contains(e.target)
        ) {

            suggestions.classList.add(
                "hidden"
            );

        }

    }
);

</script>


</body>

</html>
"""


# ============================================================
# 8. HOME
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML_TEMPLATE
    )


# ============================================================
# 9. ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "status": "error",

        "message": "Endpoint not found."

    }), 404


@app.errorhandler(500)
def internal_error(error):

    app.logger.exception(
        "Internal server error"
    )

    return jsonify({

        "status": "error",

        "message": "Internal server error."

    }), 500


# ============================================================
# 10. RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
