import math
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Origin': 'https://www.tradingview.com',
    'Referer': 'https://www.tradingview.com/',
}


@app.route('/api/search', methods=['GET'])
def search_stocks():
  query = request.args.get('q', '').strip()
  if not query or len(query) < 2:
    return jsonify([])

  try:
    url = f'https://symbol-search.tradingview.com/symbol_search/?text={query}&type=stock'
    res = requests.get(url, headers=HEADERS, timeout=5)
    data = res.json()

    suggestions = []
    for item in data[:8]:
      symbol = item.get('symbol')
      exch = item.get('exchange', '').upper()
      full_symbol = f'{exch}:{symbol}' if exch else symbol
      name = item.get('description') or symbol

      suggestions.append({
          'symbol': full_symbol,
          'raw_symbol': symbol,
          'name': name,
          'exchange': exch,
      })

    return jsonify(suggestions)
  except Exception:
    return jsonify([])


@app.route('/api/analyze', methods=['GET'])
def analyze():
  raw_query = request.args.get('symbol', '').strip()
  if not raw_query:
    return jsonify(
        {'status': 'error', 'message': 'સ્ટોકનું નામ અથવા સિમ્બોલ જરૂરી છે.'}
    )

  try:
    target_ticker = raw_query
    company_name = raw_query
    exchange = 'NSE'

    if ':' in raw_query:
      parts = raw_query.split(':')
      exchange = parts[0].upper()
      target_ticker = raw_query
    else:
      search_url = f'https://symbol-search.tradingview.com/symbol_search/?text={raw_query}&type=stock'
      search_res = requests.get(search_url, headers=HEADERS, timeout=5).json()
      if search_res:
        first = search_res[0]
        exchange = first.get('exchange', 'NSE').upper()
        sym = first.get('symbol')
        target_ticker = f'{exchange}:{sym}'
        company_name = first.get('description') or sym
      else:
        target_ticker = f'NSE:{raw_query.upper()}'

    # Deep Institutional Indicators Request Payload
    payload = {
        'symbols': {'tickers': [target_ticker]},
        'columns': [
            'close',  # 0
            'price_earnings_ttm',  # 1
            'earnings_per_share_basic_ttm',  # 2
            'book_value_per_share_fq',  # 3
            'return_on_equity_fq',  # 4
            'return_on_invested_capital_fq',  # 5
            'return_on_assets_fq',  # 6
            'total_debt_fq',  # 7
            'total_assets_fq',  # 8
            'current_ratio_fq',  # 9
            'quick_ratio_fq',  # 10
            'operating_margin_ttm',  # 11
            'net_profit_margin_ttm',  # 12
            'free_cash_flow_ttm',  # 13
            'operating_cash_flow_ttm',  # 14
            'price_earnings_growth_ttm',  # 15
            'enterprise_value_ebitda_ttm',  # 16
            'price_book_fq',  # 17
            'price_sales_ttm',  # 18
            'beta_1_year',  # 19
            'RSI',  # 20
            'SMA50',  # 21
            'SMA200',  # 22
            'market_cap_basic',  # 23
            'description',  # 24
        ],
    }

    scanner_url = 'https://scanner.tradingview.com/india/scan'
    scan_res = requests.post(
        scanner_url, json=payload, headers=HEADERS, timeout=6
    ).json()
    data_list = scan_res.get('data', [])

    if not data_list:
      global_scanner_url = 'https://scanner.tradingview.com/global/scan'
      scan_res = requests.post(
          global_scanner_url, json=payload, headers=HEADERS, timeout=6
      ).json()
      data_list = scan_res.get('data', [])

    if not data_list:
      return jsonify({
          'status': 'error',
          'message': (
              f"'{raw_query}' નો ડેટા મળ્યો નથી. ડ્રોપડાઉનમાંથી યોગ્ય સ્ટોક પસંદ"
              ' કરો.'
          ),
      })

    row = data_list[0].get('d', [])

    # Core Variables
    price = row[0] or 0
    pe = row[1] or 0
    eps = row[2]
    bvps = row[3]
    roe = row[4] or 0
    roic = row[5] or 0
    roa = row[6] or 0
    total_debt = row[7] or 0
    total_assets = row[8] or 0
    current_ratio = row[9] or 0
    quick_ratio = row[10] or 0
    op_margin = row[11] or 0
    net_margin = row[12] or 0
    fcf = row[13] or 0
    ocf = row[14] or 0
    peg = row[15] or 0
    ev_ebitda = row[16] or 0
    pb = row[17] or 0
    ps = row[18] or 0
    beta = row[19] or 1.0
    rsi = row[20] or 50.0
    sma50 = row[21] or price
    sma200 = row[22] or price
    market_cap = row[23] or 0
    if len(row) > 24 and row[24]:
      company_name = row[24]

    if price == 0:
      return jsonify(
          {'status': 'error', 'message': f'{target_ticker} નો લાઈવ ભાવ મળ્યો નથી.'}
      )

    # -------------------------------------------------------------
    # 1. SMART FALLBACK & AUTO-RECOVERY ENGINE
    # -------------------------------------------------------------
    if (eps is None or eps == 0) and pe > 0:
      eps = round(price / pe, 2)
    if (bvps is None or bvps == 0) and pb > 0:
      bvps = round(price / pb, 2)
    if roe == 0 and eps and bvps and bvps > 0:
      roe = round((eps / bvps) * 100, 2)
    if roic == 0 and roe > 0:
      roic = round(roe * 0.85, 2)

    currency = '₹' if exchange in ['NSE', 'BSE', 'MCX', 'INDIA'] else '$'

    # -------------------------------------------------------------
    # 2. INSTITUTIONAL VALUATION MODELS
    # -------------------------------------------------------------

    # Model A: Benjamin Graham Formula
    graham_val = None
    if eps and eps > 0 and bvps and bvps > 0:
      graham_val = math.sqrt(22.5 * eps * bvps)

    # Model B: Multi-Stage DCF Intrinsic Model
    dcf_val = None
    discount_rate = 0.105  # WACC 10.5%
    growth_rate = 0.12  # Expected 12% growth
    terminal_growth = 0.04  # Long term inflation rate

    if fcf and market_cap and fcf > 0:
      shares_outstanding = market_cap / price
      fcf_per_share = fcf / shares_outstanding

      dcf_sum = 0
      current_fcf = fcf_per_share
      for i in range(1, 6):
        current_fcf *= 1 + growth_rate
        dcf_sum += current_fcf / ((1 + discount_rate) ** i)

      terminal_val = (current_fcf * (1 + terminal_growth)) / (
          discount_rate - terminal_growth
      )
      terminal_pv = terminal_val / ((1 + discount_rate) ** 5)
      dcf_val = round(dcf_sum + terminal_pv, 2)
    else:
      # Secondary DCF model fallback using EPS
      if eps and eps > 0:
        dcf_val = round(
            eps * (8.5 + 2 * (growth_rate * 100)) * (4.4 / 7.5), 2
        )

    # Combined Intrinsic Target
    if dcf_val and graham_val:
      fair_intrinsic_value = round((dcf_val * 0.6) + (graham_val * 0.4), 2)
    elif dcf_val:
      fair_intrinsic_value = dcf_val
    elif graham_val:
      fair_intrinsic_value = round(graham_val, 2)
    else:
      fair_intrinsic_value = round(price * 1.05, 2)

    best_buy_target = round(fair_intrinsic_value * 0.80, 2)
    discount_margin = round(
        ((best_buy_target - price) / price) * 100, 2
    )

    # -------------------------------------------------------------
    # 3. FINANCIAL HEALTH & RISK ENGINE
    # -------------------------------------------------------------

    # A. Altman Z-Score Bankruptcy Risk Estimation
    z_score = 3.0
    if pb > 0 and current_ratio > 0:
      z_score = round(
          (current_ratio * 0.8)
          + ((net_margin / 100) * 1.4)
          + ((roic / 100) * 3.3)
          + (pb * 0.6),
          2,
      )

    if z_score >= 2.99:
      z_status = 'SAFE ZONE 🟢 (Zero Bankruptcy Risk)'
    elif z_score >= 1.81:
      z_status = 'GREY ZONE 🟡 (Moderate Financial Health)'
    else:
      z_status = 'DISTRESS ZONE 🔴 (High Bankruptcy Risk)'

    # B. Piotroski F-Score (0-9 Score)
    f_score = 0
    if roe > 8:
      f_score += 2
    if roic > 10:
      f_score += 2
    if current_ratio > 1.2:
      f_score += 1
    if op_margin > 12:
      f_score += 2
    if fcf > 0:
      f_score += 2

    # -------------------------------------------------------------
    # 4. INSTITUTIONAL COMPOSITE MASTER SCORE (0 - 100)
    # -------------------------------------------------------------
    score = 50

    # Valuation Score
    if price < best_buy_target:
      score += 25
    elif price < fair_intrinsic_value:
      score += 15
    elif price > fair_intrinsic_value * 1.25:
      score -= 20

    # Health & Profitability Score
    if f_score >= 7:
      score += 15
    elif f_score <= 3:
      score -= 15

    if roic > 15:
      score += 10
    if z_score >= 2.99:
      score += 10

    # Technical Trend Score
    if price > sma200:
      score += 5
    if rsi >= 40 and rsi <= 65:
      score += 5

    master_score = min(max(score, 10), 99)

    if master_score >= 80:
      val_status = 'INSTITUTIONAL STRONG BUY 🚀'
      val_type = 'success'
    elif master_score >= 60:
      val_status = 'UNDERVALUED / BUY 🟢'
      val_type = 'success'
    elif master_score >= 40:
      val_status = 'FAIRLY VALUED / HOLD 🟡'
      val_type = 'warning'
    else:
      val_status = 'OVERVALUED / SELL 🔴'
      val_type = 'danger'

    # Technical Trend Signal
    if price > sma50 and sma50 > sma200:
      trend_signal = 'BULLISH GOLDEN TREND 📈'
    elif price < sma50 and sma50 < sma200:
      trend_signal = 'BEARISH DOWNTREND 📉'
    else:
      trend_signal = 'SIDEWAYS / CONSOLIDATION ⚡'

    return jsonify({
        'status': 'success',
        'symbol': target_ticker,
        'company_name': company_name,
        'currency': currency,
        'current_price': round(price, 2),
        'master_score': master_score,
        'valuation': {
            'status': val_status,
            'status_type': val_type,
            'fair_intrinsic_value': f'{currency}{fair_intrinsic_value}',
            'dcf_valuation': (
                f'{currency}{dcf_val}' if dcf_val else 'N/A'
            ),
            'graham_valuation': (
                f'{currency}{round(graham_val, 2)}' if graham_val else 'N/A'
            ),
            'best_buy_target': f'{currency}{best_buy_target}',
            'discount_margin': f'{discount_margin}%',
        },
        'health_and_risk': {
            'altman_z_score': z_score,
            'z_status': z_status,
            'piotroski_f_score': f'{f_score}/9',
            'current_ratio': round(current_ratio, 2) if current_ratio else 'N/A',
            'quick_ratio': round(quick_ratio, 2) if quick_ratio else 'N/A',
        },
        'profitability': {
            'roe': f'{round(roe, 2)}%' if roe else 'N/A',
            'roic': f'{round(roic, 2)}%' if roic else 'N/A',
            'operating_margin': f'{round(op_margin, 2)}%' if op_margin else 'N/A',
            'net_margin': f'{round(net_margin, 2)}%' if net_margin else 'N/A',
        },
        'technical_and_ratios': {
            'pe_ratio': round(pe, 2) if pe else 'N/A',
            'pb_ratio': round(pb, 2) if pb else 'N/A',
            'peg_ratio': round(peg, 2) if peg else 'N/A',
            'beta': round(beta, 2),
            'rsi': round(rsi, 2),
            'trend_signal': trend_signal,
        },
    })
  except Exception as e:
    return jsonify({
        'status': 'error',
        'message': f'Institutional Engine Error: {str(e)}',
    })


# -------------------------------------------------------------------
# FRONTEND UI (INSTITUTIONAL DASHBOARD)
# -------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Stock Intelligence Portal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .glass-card {
            background: rgba(15, 23, 42, 0.82);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans flex flex-col justify-between bg-fixed bg-cover bg-center relative" 
      style="background-image: linear-gradient(to bottom, rgba(2, 6, 23, 0.90), rgba(15, 23, 42, 0.96)), url('https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1920&auto=format&fit=crop');">

    <div class="max-w-5xl mx-auto w-full px-4 pt-8 md:pt-12 flex-grow">
        
        <div class="text-center mb-10">
            <div class="inline-flex items-center gap-3 bg-slate-900/90 border border-emerald-500/40 px-5 py-2 rounded-full mb-4 shadow-xl backdrop-blur-md">
                <i class="fa-solid fa-building-columns text-emerald-400 text-lg animate-pulse"></i>
                <span class="text-xs md:text-sm font-semibold tracking-wider text-emerald-400 uppercase">Institutional Wall-Street Engine</span>
            </div>
            <h1 class="text-3xl md:text-5xl font-black text-white tracking-tight mb-3 drop-shadow-md">
                STOCK VALUATION & RISK ANALYTICS
            </h1>
            <p class="text-slate-300 text-sm md:text-base font-medium max-w-xl mx-auto">
                DCF Valuation, Altman Bankruptcy Risk, Piotroski Health Score & ROIC Matrix
            </p>
        </div>

        <div class="relative mb-10">
            <div class="relative flex gap-2">
                <div class="relative w-full">
                    <input type="text" id="searchInput" placeholder="Search Stock (e.g. Tata Steel, Reliance, Apple, TCS)..." 
                           class="w-full p-4 pl-12 rounded-2xl glass-card text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-400/80 text-lg shadow-2xl transition-all"
                           autocomplete="off">
                    <i class="fa-solid fa-magnifying-glass absolute left-4 top-5 text-slate-400 text-xl"></i>
                </div>
                <button onclick="triggerAnalysis()" class="px-7 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold rounded-2xl transition-all flex items-center gap-2 shadow-lg hover:shadow-emerald-500/20">
                    <span>Analyze</span>
                </button>
            </div>
            <ul id="suggestions" class="absolute left-0 right-0 mt-2 glass-card border border-slate-700/80 rounded-2xl max-h-64 overflow-y-auto hidden z-50 shadow-2xl"></ul>
        </div>

        <div id="loader" class="hidden text-center my-12">
            <div class="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400"></div>
            <p class="mt-3 text-emerald-300 font-semibold tracking-wide">Executing DCF & Institutional Cash-Flow Simulations...</p>
        </div>

        <div id="results" class="hidden space-y-6 mb-12">
            
            <!-- Header Card -->
            <div class="glass-card p-6 rounded-3xl border border-slate-700/50 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 shadow-2xl">
                <div>
                    <h2 id="companyName" class="text-2xl md:text-3xl font-extrabold text-white"></h2>
                    <p id="stockSymbol" class="text-slate-400 font-mono text-sm mt-1"></p>
                </div>
                <div class="text-left md:text-right">
                    <span class="text-xs uppercase tracking-wider text-slate-400 block mb-1 font-semibold">Current Market Price</span>
                    <span id="currentPrice" class="text-3xl md:text-4xl font-black text-emerald-400 drop-shadow"></span>
                </div>
            </div>

            <!-- Composite Score Banner -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div id="statusBadgeContainer" class="p-6 rounded-3xl text-center md:col-span-2 flex flex-col justify-center items-center shadow-xl border">
                    <span id="valuationStatus" class="text-xl md:text-2xl font-black tracking-wide"></span>
                    <span id="trendSignal" class="text-xs font-mono mt-2 opacity-90 px-3 py-1 bg-black/30 rounded-full border border-white/10"></span>
                </div>

                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 text-center flex flex-col justify-center items-center shadow-xl">
                    <span class="text-xs text-slate-400 uppercase font-bold tracking-wider mb-1">Institutional Rating Score</span>
                    <div class="flex items-baseline gap-1">
                        <span id="masterScore" class="text-5xl font-black text-amber-400"></span>
                        <span class="text-slate-400 font-bold">/100</span>
                    </div>
                </div>
            </div>

            <!-- Valuation Models Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <!-- Intrinsic Valuation Target Card -->
                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-emerald-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-bullseye text-emerald-400"></i> Intrinsic Valuation Models
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Combined Fair Value Target:</span>
                            <span id="fairIntrinsicVal" class="font-bold text-white"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">DCF Model Fair Value:</span>
                            <span id="dcfVal" class="font-bold text-blue-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Graham Growth Model Value:</span>
                            <span id="grahamVal" class="font-bold text-indigo-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Best Buy Target (20% Disc.):</span>
                            <span id="bestBuyTarget" class="font-bold text-emerald-400"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">Margin Discount vs Price:</span>
                            <span id="discountMargin" class="font-bold text-amber-400"></span>
                        </div>
                    </div>
                </div>

                <!-- Financial Health & Risk Assessment Card -->
                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-purple-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-shield-halved text-purple-400"></i> Bankruptcy & Health Matrix
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Altman Z-Score (Bankruptcy):</span>
                            <span id="altmanScore" class="font-bold text-white"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Bankruptcy Risk Status:</span>
                            <span id="altmanStatus" class="font-semibold text-xs text-slate-300"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Piotroski F-Score (Health):</span>
                            <span id="piotroskiScore" class="font-bold text-purple-300"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Current Ratio (Liquidity):</span>
                            <span id="currentRatio" class="font-bold text-slate-200"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">Quick Ratio:</span>
                            <span id="quickRatio" class="font-bold text-slate-200"></span>
                        </div>
                    </div>
                </div>

            </div>

            <!-- Profitability & Efficiency Table -->
            <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                <h3 class="text-lg font-bold text-amber-400 mb-4 flex items-center gap-2">
                    <i class="fa-solid fa-chart-pie text-amber-400"></i> Institutional Profitability & Technical Ratios
                </h3>
                <div class="grid grid-cols-2 md:grid-cols-6 gap-4 text-center">
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">ROIC</p>
                        <p id="roicVal" class="text-base font-bold text-emerald-400 mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">ROE</p>
                        <p id="roeVal" class="text-base font-bold text-white mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">Op Margin</p>
                        <p id="opMarginVal" class="text-base font-bold text-blue-400 mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">P/E Ratio</p>
                        <p id="peRatio" class="text-base font-bold text-white mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">PEG Ratio</p>
                        <p id="pegRatio" class="text-base font-bold text-purple-400 mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">RSI (14)</p>
                        <p id="rsiVal" class="text-base font-bold text-amber-400 mt-1"></p>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <footer class="w-full mt-12 border-t border-slate-800/80 bg-slate-950/90 backdrop-blur-xl py-8 text-center shadow-2xl">
        <div class="max-w-4xl mx-auto px-4">
            <h2 class="text-2xl md:text-4xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-amber-300 to-yellow-500 hover:scale-105 transition-transform duration-300 drop-shadow-xl">
                MADE BY DEV SAHOLIYA
            </h2>
            <p class="text-xs text-slate-400 mt-2 tracking-wider uppercase font-semibold">Institutional Stock Intelligence & DCF Valuation Analytics</p>
        </div>
    </footer>

    <script>
        const searchInput = document.getElementById('searchInput');
        const suggestions = document.getElementById('suggestions');
        const loader = document.getElementById('loader');
        const results = document.getElementById('results');

        let debounceTimer;
        let selectedSymbol = '';

        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            const query = e.target.value.trim();
            selectedSymbol = query;

            if (query.length < 2) {
                suggestions.classList.add('hidden');
                return;
            }

            debounceTimer = setTimeout(() => {
                fetch(`/api/search?q=${encodeURIComponent(query)}`)
                    .then(res => res.json())
                    .then(data => {
                        suggestions.innerHTML = '';
                        if (!data || data.length === 0) {
                            suggestions.classList.add('hidden');
                            return;
                        }
                        data.forEach(item => {
                            const li = document.createElement('li');
                            li.className = 'p-3 hover:bg-slate-800/90 cursor-pointer flex justify-between items-center border-b border-slate-800 last:border-0 transition-colors';
                            li.innerHTML = `<div><span class="font-bold text-white">${item.name}</span> <span class="text-xs text-slate-400 ml-2">(${item.symbol})</span></div><span class="text-xs bg-slate-900 text-emerald-400 px-2.5 py-1 rounded-full font-semibold border border-emerald-500/20">${item.exchange}</span>`;
                            li.onclick = () => selectStock(item.symbol, item.name);
                            suggestions.appendChild(li);
                        });
                        suggestions.classList.remove('hidden');
                    })
                    .catch(() => suggestions.classList.add('hidden'));
            }, 300);
        });

        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                suggestions.classList.add('hidden');
                triggerAnalysis();
            }
        });

        function selectStock(symbol, name) {
            searchInput.value = name;
            selectedSymbol = symbol;
            suggestions.classList.add('hidden');
            fetchStockData(symbol);
        }

        function triggerAnalysis() {
            const query = searchInput.value.trim();
            if (!query) return;
            suggestions.classList.add('hidden');
            fetchStockData(selectedSymbol || query);
        }

        function fetchStockData(query) {
            results.classList.add('hidden');
            loader.classList.remove('hidden');

            fetch(`/api/analyze?symbol=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(data => {
                    loader.classList.add('hidden');
                    if (data.status === 'error') {
                        alert(data.message);
                        return;
                    }

                    document.getElementById('companyName').innerText = data.company_name;
                    document.getElementById('stockSymbol').innerText = data.symbol;
                    document.getElementById('currentPrice').innerText = `${data.currency}${data.current_price}`;

                    const badgeContainer = document.getElementById('statusBadgeContainer');
                    const badgeText = document.getElementById('valuationStatus');
                    badgeText.innerText = data.valuation.status;

                    if (data.valuation.status_type === 'success') {
                        badgeContainer.className = 'p-6 rounded-3xl text-center md:col-span-2 flex flex-col justify-center items-center bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 backdrop-blur-md shadow-emerald-950/50';
                    } else if (data.valuation.status_type === 'danger') {
                        badgeContainer.className = 'p-6 rounded-3xl text-center md:col-span-2 flex flex-col justify-center items-center bg-rose-950/80 text-rose-300 border border-rose-500/40 backdrop-blur-md shadow-rose-950/50';
                    } else {
                        badgeContainer.className = 'p-6 rounded-3xl text-center md:col-span-2 flex flex-col justify-center items-center bg-amber-950/80 text-amber-300 border border-amber-500/40 backdrop-blur-md shadow-amber-950/50';
                    }

                    document.getElementById('masterScore').innerText = data.master_score;
                    document.getElementById('trendSignal').innerText = data.technical_and_ratios.trend_signal;

                    document.getElementById('fairIntrinsicVal').innerText = data.valuation.fair_intrinsic_value;
                    document.getElementById('dcfVal').innerText = data.valuation.dcf_valuation;
                    document.getElementById('grahamVal').innerText = data.valuation.graham_valuation;
                    document.getElementById('bestBuyTarget').innerText = data.valuation.best_buy_target;
                    document.getElementById('discountMargin').innerText = data.valuation.discount_margin;

                    document.getElementById('altmanScore').innerText = data.health_and_risk.altman_z_score;
                    document.getElementById('altmanStatus').innerText = data.health_and_risk.z_status;
                    document.getElementById('piotroskiScore').innerText = data.health_and_risk.piotroski_f_score;
                    document.getElementById('currentRatio').innerText = data.health_and_risk.current_ratio;
                    document.getElementById('quickRatio').innerText = data.health_and_risk.quick_ratio;

                    document.getElementById('roicVal').innerText = data.profitability.roic;
                    document.getElementById('roeVal').innerText = data.profitability.roe;
                    document.getElementById('opMarginVal').innerText = data.profitability.operating_margin;
                    document.getElementById('peRatio').innerText = data.technical_and_ratios.pe_ratio;
                    document.getElementById('pegRatio').innerText = data.technical_and_ratios.peg_ratio;
                    document.getElementById('rsiVal').innerText = data.technical_and_ratios.rsi;

                    results.classList.remove('hidden');
                })
                .catch(err => {
                    loader.classList.add('hidden');
                    alert('ડેટા લોડ કરવામાં મુશ્કેલી આવી છે. કૃપા કરીને ફરી પ્રયાસ કરો.');
                });
        }

        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !suggestions.contains(e.target)) {
                suggestions.classList.add('hidden');
            }
        });
    </script>
</body>
</html>
"""


@app.route('/')
def home():
  return render_template_string(HTML_TEMPLATE)


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000)
