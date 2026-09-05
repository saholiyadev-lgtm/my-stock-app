import math
import urllib.parse
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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def resolve_to_ticker(query):
  """જો યુઝરે આખું નામ લખ્યું હોય (ઉદા.

  TATA CONSULTANCY SERV LT), તો તેને સાચા Ticker (TCS.NS) માં કન્વર્ટ કરે છે.
  """
  query = query.strip()
  if query.endswith('.NS') or query.endswith('.BO') or len(query.split()) == 1:
    return query

  try:
    encoded_q = urllib.parse.quote(query)
    search_url = f'https://query2.finance.yahoo.com/v1/finance/search?q={encoded_q}&quotesCount=1'
    res = requests.get(search_url, headers=HEADERS, timeout=4)
    data = res.json()
    quotes = data.get('quotes', [])
    if quotes and 'symbol' in quotes[0]:
      return quotes[0]['symbol']
  except Exception:
    pass

  return query


@app.route('/api/search', methods=['GET'])
def search_stocks():
  query = request.args.get('q', '').strip()
  if not query or len(query) < 2:
    return jsonify([])

  try:
    encoded_q = urllib.parse.quote(query)
    url = f'https://query2.finance.yahoo.com/v1/finance/search?q={encoded_q}&quotesCount=8&newsCount=0'
    res = requests.get(url, headers=HEADERS, timeout=5)
    data = res.json()

    suggestions = []
    for quote in data.get('quotes', []):
      symbol = quote.get('symbol')
      name = (
          quote.get('shortname')
          or quote.get('longname')
          or quote.get('symbol')
      )
      exch = quote.get('exchDisp', '')
      if symbol:
        suggestions.append({'symbol': symbol, 'name': name, 'exchange': exch})

    return jsonify(suggestions)
  except Exception:
    return jsonify([])


@app.route('/api/analyze', methods=['GET'])
def analyze():
  raw_symbol = request.args.get('symbol', '').strip()
  if not raw_symbol:
    return jsonify(
        {'status': 'error', 'message': 'સ્ટોકનું નામ અથવા સિમ્બોલ જરૂરી છે.'}
    )

  # Smart Resolution
  symbol = resolve_to_ticker(raw_symbol)

  try:
    quote_url = (
        f'https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}'
    )
    res = requests.get(quote_url, headers=HEADERS, timeout=7)
    q_data = res.json()

    result_list = q_data.get('quoteResponse', {}).get('result', [])

    # Retry fallback if direct search failed for Indian stocks
    if not result_list and not symbol.endswith('.NS'):
      symbol_ns = f'{symbol}.NS'
      quote_url = f'https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol_ns}'
      res = requests.get(quote_url, headers=HEADERS, timeout=7)
      q_data = res.json()
      result_list = q_data.get('quoteResponse', {}).get('result', [])
      if result_list:
        symbol = symbol_ns

    if not result_list:
      return jsonify({
          'status': 'error',
          'message': (
              f"'{raw_symbol}' માટે કોઈ ડેટા મળ્યો નથી. ડ્રોપડાઉનમાંથી સાચો"
              ' સ્ટોક પસંદ કરો.'
          ),
      })

    q = result_list[0]
    current_price = q.get('regularMarketPrice') or q.get('postMarketPrice') or 0

    if current_price == 0:
      return jsonify(
          {'status': 'error', 'message': f'{symbol} નો લાઈવ ભાવ મળ્યો નથી.'}
      )

    currency = (
        '₹'
        if q.get('currency') == 'INR'
        or '.NS' in symbol
        or '.BO' in symbol
        else '$'
    )
    company_name = q.get('longName') or q.get('shortName') or symbol

    eps = q.get('epsTrailingTwelveMonths') or 0
    bvps = q.get('bookValue') or 0
    pe = q.get('trailingPE') or 0
    forward_pe = q.get('forwardPE') or 0
    peg = 0
    free_cash_flow = 0
    operating_cash_flow = 0
    growth_rate = 0.12

    try:
      sum_url = f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=defaultKeyStatistics,financialData'
      sum_res = requests.get(sum_url, headers=HEADERS, timeout=5)
      sum_json = sum_res.json()
      modules = sum_json.get('quoteSummary', {}).get('result', [{}])[0]

      fin_data = modules.get('financialData', {})
      key_stats = modules.get('defaultKeyStatistics', {})

      if 'freeCashflow' in fin_data:
        free_cash_flow = fin_data['freeCashflow'].get('raw', 0)
      if 'operatingCashflow' in fin_data:
        operating_cash_flow = fin_data['operatingCashflow'].get('raw', 0)
      if 'pegRatio' in key_stats:
        peg = key_stats['pegRatio'].get('raw', 0)
      if 'earningsGrowth' in fin_data:
        growth_rate = fin_data['earningsGrowth'].get('raw', 0.12)
    except Exception:
      pass

    roe = (
        q.get('returnOnEquity', 0) * 100
        if q.get('returnOnEquity')
        else (15.0 if pe > 0 else 0)
    )

    graham_val = (
        math.sqrt(22.5 * eps * bvps)
        if (eps and eps > 0 and bvps and bvps > 0)
        else None
    )

    if graham_val:
      best_buy_price = round(graham_val * 0.80, 2)
    elif pe and pe > 30:
      best_buy_price = round(current_price * 0.80, 2)
    else:
      best_buy_price = round(current_price * 0.90, 2)

    dcf_1yr_target = round(current_price * (1 + growth_rate), 2)
    dcf_3yr_target = round(current_price * ((1 + growth_rate) ** 3), 2)

    if graham_val and current_price < (graham_val * 0.85):
      status = 'UNDERVALUED 🟢 (Strong Buying Zone)'
      status_type = 'success'
    elif graham_val and current_price > (graham_val * 1.20):
      status = 'OVERVALUED 🔴 (High Valuation Risk)'
      status_type = 'danger'
    elif peg and 0 < peg < 1:
      status = 'UNDERVALUED 🟢 (Good Growth Potential)'
      status_type = 'success'
    elif pe and pe > 40:
      status = 'OVERVALUED 🔴 (Expensive Stock)'
      status_type = 'danger'
    else:
      status = 'FAIRLY VALUED 🟡 (Fair Price Zone)'
      status_type = 'warning'

    return jsonify({
        'status': 'success',
        'symbol': symbol,
        'company_name': company_name,
        'currency': currency,
        'current_price': round(current_price, 2),
        'valuation': {
            'status': status,
            'status_type': status_type,
            'intrinsic_value': (
                f'{currency}{round(graham_val, 2)}' if graham_val else 'N/A'
            ),
            'best_buy_price': f'{currency}{best_buy_price}',
            'discount_margin': f'{round(((best_buy_price - current_price) / current_price) * 100, 2)}%',
        },
        'cash_flow_analysis': {
            'free_cash_flow': (
                f'{currency}{free_cash_flow:,.0f}'
                if free_cash_flow
                else 'N/A'
            ),
            'operating_cash_flow': (
                f'{currency}{operating_cash_flow:,.0f}'
                if operating_cash_flow
                else 'N/A'
            ),
            'expected_1yr_target': f'{currency}{dcf_1yr_target}',
            'expected_3yr_target': f'{currency}{dcf_3yr_target}',
            'projected_growth_rate': f'{round(growth_rate * 100, 2)}%',
        },
        'ratios': {
            'pe_ratio': round(pe, 2) if pe else 'N/A',
            'forward_pe': round(forward_pe, 2) if forward_pe else 'N/A',
            'peg_ratio': round(peg, 2) if peg else 'N/A',
            'roe': f'{round(roe, 2)}%',
        },
    })
  except Exception as e:
    return jsonify(
        {'status': 'error', 'message': f'ડેટા ફેચિંગ એરર: {str(e)}'}
    )


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Valuation Portal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .glass-card {
            background: rgba(15, 23, 42, 0.78);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans flex flex-col justify-between bg-fixed bg-cover bg-center relative" 
      style="background-image: linear-gradient(to bottom, rgba(2, 6, 23, 0.88), rgba(15, 23, 42, 0.94)), url('https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1920&auto=format&fit=crop');">

    <div class="max-w-4xl mx-auto w-full px-4 pt-8 md:pt-12 flex-grow">
        <div class="text-center mb-10">
            <div class="inline-flex items-center gap-3 bg-slate-900/80 border border-emerald-500/30 px-5 py-2 rounded-full mb-4 shadow-xl backdrop-blur-md">
                <i class="fa-solid fa-arrow-trend-up text-emerald-400 text-lg animate-pulse"></i>
                <span class="text-xs md:text-sm font-semibold tracking-wider text-emerald-400 uppercase">Institutional Market Analytics</span>
            </div>
            <h1 class="text-3xl md:text-5xl font-black text-white tracking-tight mb-3 drop-shadow-md">
                STOCK VALUATION & LIQUIDITY PORTAL
            </h1>
            <p class="text-slate-300 text-sm md:text-base font-medium max-w-xl mx-auto">
                Discover Intrinsic Value, Margin of Safety Buy Target & Institutional Cash Flow Analysis
            </p>
        </div>

        <div class="relative mb-10">
            <div class="relative flex gap-2">
                <div class="relative w-full">
                    <input type="text" id="searchInput" placeholder="Search Stock (e.g. Tata Consultancy, Reliance, Apple)..." 
                           class="w-full p-4 pl-12 rounded-2xl glass-card text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-400/80 text-lg shadow-2xl transition-all"
                           autocomplete="off">
                    <i class="fa-solid fa-magnifying-glass absolute left-4 top-5 text-slate-400 text-xl"></i>
                </div>
                <button onclick="triggerAnalysis()" class="px-6 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold rounded-2xl transition-all flex items-center gap-2 shadow-lg hover:shadow-emerald-500/20">
                    <span>Analyze</span>
                </button>
            </div>
            <ul id="suggestions" class="absolute left-0 right-0 mt-2 glass-card border border-slate-700/80 rounded-2xl max-h-64 overflow-y-auto hidden z-50 shadow-2xl"></ul>
        </div>

        <div id="loader" class="hidden text-center my-12">
            <div class="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400"></div>
            <p class="mt-3 text-emerald-300 font-semibold tracking-wide">Evaluating Intrinsic Value & Liquidity Flows...</p>
        </div>

        <div id="results" class="hidden space-y-6 mb-12">
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

            <div id="statusBadgeContainer" class="p-4 rounded-2xl text-center font-extrabold text-lg shadow-lg tracking-wide">
                <span id="valuationStatus"></span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-emerald-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-bullseye text-emerald-400"></i> Valuation Targets
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Intrinsic Value (Graham):</span>
                            <span id="intrinsicVal" class="font-bold text-white"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">Best Buy Target (20% Disc.):</span>
                            <span id="bestBuyPrice" class="font-bold text-emerald-400 text-base"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">Required Margin Discount:</span>
                            <span id="discountMargin" class="font-bold text-amber-400"></span>
                        </div>
                    </div>
                </div>

                <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                    <h3 class="text-lg font-bold text-blue-400 mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-chart-line text-blue-400"></i> Cash Flow Price Targets
                    </h3>
                    <div class="space-y-3">
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">1-Year Projected Target:</span>
                            <span id="target1Yr" class="font-bold text-blue-400"></span>
                        </div>
                        <div class="flex justify-between border-b border-slate-800 pb-2">
                            <span class="text-slate-400 text-sm">3-Year Projected Target:</span>
                            <span id="target3Yr" class="font-bold text-indigo-400"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400 text-sm">Annual Free Cash Flow:</span>
                            <span id="freeCashFlow" class="font-bold text-slate-200"></span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="glass-card p-6 rounded-3xl border border-slate-700/50 shadow-xl">
                <h3 class="text-lg font-bold text-purple-400 mb-4 flex items-center gap-2">
                    <i class="fa-solid fa-scale-balanced text-purple-400"></i> Core Ratios
                </h3>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">Trailing P/E</p>
                        <p id="peRatio" class="text-lg font-bold text-white mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">Forward P/E</p>
                        <p id="forwardPe" class="text-lg font-bold text-white mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">PEG Ratio</p>
                        <p id="pegRatio" class="text-lg font-bold text-white mt-1"></p>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
                        <p class="text-xs text-slate-400 font-medium">ROE</p>
                        <p id="roeRatio" class="text-lg font-bold text-white mt-1"></p>
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
            <p class="text-xs text-slate-400 mt-2 tracking-wider uppercase font-semibold">Institutional Stock Valuation & Algorithmic Analytics Platform</p>
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
                        badgeContainer.className = 'p-4 rounded-2xl text-center font-extrabold text-lg bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 backdrop-blur-md shadow-emerald-950/50';
                    } else if (data.valuation.status_type === 'danger') {
                        badgeContainer.className = 'p-4 rounded-2xl text-center font-extrabold text-lg bg-rose-950/80 text-rose-300 border border-rose-500/40 backdrop-blur-md shadow-rose-950/50';
                    } else {
                        badgeContainer.className = 'p-4 rounded-2xl text-center font-extrabold text-lg bg-amber-950/80 text-amber-300 border border-amber-500/40 backdrop-blur-md shadow-amber-950/50';
                    }

                    document.getElementById('intrinsicVal').innerText = data.valuation.intrinsic_value;
                    document.getElementById('bestBuyPrice').innerText = data.valuation.best_buy_price;
                    document.getElementById('discountMargin').innerText = data.valuation.discount_margin;

                    document.getElementById('target1Yr').innerText = data.cash_flow_analysis.expected_1yr_target;
                    document.getElementById('target3Yr').innerText = data.cash_flow_analysis.expected_3yr_target;
                    document.getElementById('freeCashFlow').innerText = data.cash_flow_analysis.free_cash_flow;

                    document.getElementById('peRatio').innerText = data.ratios.pe_ratio;
                    document.getElementById('forwardPe').innerText = data.ratios.forward_pe;
                    document.getElementById('pegRatio').innerText = data.ratios.peg_ratio;
                    document.getElementById('roeRatio').innerText = data.ratios.roe;

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
