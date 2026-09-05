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

SCANNER_ENDPOINTS = [
    'https://scanner.tradingview.com/india/scan',
    'https://scanner.tradingview.com/america/scan',
    'https://scanner.tradingview.com/global/scan',
]

RECOMMENDATION_WATCHLIST = [
    'NSE:RELIANCE',
    'NSE:TCS',
    'NSE:INFY',
    'NSE:HDFCBANK',
    'NSE:ICICIBANK',
    'NSE:TATAMOTORS',
    'NSE:LT',
    'NSE:BHARTIARTL',
    'NSE:ITC',
    'NSE:SBIN',
    'NSE:AXISBANK',
    'NSE:MARUTI',
    'NSE:SUNPHARMA',
    'NSE:TITAN',
    'NSE:TATASTEEL',
    'NSE:WIPRO',
    'NSE:HCLTECH',
    'NSE:NTPC',
    'NSE:POWERGRID',
    'NSE:COALINDIA',
    'NSE:ONGC',
]


def process_stock_row(row, ticker, name=None):
  price = row[0] or 0
  volume = row[1] or 0
  avg_vol_10 = row[2] or volume or 1
  vwap = row[4] or price
  pe = row[5] or 0
  eps = row[6]
  bvps = row[7]  # Book Value Per Share
  roe = row[8] or 0
  roic = row[9] or 0
  current_ratio = row[12] or 0
  op_margin = row[14] or 0
  net_margin = row[15] or 0
  fcf = row[16] or 0
  pb = row[18] or 0  # Price to Book Ratio
  rsi = row[20] or 50.0
  sma200 = row[22] or price
  market_cap = row[23] or 0
  company_name = name or (row[24] if len(row) > 24 and row[24] else ticker)

  if price == 0:
    return None

  # Auto Recovery for BVPS and P/B
  if (bvps is None or bvps == 0) and pb > 0:
    bvps = round(price / pb, 2)
  elif bvps and (pb == 0 or pb is None):
    pb = round(price / bvps, 2)

  bvps = round(bvps, 2) if bvps else 0
  pb = round(pb, 2) if pb else 0

  if (eps is None or eps == 0) and pe > 0:
    eps = round(price / pe, 2)

  # Intrinsic Valuation Engine
  graham_val = (
      math.sqrt(22.5 * eps * bvps)
      if (eps and eps > 0 and bvps and bvps > 0)
      else None
  )

  dcf_val = None
  if fcf and market_cap and fcf > 0:
    shares = market_cap / price
    fcf_ps = fcf / shares
    dcf_sum = sum([
        (fcf_ps * ((1.12) ** i)) / ((1.105) ** i) for i in range(1, 6)
    ])
    term_val = (fcf_ps * (1.12**5) * 1.04) / (0.105 - 0.04)
    term_pv = term_val / (1.105**5)
    dcf_val = round(dcf_sum + term_pv, 2)
  elif eps and eps > 0:
    dcf_val = round(eps * (8.5 + 2 * 12) * (4.4 / 7.5), 2)

  if dcf_val and graham_val:
    fair_val = round((dcf_val * 0.6) + (graham_val * 0.4), 2)
  elif dcf_val:
    fair_val = dcf_val
  elif graham_val:
    fair_val = round(graham_val, 2)
  else:
    fair_val = round(price * 1.05, 2)

  best_buy = round(fair_val * 0.80, 2)
  rvol = round(volume / avg_vol_10, 2) if avg_vol_10 > 0 else 1.0

  # Composite God-Score Calculation with Book Value Weightage
  score = 45
  if price < best_buy:
    score += 20
  elif price < fair_val:
    score += 12

  # Book Value Discount Scoring Criteria
  if pb > 0 and pb <= 1.0:
    score += 15  # Deep Value: Trading below Book Value
  elif pb > 0 and pb <= 1.8:
    score += 8  # Fair Value relative to Book Assets

  if rvol >= 1.5:
    score += 10
  if price >= vwap:
    score += 5
  if roe > 10:
    score += 8
  if price > sma200:
    score += 5

  master_score = min(max(score, 10), 99)
  discount = round(((fair_val - price) / price) * 100, 2)
  is_undervalued = price < fair_val

  return {
      'ticker': ticker,
      'company_name': company_name,
      'price': round(price, 2),
      'bvps': bvps,
      'pb_ratio': pb,
      'fair_val': fair_val,
      'best_buy': best_buy,
      'master_score': master_score,
      'rvol': rvol,
      'discount': discount,
      'is_undervalued': is_undervalued,
      'is_recommended': (
          master_score >= 70 and (is_undervalued or (pb > 0 and pb <= 1.5))
      ),
  }


@app.route('/api/search', methods=['GET'])
def search_stocks():
  query = request.args.get('q', '').strip()
  if not query or len(query) < 2:
    return jsonify([])

  try:
    url = f'https://symbol-search.tradingview.com/symbol_search/?text={query}'
    res = requests.get(url, headers=HEADERS, timeout=5).json()
    suggestions = []
    for item in res[:10]:
      symbol = item.get('symbol')
      exch = item.get('exchange', '').upper()
      full_symbol = f'{exch}:{symbol}' if exch else symbol
      name = item.get('description') or symbol
      suggestions.append({
          'symbol': full_symbol,
          'name': name,
          'exchange': exch,
      })
    return jsonify(suggestions)
  except Exception:
    return jsonify([])


@app.route('/api/recommendations', methods=['GET'])
def get_recommendations():
  payload = {
      'symbols': {'tickers': RECOMMENDATION_WATCHLIST},
      'columns': [
          'close',
          'volume',
          'average_volume_10_day',
          'average_volume_30_day',
          'VWAP',
          'price_earnings_ttm',
          'earnings_per_share_basic_ttm',
          'book_value_per_share_fq',
          'return_on_equity_fq',
          'return_on_invested_capital_fq',
          'total_debt_fq',
          'total_assets_fq',
          'current_ratio_fq',
          'quick_ratio_fq',
          'operating_margin_ttm',
          'net_profit_margin_ttm',
          'free_cash_flow_ttm',
          'price_earnings_growth_ttm',
          'price_book_fq',
          'beta_1_year',
          'RSI',
          'SMA50',
          'SMA200',
          'market_cap_basic',
          'description',
          'price_52_week_high',
          'price_52_week_low',
      ],
  }

  recommendations = []
  try:
    res = requests.post(
        SCANNER_ENDPOINTS[0], json=payload, headers=HEADERS, timeout=6
    ).json()
    data = res.get('data', [])

    for i, item in enumerate(data):
      row = item.get('d', [])
      ticker = RECOMMENDATION_WATCHLIST[i]
      processed = process_stock_row(row, ticker)
      if processed and processed['is_recommended']:
        recommendations.append(processed)

    recommendations.sort(key=lambda x: x['master_score'], reverse=True)
    return jsonify({'status': 'success', 'data': recommendations})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e), 'data': []})


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
      search_url = f'https://symbol-search.tradingview.com/symbol_search/?text={raw_query}'
      try:
        search_res = requests.get(
            search_url, headers=HEADERS, timeout=5
        ).json()
        if search_res:
          first = search_res[0]
          exchange = first.get('exchange', 'NSE').upper()
          sym = first.get('symbol')
          target_ticker = f'{exchange}:{sym}'
          company_name = first.get('description') or sym
        else:
          target_ticker = f'NSE:{raw_query.upper()}'
      except Exception:
        target_ticker = f'NSE:{raw_query.upper()}'

    payload = {
        'symbols': {'tickers': [target_ticker]},
        'columns': [
            'close',
            'volume',
            'average_volume_10_day',
            'average_volume_30_day',
            'VWAP',
            'price_earnings_ttm',
            'earnings_per_share_basic_ttm',
            'book_value_per_share_fq',
            'return_on_equity_fq',
            'return_on_invested_capital_fq',
            'total_debt_fq',
            'total_assets_fq',
            'current_ratio_fq',
            'quick_ratio_fq',
            'operating_margin_ttm',
            'net_profit_margin_ttm',
            'free_cash_flow_ttm',
            'price_earnings_growth_ttm',
            'price_book_fq',
            'beta_1_year',
            'RSI',
            'SMA50',
            'SMA200',
            'market_cap_basic',
            'description',
            'price_52_week_high',
            'price_52_week_low',
        ],
    }

    data_list = []
    for endpoint in SCANNER_ENDPOINTS:
      try:
        scan_res = requests.post(
            endpoint, json=payload, headers=HEADERS, timeout=5
        ).json()
        if scan_res and scan_res.get('data'):
          data_list = scan_res.get('data')
          break
      except Exception:
        continue

    if not data_list:
      return jsonify({
          'status': 'error',
          'message': f"'{raw_query}' નો ડેટા મળ્યો નથી.",
      })

    row = data_list[0].get('d', [])
    processed = process_stock_row(row, target_ticker, company_name)
    if not processed:
      return jsonify({'status': 'error', 'message': 'ડેટા પ્રોસેસિંગમાં ભૂલ.'})

    price = row[0] or 0
    volume = row[1] or 0
    vwap = row[4] or price
    pe = row[5] or 0
    roe = row[8] or 0
    roic = row[9] or 0
    current_ratio = row[12] or 0
    rsi = row[20] or 50.0
    week_high_52 = row[25] or price * 1.2
    week_low_52 = row[26] or price * 0.8

    currency = '₹' if exchange in ['NSE', 'BSE', 'MCX', 'INDIA'] else '$'

    rvol = processed['rvol']
    order_flow_status = (
        '⚡ SMART MONEY ACCUMULATION'
        if rvol >= 1.5
        else '⚖️ NORMAL VOLUME FLOW'
    )

    vwap_diff = round(((price - vwap) / vwap) * 100, 2)
    vwap_signal = (
        f'BULLISH (+{vwap_diff}% Above VWAP)'
        if price >= vwap
        else f'BEARISH ({vwap_diff}% Below VWAP)'
    )

    dist_to_high = round(((week_high_52 - price) / price) * 100, 2)
    dist_to_low = round(((price - week_low_52) / price) * 100, 2)

    smc_zone = (
        '🔥 NEAR 52W HIGH'
        if dist_to_high <= 5
        else (
            '🛡️ DEMAND ORDER BLOCK (Near 52W Low)'
            if dist_to_low <= 5
            else '🔄 MID-RANGE STRUCTURE'
        )
    )

    z_score = round((current_ratio * 0.8) + (processed['pb_ratio'] * 0.6) + 1.5, 2)
    z_status = 'SAFE ZONE 🟢' if z_score >= 2.99 else 'GREY/DISTRESS ZONE 🟡'

    master_score = processed['master_score']
    if master_score >= 80:
      val_status = 'GOD-LEVEL STRONG BUY 🚀 (Book Value & SMC Aligned)'
      val_type = 'success'
    elif master_score >= 60:
      val_status = 'INSTITUTIONAL ACCUMULATION 🟢'
      val_type = 'success'
    elif master_score >= 40:
      val_status = 'NEUTRAL / HOLD 🟡'
      val_type = 'warning'
    else:
      val_status = 'DISTRIBUTION / SELL 🔴'
      val_type = 'danger'

    return jsonify({
        'status': 'success',
        'symbol': target_ticker,
        'company_name': processed['company_name'],
        'currency': currency,
        'current_price': round(price, 2),
        'bvps': processed['bvps'],
        'pb_ratio': processed['pb_ratio'],
        'master_score': master_score,
        'is_dev_recommended': processed['is_recommended'],
        'order_flow': {
            'rvol': f'{rvol}x',
            'status': order_flow_status,
            'vwap': f'{currency}{round(vwap, 2)}',
            'vwap_signal': vwap_signal,
            'smc_zone': smc_zone,
        },
        'valuation': {
            'status': val_status,
            'status_type': val_type,
            'fair_intrinsic_value': f"{currency}{processed['fair_val']}",
            'best_buy_target': f"{currency}{processed['best_buy']}",
            'discount_margin': f"{processed['discount']}%",
        },
        'health_and_risk': {
            'altman_z_score': z_score,
            'z_status': z_status,
        },
        'profitability': {
            'roe': f'{round(roe, 2)}%' if roe else 'N/A',
            'roic': f'{round(roic, 2)}%' if roic else 'N/A',
        },
        'technical_and_ratios': {
            'pe_ratio': round(pe, 2) if pe else 'N/A',
            'pb_ratio': processed['pb_ratio'],
            'bvps': f"{currency}{processed['bvps']}",
            'rsi': round(rsi, 2),
        },
    })
  except Exception as e:
    return jsonify(
        {'status': 'error', 'message': f'Analysis Exception: {str(e)}'}
    )


# -------------------------------------------------------------------
# FRONTEND UI WITH BOOK VALUE INTELLIGENCE & DEV SAHOLIYA RECOS
# -------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>God-Level Stock Intelligence & Book Value Recommendations</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .glass-card {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .gold-border {
            border: 1px solid rgba(245, 158, 11, 0.5);
            box-shadow: 0 0 20px rgba(245, 158, 11, 0.15);
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans flex flex-col justify-between bg-fixed bg-cover bg-center relative" 
      style="background-image: linear-gradient(to bottom, rgba(2, 6, 23, 0.92), rgba(15, 23, 42, 0.97)), url('https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1920&auto=format&fit=crop');">

    <div class="max-w-5xl mx-auto w-full px-4 pt-8 md:pt-12 flex-grow">
        
        <!-- Header -->
        <div class="text-center mb-8">
            <div class="inline-flex items-center gap-3 bg-slate-900/90 border border-emerald-500/40 px-5 py-2 rounded-full mb-4 shadow-xl backdrop-blur-md">
                <i class="fa-solid fa-crown text-amber-400 text-lg animate-bounce"></i>
                <span class="text-xs md:text-sm font-semibold tracking-wider text-emerald-400 uppercase">God-Level Book Value & SMC Engine</span>
            </div>
            <h1 class="text-3xl md:text-5xl font-black text-white tracking-tight mb-2 drop-shadow-md">
                INSTITUTIONAL STOCK ANALYTICS
            </h1>
            <p class="text-slate-300 text-sm md:text-base font-medium max-w-2xl mx-auto">
                Real-Time Book Value (BVPS) Filter, P/B Ratio, Order Flow & Intrinsic Valuation
            </p>
        </div>

        <!-- Search Bar -->
        <div class="relative mb-8">
            <div class="relative flex gap-2">
                <div class="relative w-full">
                    <input type="text" id="searchInput" placeholder="Search Stock (e.g. Tata Steel, Reliance, Coal India)..." 
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

        <!-- DEV SAHOLIYA RECOMMENDED STOCKS SECTION -->
        <div class="glass-card gold-border p-6 rounded-3xl mb-10 relative overflow-hidden">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6 border-b border-amber-500/20 pb-4">
                <div>
                    <div class="flex items-center gap-2 text-amber-400 font-bold text-sm tracking-wider uppercase mb-1">
                        <i class="fa-solid fa-star text-amber-400"></i> Score 70+ & Book Value Aligned Picks
                    </div>
                    <h2 class="text-xl md:text-2xl font-black text-white">
                        STOCKS RECOMMENDED BY DEV SAHOLIYA
                    </h2>
                    <p class="text-xs text-slate-400">Filtered by Score 70+, Undervalued Status & High Book Value Discount</p>
                </div>
                <button onclick="loadRecommendations()" class="px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 font-bold text-xs rounded-xl transition-all flex items-center gap-2">
                    <i class="fa-solid fa-rotate-right"></i>
                    <span>Scan Market Recommendations</span>
                </button>
            </div>

            <div id="recoLoader" class="hidden text-center py-6">
                <div class="inline-block animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-amber-400"></div>
                <p class="mt-2 text-amber-300 text-xs font-semibold">Scanning High Book Value & Score 70+ Picks...</p>
            </div>

            <div id="recoGrid" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <!-- Dynamic Recommendation Cards Inserted Here -->
            </div>
        </div>

        <!-- Loader -->
        <div id="loader" class="hidden text-center my-12">
            <div class="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400"></div>
            <p class="mt-3 text-emerald-300 font-semibold tracking-wide">Executing Book Value & Institutional Analysis...</p>
        </div>

        <!-- Analysis Results -->
        <div id="results" class="hidden space-y-6 mb-12">
            
            <div id="devBadge" class="hidden glass-card gold-border p-4 rounded-2xl flex items-center gap-4 bg-amber-500/10 text-amber-300 border border-amber-500/40">
                <div class="p-3 bg-amber-500/20 rounded-xl text-amber-400 text-2xl font-black">⭐</div>
                <div>
                    <h4 class="font-black text-base md:text-lg uppercase text-amber-300 tracking-wider">OFFICIAL DEV SAHOLIYA RECOMMENDATION PICK</h4>
                    <p class="text-xs text-slate-300">આ સ્ટોકનો માસ્ટર સ્કોર 70+ છે અને તેની બુક વેલ્યુ (Book Value) અને ડાયરેક્ટ વેલ્યુએશન મજબૂત છે.</p>
                </div>
            </div>

            <!-- Header Card -->
            <div class="glass-card p-6 rounded-3xl border border-slate-700/50 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 shadow-2xl">
                <div>
                    <h2 id="companyName" class="text-2xl md:text-3xl font-extrabold text-white"></h2>
                    <p id="stockSymbol" class="text-slate-400 font-mono text-sm mt-1"></p>
                </div>
                <div class="text-left md:text-right">
                    <span class="text-xs uppercase tracking-wider text-slate-400 block mb-1 font-semibold">Current Price</span>
                    <span id="currentPrice" class="text-3xl md:text-4xl font-black text-emerald-400 drop-shadow"></span>
                </div>
            </div>

            <!-- God Score Banner -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div id="statusBadgeContainer" class="p-6 rounded-3xl text-center md:col-span-2 flex flex-col justify-center items-center shadow-xl border">
                    <span id="valuationStatus" class="text-xl md:text-2xl font-black tracking-wide"></span>
                    <span id="smcZone" class="text-xs font-mono mt-2 px-3 py-1 bg-black/40 rounded-full border border-white/10 text-amber-300"></span>
                </div>

                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 text-center flex flex-col justify-center items-center shadow-xl">
                    <span class="text-xs text-slate-400 uppercase font-bold tracking-wider mb-1">Composite God Score</span>
                    <div class="flex items-baseline gap-1">
                        <span id="masterScore" class="text-5xl font-black text-amber-400"></span>
                        <span class="text-slate-400 font-bold">/100</span>
                    </div>
                </div>
            </div>

            <!-- Valuation & Book Value Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-emerald-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-bullseye"></i> Intrinsic & Book Value Models
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Book Value Per Share (BVPS):</span>
                            <span id="bvpsVal" class="font-bold text-cyan-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Price to Book Ratio (P/B):</span>
                            <span id="pbRatioVal" class="font-bold text-amber-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Combined Fair Value:</span>
                            <span id="fairIntrinsicVal" class="font-bold text-white"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Best Buy Target (20% Disc.):</span>
                            <span id="bestBuyTarget" class="font-bold text-emerald-400"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">Margin Discount:</span>
                            <span id="discountMargin" class="font-bold text-amber-400"></span>
                        </div>
                    </div>
                </div>

                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-purple-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-chart-pie"></i> Financial Ratios & Volume
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Relative Volume (RVOL):</span>
                            <span id="rvolVal" class="font-bold text-emerald-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Return on Equity (ROE):</span>
                            <span id="roeVal" class="font-bold text-white"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">P/E Ratio:</span>
                            <span id="peRatio" class="font-bold text-slate-200"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">RSI (14 Momentum):</span>
                            <span id="rsiVal" class="font-bold text-amber-400"></span>
                        </div>
                    </div>
                </div>

            </div>

        </div>
    </div>

    <!-- Footer -->
    <footer class="w-full mt-12 border-t border-slate-800/80 bg-slate-950/90 backdrop-blur-xl py-8 text-center shadow-2xl">
        <div class="max-w-4xl mx-auto px-4">
            <h2 class="text-2xl md:text-4xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-amber-300 to-yellow-500 hover:scale-105 transition-transform duration-300 drop-shadow-xl">
                MADE BY DEV SAHOLIYA
            </h2>
            <p class="text-xs text-slate-400 mt-2 tracking-wider uppercase font-semibold">God-Level Book Value & OrderFlow Intelligence Portal</p>
        </div>
    </footer>

    <script>
        const searchInput = document.getElementById('searchInput');
        const suggestions = document.getElementById('suggestions');
        const loader = document.getElementById('loader');
        const results = document.getElementById('results');
        const recoGrid = document.getElementById('recoGrid');
        const recoLoader = document.getElementById('recoLoader');

        let debounceTimer;
        let selectedSymbol = '';

        window.addEventListener('DOMContentLoaded', () => {
            loadRecommendations();
        });

        function loadRecommendations() {
            recoGrid.innerHTML = '';
            recoLoader.classList.remove('hidden');

            fetch('/api/recommendations')
                .then(res => res.json())
                .then(data => {
                    recoLoader.classList.add('hidden');
                    if (data.status === 'success' && data.data.length > 0) {
                        data.data.forEach(item => {
                            const card = document.createElement('div');
                            card.className = 'bg-slate-900/90 border border-amber-500/30 p-4 rounded-2xl flex flex-col justify-between hover:border-amber-400 transition-all cursor-pointer group shadow-lg';
                            card.onclick = () => {
                                searchInput.value = item.company_name;
                                fetchStockData(item.ticker);
                            };

                            card.innerHTML = `
                                <div>
                                    <div class="flex justify-between items-start gap-2 mb-2">
                                        <h4 class="font-bold text-white text-base group-hover:text-amber-400 transition-colors">${item.company_name}</h4>
                                        <span class="px-2 py-0.5 bg-amber-500/20 text-amber-300 text-xs font-black rounded-lg border border-amber-500/40">Score ${item.master_score}</span>
                                    </div>
                                    <div class="text-xs text-slate-400 font-mono mb-3">${item.ticker}</div>
                                </div>
                                <div class="border-t border-slate-800 pt-3 flex justify-between items-center text-xs">
                                    <div>
                                        <span class="text-slate-400 block">Price</span>
                                        <span class="font-bold text-white">₹${item.price}</span>
                                    </div>
                                    <div class="text-center">
                                        <span class="text-slate-400 block">Book Value</span>
                                        <span class="font-bold text-cyan-400">₹${item.bvps}</span>
                                    </div>
                                    <div class="text-right">
                                        <span class="text-slate-400 block">P/B Ratio</span>
                                        <span class="font-bold text-amber-400">${item.pb_ratio}x</span>
                                    </div>
                                </div>
                            `;
                            recoGrid.appendChild(card);
                        });
                    } else {
                        recoGrid.innerHTML = '<div class="col-span-3 text-center text-slate-400 py-4 text-xs">હાલમાં કોઈ સ્ટોક રેકમેન્ડેશન ક્રાઈટેરિયામાં મેચ થયો નથી.</div>';
                    }
                })
                .catch(() => {
                    recoLoader.classList.add('hidden');
                    recoGrid.innerHTML = '<div class="col-span-3 text-center text-rose-400 py-4 text-xs">રેકમેન્ડેડ લિસ્ટ લોડ કરવામાં મુશ્કેલી આવી છે.</div>';
                });
        }

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

                    const devBadge = document.getElementById('devBadge');
                    if (data.is_dev_recommended) {
                        devBadge.classList.remove('hidden');
                    } else {
                        devBadge.classList.add('hidden');
                    }

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
                    document.getElementById('smcZone').innerText = data.order_flow.smc_zone;

                    document.getElementById('bvpsVal').innerText = data.technical_and_ratios.bvps;
                    document.getElementById('pbRatioVal').innerText = `${data.technical_and_ratios.pb_ratio}x`;

                    document.getElementById('rvolVal').innerText = data.order_flow.rvol;
                    document.getElementById('fairIntrinsicVal').innerText = data.valuation.fair_intrinsic_value;
                    document.getElementById('bestBuyTarget').innerText = data.valuation.best_buy_target;
                    document.getElementById('discountMargin').innerText = data.valuation.discount_margin;

                    document.getElementById('roeVal').innerText = data.profitability.roe;
                    document.getElementById('peRatio').innerText = data.technical_and_ratios.pe_ratio;
                    document.getElementById('rsiVal').innerText = data.technical_and_ratios.rsi;

                    results.classList.remove('hidden');
                    results.scrollIntoView({ behavior: 'smooth' });
                })
                .catch(err => {
                    loader.classList.add('hidden');
                    alert('ડેટા લોડ કરવામાં મુશ્કેલી આવી છે.');
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
