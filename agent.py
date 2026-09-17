"""
AI Trading Signal Agent v2 — 20-Indicator Voting System
========================================================
4 categories · 20 indicators · majority-vote signal engine
If 6+ of 11 core indicators agree → trade signal fires

HOW TO RUN:
  1. pip install -r requirements.txt
  2. cp .env.example .env  →  fill in your API keys
  3. python agent.py
"""

import os, time, json, math, requests
from datetime import datetime
from dotenv import load_dotenv
import anthropic

load_dotenv()

ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY")
ALPHA_VANTAGE    = os.getenv("ALPHA_VANTAGE_API_KEY")
NEWS_API_KEY     = os.getenv("NEWS_API_KEY")
COINGECKO_KEY    = os.getenv("COINGECKO_API_KEY")   # optional but speeds up rate limits
COINGECKO_BASE   = "https://api.coingecko.com/api/v3"

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

ASSETS = [
    {"name": "Bitcoin",  "type": "crypto", "id": "bitcoin",  "symbol": "BTC/USD"},
    {"name": "Ethereum", "type": "crypto", "id": "ethereum", "symbol": "ETH/USD"},
    {"name": "Gold",     "type": "stock",  "id": "GLD",      "symbol": "XAU/USD"},
    {"name": "EUR/USD",  "type": "forex",  "id": "EURUSD",   "symbol": "EUR/USD"},
    {"name": "GBP/USD",  "type": "forex",  "id": "GBPUSD",   "symbol": "GBP/USD"},
    {"name": "S&P 500",  "type": "stock",  "id": "SPY",      "symbol": "SPX"},
]

# ─── Minimum votes needed to fire a signal ───────────────────────────────────
MIN_VOTES_TO_TRADE = 6   # out of max ~20 indicators
# Set higher (e.g. 12) for fewer but higher-quality signals
# Set lower  (e.g. 5)  for more frequent signals


# ═══════════════════════════════════════════════════════════════════════════════
#  MARKET DATA AGENT
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_crypto(coin_id, days=60):
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency":"usd","days":days,"interval":"daily"}
    if COINGECKO_KEY:
        params["x_cg_demo_api_key"] = COINGECKO_KEY
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    d = r.json()
    prices  = [p[1] for p in d["prices"]]
    volumes = [v[1] for v in d["total_volumes"]]
    highs   = [p * 1.005 for p in prices]   # approximated from daily close
    lows    = [p * 0.995 for p in prices]
    return {"prices": prices, "highs": highs, "lows": lows, "volumes": volumes}

def fetch_forex(symbol, days=60):
    url = "https://www.alphavantage.co/query"
    p = {"function":"FX_DAILY","from_symbol":symbol[:3],"to_symbol":symbol[3:],
         "apikey":ALPHA_VANTAGE,"outputsize":"full"}
    for attempt in range(2):
        try:
            r = requests.get(url, params=p, timeout=15)
            r.raise_for_status()
            data = r.json()
            if "Note" in data or "Information" in data:
                print(f"  [!] Alpha Vantage rate limit hit. Free tier = 25 calls/day.")
                return None
            series = data.get("Time Series FX (Daily)", {})
            if not series: return None
            dates  = sorted(series.keys(), reverse=True)[:days]
            closes  = [float(series[d]["4. close"]) for d in dates]
            highs   = [float(series[d]["2. high"])  for d in dates]
            lows    = [float(series[d]["3. low"])   for d in dates]
            volumes = [0] * len(closes)
            return {"prices": list(reversed(closes)), "highs": list(reversed(highs)),
                    "lows": list(reversed(lows)),     "volumes": volumes}
        except Exception as e:
            print(f"  [!] Forex fetch error ({symbol}): {e}")
            time.sleep(3)
    return None

def fetch_stock(symbol, days=60):
    url = "https://www.alphavantage.co/query"
    p = {"function":"TIME_SERIES_DAILY","symbol":symbol,"apikey":ALPHA_VANTAGE,"outputsize":"full"}
    for attempt in range(2):
        try:
            r = requests.get(url, params=p, timeout=15)
            r.raise_for_status()
            data = r.json()
            if "Note" in data or "Information" in data:
                print(f"  [!] Alpha Vantage rate limit hit. Free tier = 25 calls/day.")
                return None
            series = data.get("Time Series (Daily)", {})
            if not series: return None
            dates  = sorted(series.keys(), reverse=True)[:days]
            closes  = [float(series[d]["4. close"])  for d in dates]
            highs   = [float(series[d]["2. high"])   for d in dates]
            lows    = [float(series[d]["3. low"])    for d in dates]
            volumes = [float(series[d]["5. volume"]) for d in dates]
            return {"prices": list(reversed(closes)), "highs": list(reversed(highs)),
                    "lows": list(reversed(lows)),     "volumes": volumes}
        except Exception as e:
            print(f"  [!] Stock fetch error ({symbol}): {e}")
            time.sleep(3)
    return None

def get_market_data(asset):
    try:
        if asset["type"] == "crypto": return fetch_crypto(asset["id"])
        elif asset["type"] == "forex": return fetch_forex(asset["id"])
        else: return fetch_stock(asset["id"])
    except Exception as e:
        print(f"  [!] Data fetch error ({asset['name']}): {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  MATH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sma(data, period):
    if len(data) < period: return None
    return sum(data[-period:]) / period

def ema(data, period):
    if len(data) < period: return None
    k, e = 2/(period+1), sum(data[:period])/period
    for p in data[period:]: e = p*k + e*(1-k)
    return e

def stdev(data, period):
    if len(data) < period: return None
    s = data[-period:]
    m = sum(s)/period
    return math.sqrt(sum((x-m)**2 for x in s)/period)

def true_range(highs, lows, closes):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return trs

def vote(name, signal, reason=""):
    """Helper to create a single indicator vote dict."""
    return {"name": name, "signal": signal, "reason": reason}


# ═══════════════════════════════════════════════════════════════════════════════
#  CATEGORY 1 — TREND INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def ind_moving_averages(prices):
    """SMA 20/50 + EMA 12/26 cross."""
    votes = []
    p = prices
    e12, e26 = ema(p, 12), ema(p, 26)
    s20, s50 = sma(p, 20), sma(p, 50)
    cur = p[-1]

    if e12 and e26:
        sig = "BUY" if e12 > e26 else "SELL"
        votes.append(vote("EMA Cross (12/26)", sig,
                          f"EMA12={e12:.4f} {'>' if e12>e26 else '<'} EMA26={e26:.4f}"))
    if s20 and s50:
        sig = "BUY" if s20 > s50 else "SELL"
        votes.append(vote("SMA Cross (20/50)", sig,
                          f"SMA20={s20:.4f} {'>' if s20>s50 else '<'} SMA50={s50:.4f}"))
    if s20:
        sig = "BUY" if cur > s20 else "SELL"
        votes.append(vote("Price vs SMA20", sig,
                          f"Price={cur:.4f} {'above' if cur>s20 else 'below'} SMA20"))
    return votes

def ind_ichimoku(prices, highs, lows):
    """Ichimoku Cloud — Tenkan/Kijun cross + price vs cloud."""
    def midpoint(h, l): return (max(h)+min(l))/2

    def ichi_line(h, l, n):
        if len(h) < n: return None
        return midpoint(h[-n:], l[-n:])

    tenkan = ichi_line(highs, lows, 9)
    kijun  = ichi_line(highs, lows, 26)
    span_a = (tenkan + kijun) / 2 if tenkan and kijun else None
    span_b = ichi_line(highs, lows, 52)
    cur = prices[-1]

    votes_out = []
    if tenkan and kijun:
        sig = "BUY" if tenkan > kijun else "SELL"
        votes_out.append(vote("Ichimoku TK Cross", sig,
                              f"Tenkan={tenkan:.4f} {'>' if tenkan>kijun else '<'} Kijun={kijun:.4f}"))
    if span_a and span_b:
        cloud_top = max(span_a, span_b)
        cloud_bot = min(span_a, span_b)
        if cur > cloud_top:
            votes_out.append(vote("Ichimoku Cloud", "BUY",  f"Price above cloud ({cloud_bot:.4f}–{cloud_top:.4f})"))
        elif cur < cloud_bot:
            votes_out.append(vote("Ichimoku Cloud", "SELL", f"Price below cloud ({cloud_bot:.4f}–{cloud_top:.4f})"))
        else:
            votes_out.append(vote("Ichimoku Cloud", "WAIT", "Price inside cloud — neutral zone"))
    return votes_out

def ind_adx(highs, lows, closes, period=14):
    """ADX — measures trend strength. Above 25 = trending."""
    if len(closes) < period+2:
        return [vote("ADX", "WAIT", "Insufficient data")]
    trs = true_range(highs, lows, closes)
    plus_dm, minus_dm = [], []
    for i in range(1, len(closes)):
        up   = highs[i]   - highs[i-1]
        down = lows[i-1]  - lows[i]
        plus_dm.append(up   if up > down and up > 0   else 0)
        minus_dm.append(down if down > up and down > 0 else 0)

    atr14    = sum(trs[-period:]) / period
    plus_di  = 100 * (sum(plus_dm[-period:])  / period) / atr14 if atr14 else 0
    minus_di = 100 * (sum(minus_dm[-period:]) / period) / atr14 if atr14 else 0
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di+minus_di) else 0
    adx_val = dx   # simplified single-period

    trending = adx_val > 25
    if trending and plus_di > minus_di:
        sig, reason = "BUY",  f"ADX={adx_val:.1f} (strong trend) +DI>{'-'}DI"
    elif trending and minus_di > plus_di:
        sig, reason = "SELL", f"ADX={adx_val:.1f} (strong trend) -DI>+DI"
    else:
        sig, reason = "WAIT", f"ADX={adx_val:.1f} (<25, no clear trend)"
    return [vote("ADX", sig, reason)]

def ind_parabolic_sar(highs, lows, closes, af_start=0.02, af_max=0.2):
    """Parabolic SAR — trend direction + reversal signals."""
    if len(closes) < 5:
        return [vote("Parabolic SAR", "WAIT", "Insufficient data")]
    bull = closes[1] > closes[0]
    sar  = lows[0]  if bull else highs[0]
    ep   = highs[0] if bull else lows[0]
    af   = af_start

    for i in range(1, len(closes)):
        prev_sar = sar
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, lows[i-1], lows[max(0,i-2)])
            if closes[i] < sar:
                bull, sar, ep, af = False, ep, lows[i], af_start
            else:
                if highs[i] > ep: ep = highs[i]; af = min(af+af_start, af_max)
        else:
            sar = max(sar, highs[i-1], highs[max(0,i-2)])
            if closes[i] > sar:
                bull, sar, ep, af = True, ep, highs[i], af_start
            else:
                if lows[i] < ep: ep = lows[i]; af = min(af+af_start, af_max)

    cur = closes[-1]
    sig = "BUY" if bull else "SELL"
    return [vote("Parabolic SAR", sig,
                 f"SAR={sar:.4f} {'below' if bull else 'above'} price={cur:.4f}")]

def ind_supertrend(highs, lows, closes, period=10, multiplier=3):
    """Supertrend indicator — ATR-based trend with clear buy/sell."""
    if len(closes) < period+2:
        return [vote("Supertrend", "WAIT", "Insufficient data")]
    trs = true_range(highs, lows, closes)
    atr_vals = []
    atr = sum(trs[:period]) / period
    atr_vals.append(atr)
    for tr in trs[period:]:
        atr = (atr * (period-1) + tr) / period
        atr_vals.append(atr)

    up_band, dn_band, supertrend_line = [], [], []
    trend_up = True
    for i in range(len(atr_vals)):
        idx = i + period
        if idx >= len(closes): break
        hl2 = (highs[idx] + lows[idx]) / 2
        ub  = hl2 + multiplier * atr_vals[i]
        db  = hl2 - multiplier * atr_vals[i]
        if i == 0:
            up_band.append(ub); dn_band.append(db)
            supertrend_line.append(db if trend_up else ub)
            continue
        ub = min(ub, up_band[-1]) if closes[idx-1] <= up_band[-1] else ub
        db = max(db, dn_band[-1]) if closes[idx-1] >= dn_band[-1] else db
        up_band.append(ub); dn_band.append(db)
        if trend_up:
            if closes[idx] < dn_band[-1]: trend_up = False
        else:
            if closes[idx] > up_band[-1]: trend_up = True
        supertrend_line.append(dn_band[-1] if trend_up else up_band[-1])

    sig = "BUY" if trend_up else "SELL"
    st_val = supertrend_line[-1] if supertrend_line else 0
    return [vote("Supertrend", sig,
                 f"ST={st_val:.4f}, price {'above' if trend_up else 'below'} supertrend")]


# ═══════════════════════════════════════════════════════════════════════════════
#  CATEGORY 2 — MOMENTUM INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def ind_rsi(prices, period=14):
    """RSI — oversold (<30=BUY) / overbought (>70=SELL)."""
    if len(prices) < period+1:
        return [vote("RSI", "WAIT", "Insufficient data")]
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    ag = sum(gains[-period:])/period  if gains  else 0
    al = sum(losses[-period:])/period if losses else 0.001
    rsi_val = round(100 - (100/(1 + ag/al)), 1)

    if rsi_val < 30:   sig, r = "BUY",  f"RSI={rsi_val} — oversold"
    elif rsi_val > 70: sig, r = "SELL", f"RSI={rsi_val} — overbought"
    elif rsi_val < 45: sig, r = "BUY",  f"RSI={rsi_val} — bullish momentum building"
    elif rsi_val > 58: sig, r = "SELL", f"RSI={rsi_val} — bearish pressure"
    else:              sig, r = "WAIT", f"RSI={rsi_val} — neutral zone"
    return [vote("RSI (14)", sig, r)]

def ind_macd(prices):
    """MACD line cross + histogram direction."""
    if len(prices) < 27:
        return [vote("MACD", "WAIT", "Insufficient data")]
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    macd_val = e12 - e26

    # Build MACD history for signal line
    macd_hist = []
    for i in range(26, len(prices)):
        e12i = ema(prices[:i+1], 12)
        e26i = ema(prices[:i+1], 26)
        if e12i and e26i: macd_hist.append(e12i - e26i)

    signal_line = ema(macd_hist, 9) if len(macd_hist) >= 9 else None
    histogram   = macd_val - signal_line if signal_line else None

    votes_out = []
    if signal_line:
        sig = "BUY" if macd_val > signal_line else "SELL"
        votes_out.append(vote("MACD Signal Cross", sig,
                              f"MACD={macd_val:.6f} {'>' if macd_val>signal_line else '<'} Signal={signal_line:.6f}"))
    if histogram is not None:
        sig = "BUY" if histogram > 0 else "SELL"
        votes_out.append(vote("MACD Histogram", sig,
                              f"Histogram={'positive' if histogram>0 else 'negative'} ({histogram:.6f})"))
    return votes_out

def ind_stochastic(highs, lows, closes, k_period=14, d_period=3):
    """Stochastic Oscillator %K/%D cross."""
    if len(closes) < k_period:
        return [vote("Stochastic", "WAIT", "Insufficient data")]
    k_vals = []
    for i in range(k_period-1, len(closes)):
        h = max(highs[i-k_period+1:i+1])
        l = min(lows[i-k_period+1:i+1])
        k = 100*(closes[i]-l)/(h-l) if h!=l else 50
        k_vals.append(k)
    d_vals = [sum(k_vals[i:i+d_period])/d_period for i in range(len(k_vals)-d_period+1)]

    k, d = k_vals[-1], d_vals[-1]
    if k < 20 and k > d:   sig, r = "BUY",  f"%K={k:.1f} oversold, crossing up"
    elif k > 80 and k < d: sig, r = "SELL", f"%K={k:.1f} overbought, crossing down"
    elif k > d:            sig, r = "BUY",  f"%K={k:.1f} above %D={d:.1f}"
    else:                  sig, r = "SELL", f"%K={k:.1f} below %D={d:.1f}"
    return [vote("Stochastic (%K/%D)", sig, r)]

def ind_williams_r(highs, lows, closes, period=14):
    """Williams %R — similar to Stochastic, -80 to -100 = oversold."""
    if len(closes) < period:
        return [vote("Williams %R", "WAIT", "Insufficient data")]
    h = max(highs[-period:])
    l = min(lows[-period:])
    wr = -100*(h-closes[-1])/(h-l) if h!=l else -50

    if wr < -80:  sig, r = "BUY",  f"%R={wr:.1f} — oversold"
    elif wr > -20:sig, r = "SELL", f"%R={wr:.1f} — overbought"
    else:         sig, r = "WAIT", f"%R={wr:.1f} — neutral"
    return [vote("Williams %R", sig, r)]

def ind_mfi(highs, lows, closes, volumes, period=14):
    """Money Flow Index — RSI incorporating volume."""
    if len(closes) < period+1 or not any(volumes):
        return [vote("MFI", "WAIT", "No volume data or insufficient")]
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    raw_mf = [tp[i]*volumes[i] for i in range(len(closes))]
    pos_mf = sum(raw_mf[i] for i in range(1, period+1) if tp[i] > tp[i-1])
    neg_mf = sum(raw_mf[i] for i in range(1, period+1) if tp[i] < tp[i-1])
    mfi_val = 100 - (100/(1 + pos_mf/neg_mf)) if neg_mf else 100

    if mfi_val < 20:  sig, r = "BUY",  f"MFI={mfi_val:.1f} — oversold with volume"
    elif mfi_val > 80:sig, r = "SELL", f"MFI={mfi_val:.1f} — overbought with volume"
    else:             sig, r = "WAIT", f"MFI={mfi_val:.1f} — neutral"
    return [vote("MFI (Money Flow Index)", sig, r)]


# ═══════════════════════════════════════════════════════════════════════════════
#  CATEGORY 3 — VOLATILITY INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def ind_bollinger_bands(prices, period=20, num_std=2):
    """Bollinger Bands — price at lower band = BUY, upper = SELL."""
    if len(prices) < period:
        return [vote("Bollinger Bands", "WAIT", "Insufficient data")]
    mid  = sma(prices, period)
    sd   = stdev(prices, period)
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    cur   = prices[-1]
    bw    = (upper - lower) / mid * 100  # bandwidth %

    if cur <= lower:   sig, r = "BUY",  f"Price={cur:.4f} at/below lower band={lower:.4f}"
    elif cur >= upper: sig, r = "SELL", f"Price={cur:.4f} at/above upper band={upper:.4f}"
    elif cur < mid:    sig, r = "BUY",  f"Price={cur:.4f} below midband={mid:.4f}"
    else:              sig, r = "SELL", f"Price={cur:.4f} above midband={mid:.4f}"
    return [vote("Bollinger Bands", sig, r)]

def ind_atr(highs, lows, closes, period=14):
    """ATR — high ATR = volatile (caution), used for SL sizing."""
    if len(closes) < period+1:
        return [vote("ATR", "WAIT", "Insufficient data")]
    trs  = true_range(highs, lows, closes)
    atr_val = sum(trs[-period:]) / period
    pct  = atr_val / closes[-1] * 100
    # ATR itself is neutral — but extreme volatility = caution
    if pct > 5:   sig, r = "WAIT", f"ATR={atr_val:.4f} ({pct:.1f}%) — very high volatility, caution"
    elif pct > 2: sig, r = "WAIT", f"ATR={atr_val:.4f} ({pct:.1f}%) — moderate volatility"
    else:         sig, r = "BUY",  f"ATR={atr_val:.4f} ({pct:.1f}%) — low volatility, stable"
    return [vote("ATR (Volatility)", sig, r)]

def ind_keltner_channels(highs, lows, closes, period=20, multiplier=2):
    """Keltner Channels — similar to BBands but uses ATR."""
    if len(closes) < period+2:
        return [vote("Keltner Channels", "WAIT", "Insufficient data")]
    mid   = ema(closes, period)
    trs   = true_range(highs, lows, closes)
    atr_v = sum(trs[-period:]) / period
    upper = mid + multiplier * atr_v
    lower = mid - multiplier * atr_v
    cur   = closes[-1]

    if cur < lower:  sig, r = "BUY",  f"Price={cur:.4f} below KC lower={lower:.4f}"
    elif cur > upper:sig, r = "SELL", f"Price={cur:.4f} above KC upper={upper:.4f}"
    elif cur < mid:  sig, r = "BUY",  f"Price below KC midline"
    else:            sig, r = "SELL", f"Price above KC midline"
    return [vote("Keltner Channels", sig, r)]


# ═══════════════════════════════════════════════════════════════════════════════
#  CATEGORY 4 — VOLUME INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def ind_obv(closes, volumes):
    """On-Balance Volume — rising OBV = buying pressure."""
    if not any(volumes):
        return [vote("OBV", "WAIT", "No volume data")]
    obv = 0
    obv_series = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:   obv += volumes[i]
        elif closes[i] < closes[i-1]: obv -= volumes[i]
        obv_series.append(obv)
    # Compare recent OBV trend vs price trend
    obv_slope   = obv_series[-1] - obv_series[-5]
    price_slope = closes[-1] - closes[-5]
    if obv_slope > 0 and price_slope > 0:  sig, r = "BUY",  f"OBV rising with price — confirmed"
    elif obv_slope > 0 and price_slope <= 0:sig,r = "BUY",  f"OBV rising despite price fall — bullish divergence"
    elif obv_slope < 0 and price_slope < 0:sig, r = "SELL", f"OBV falling with price — confirmed"
    else:                                  sig, r = "SELL", f"OBV falling despite price rise — bearish divergence"
    return [vote("OBV (On-Balance Volume)", sig, r)]

def ind_vwap(highs, lows, closes, volumes):
    """VWAP — price above VWAP = bullish bias."""
    if not any(volumes):
        return [vote("VWAP", "WAIT", "No volume data")]
    tp   = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    cumv = sum(volumes)
    cumtpv = sum(tp[i]*volumes[i] for i in range(len(closes)))
    vwap_val = cumtpv / cumv if cumv else closes[-1]
    cur = closes[-1]
    sig = "BUY" if cur > vwap_val else "SELL"
    r   = f"Price={cur:.4f} {'above' if cur>vwap_val else 'below'} VWAP={vwap_val:.4f}"
    return [vote("VWAP", sig, r)]

def ind_accumulation_distribution(highs, lows, closes, volumes):
    """A/D Line — money flow confirmation indicator."""
    if not any(volumes):
        return [vote("A/D Line", "WAIT", "No volume data")]
    ad, ad_series = 0, []
    for i in range(len(closes)):
        hl = highs[i] - lows[i]
        clv = ((closes[i]-lows[i]) - (highs[i]-closes[i])) / hl if hl != 0 else 0
        ad += clv * volumes[i]
        ad_series.append(ad)
    slope = ad_series[-1] - ad_series[-5]
    sig = "BUY" if slope > 0 else "SELL"
    r   = f"A/D {'rising' if slope>0 else 'falling'} — {'accumulation' if slope>0 else 'distribution'}"
    return [vote("A/D Line", sig, r)]

def ind_chaikin_mf(highs, lows, closes, volumes, period=20):
    """Chaikin Money Flow — positive = bullish, negative = bearish."""
    if not any(volumes) or len(closes) < period:
        return [vote("Chaikin MF", "WAIT", "No volume data or insufficient")]
    clvs = []
    for i in range(len(closes)):
        hl = highs[i] - lows[i]
        clv = ((closes[i]-lows[i]) - (highs[i]-closes[i])) / hl if hl != 0 else 0
        clvs.append(clv * volumes[i])
    cmf = sum(clvs[-period:]) / sum(volumes[-period:]) if sum(volumes[-period:]) else 0
    if cmf > 0.1:   sig, r = "BUY",  f"CMF={cmf:.3f} — strong money inflow"
    elif cmf < -0.1:sig, r = "SELL", f"CMF={cmf:.3f} — strong money outflow"
    elif cmf > 0:   sig, r = "BUY",  f"CMF={cmf:.3f} — slight inflow"
    else:           sig, r = "SELL", f"CMF={cmf:.3f} — slight outflow"
    return [vote("Chaikin Money Flow", sig, r)]


# ═══════════════════════════════════════════════════════════════════════════════
#  THE VOTING ENGINE — runs all 20 indicators, tallies the vote
# ═══════════════════════════════════════════════════════════════════════════════

def run_all_indicators(md):
    """Run every indicator and return a list of individual votes."""
    p = md["prices"]; h = md["highs"]; l = md["lows"]; v = md["volumes"]
    all_votes = []

    # ── Category 1: Trend ────────────────────────────────────────────────────
    all_votes += ind_moving_averages(p)
    all_votes += ind_ichimoku(h, l, p)
    all_votes += ind_adx(h, l, p)
    all_votes += ind_parabolic_sar(h, l, p)
    all_votes += ind_supertrend(h, l, p)

    # ── Category 2: Momentum ─────────────────────────────────────────────────
    all_votes += ind_rsi(p)
    all_votes += ind_macd(p)
    all_votes += ind_stochastic(h, l, p)
    all_votes += ind_williams_r(h, l, p)
    all_votes += ind_mfi(h, l, p, v)

    # ── Category 3: Volatility ───────────────────────────────────────────────
    all_votes += ind_bollinger_bands(p)
    all_votes += ind_atr(h, l, p)
    all_votes += ind_keltner_channels(h, l, p)

    # ── Category 4: Volume ───────────────────────────────────────────────────
    all_votes += ind_obv(p, v)
    all_votes += ind_vwap(h, l, p, v)
    all_votes += ind_accumulation_distribution(h, l, p, v)
    all_votes += ind_chaikin_mf(h, l, p, v)

    return all_votes

def tally_votes(all_votes):
    """Count votes and produce final majority signal."""
    buy  = [v for v in all_votes if v["signal"] == "BUY"]
    sell = [v for v in all_votes if v["signal"] == "SELL"]
    wait = [v for v in all_votes if v["signal"] == "WAIT"]
    total = len(all_votes)

    buy_count  = len(buy)
    sell_count = len(sell)
    wait_count = len(wait)

    if buy_count >= MIN_VOTES_TO_TRADE and buy_count > sell_count:
        final = "BUY"
        confidence = round(buy_count / total * 100)
    elif sell_count >= MIN_VOTES_TO_TRADE and sell_count > buy_count:
        final = "SELL"
        confidence = round(sell_count / total * 100)
    else:
        final = "WAIT"
        confidence = round(max(buy_count, sell_count) / total * 100)

    return {
        "signal":     final,
        "confidence": confidence,
        "buy_votes":  buy_count,
        "sell_votes": sell_count,
        "wait_votes": wait_count,
        "total":      total,
        "detail":     all_votes,
        "threshold":  MIN_VOTES_TO_TRADE,
    }

def calc_levels(md, signal):
    """Calculate entry, stop-loss, and take-profit from ATR."""
    p = md["prices"]; h = md["highs"]; l = md["lows"]
    trs = true_range(h, l, p)
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else abs(p[-1] - p[-2])
    cur = p[-1]

    if signal == "BUY":
        entry  = round(cur * 1.001, 4)
        sl     = round(cur - atr * 1.5, 4)
        tp1    = round(cur + atr * 2.0, 4)
        tp2    = round(cur + atr * 3.5, 4)
    elif signal == "SELL":
        entry  = round(cur * 0.999, 4)
        sl     = round(cur + atr * 1.5, 4)
        tp1    = round(cur - atr * 2.0, 4)
        tp2    = round(cur - atr * 3.5, 4)
    else:
        return {}

    risk   = abs(entry - sl)
    reward = abs(tp1 - entry)
    rr = f"1:{round(reward/risk, 1)}" if risk > 0 else "N/A"
    return {"entry": entry, "stop_loss": sl, "target1": tp1,
            "target2": tp2, "risk_reward": rr, "atr": round(atr, 4)}


# ═══════════════════════════════════════════════════════════════════════════════
#  NEWS + SENTIMENT AGENT (Claude)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_news(name):
    try:
        r = requests.get("https://newsapi.org/v2/everything", timeout=10, params={
            "q": name, "sortBy": "publishedAt", "pageSize": 5,
            "language": "en", "apiKey": NEWS_API_KEY})
        return [a["title"] for a in r.json().get("articles",[]) if a.get("title")]
    except: return []

def analyse_sentiment(name, headlines):
    if not headlines:
        return {"score":"neutral","strength":5,"summary":"No news found.","key_factors":[]}
    txt = "\n".join(f"- {h}" for h in headlines)
    prompt = f"""Analyse these headlines for {name} as a financial trader would.
Headlines:\n{txt}

Respond ONLY with valid JSON:
{{"score":"bullish"|"bearish"|"neutral","strength":1-10,
"summary":"one sentence","key_factors":["factor1","factor2","factor3"]}}"""
    try:
        msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=300,
              messages=[{"role":"user","content":prompt}])
        raw = msg.content[0].text.strip().strip("```json").strip("```").strip()
        return json.loads(raw)
    except:
        return {"score":"neutral","strength":5,"summary":"Sentiment unavailable.","key_factors":[]}


# ═══════════════════════════════════════════════════════════════════════════════
#  POSITION SIZING AGENT
# ═══════════════════════════════════════════════════════════════════════════════

def position_size(account, risk_pct, entry, sl):
    if not entry or not sl: return {}
    risk_amt = account * (risk_pct / 100)
    price_risk = abs(entry - sl)
    units = risk_amt / price_risk if price_risk else 0
    return {"max_loss": round(risk_amt,2), "units": round(units,6),
            "position_value": round(units*entry,2)}


# ═══════════════════════════════════════════════════════════════════════════════
#  BRIEFING PRINTER
# ═══════════════════════════════════════════════════════════════════════════════

SIGNAL_ICONS = {"BUY": "▲ BUY", "SELL": "▼ SELL", "WAIT": "◆ WAIT"}
CAT_LABELS = {
    "EMA Cross (12/26)":        "TREND",
    "SMA Cross (20/50)":        "TREND",
    "Price vs SMA20":           "TREND",
    "Ichimoku TK Cross":        "TREND",
    "Ichimoku Cloud":           "TREND",
    "ADX":                      "TREND",
    "Parabolic SAR":            "TREND",
    "Supertrend":               "TREND",
    "RSI (14)":                 "MOMENTUM",
    "MACD Signal Cross":        "MOMENTUM",
    "MACD Histogram":           "MOMENTUM",
    "Stochastic (%K/%D)":       "MOMENTUM",
    "Williams %R":              "MOMENTUM",
    "MFI (Money Flow Index)":   "MOMENTUM",
    "Bollinger Bands":          "VOLATILITY",
    "ATR (Volatility)":         "VOLATILITY",
    "Keltner Channels":         "VOLATILITY",
    "OBV (On-Balance Volume)":  "VOLUME",
    "VWAP":                     "VOLUME",
    "A/D Line":                 "VOLUME",
    "Chaikin Money Flow":       "VOLUME",
}

def print_full_briefing(asset, price, tally, levels, pos, sentiment):
    sig  = tally["signal"]
    icon = SIGNAL_ICONS.get(sig, sig)
    sep  = "═" * 62
    thin = "─" * 62

    print(f"\n{sep}")
    print(f"  {asset['name']:20} {asset['symbol']}")
    print(f"  Live price: {price:>12,.4f}")
    print(f"  Signal: {icon:12}  Confidence: {tally['confidence']}%")
    print(thin)

    # Vote scoreboard
    t = tally["total"]
    b, s, w = tally["buy_votes"], tally["sell_votes"], tally["wait_votes"]
    bar_b = "█" * b
    bar_s = "█" * s
    bar_w = "░" * w
    print(f"  VOTE TALLY  ({t} indicators, need {tally['threshold']} to trade)")
    print(f"  BUY  [{bar_b:<20}] {b:2d}")
    print(f"  SELL [{bar_s:<20}] {s:2d}")
    print(f"  WAIT [{bar_w:<20}] {w:2d}")
    print(thin)

    # Indicator breakdown by category
    cats = ["TREND","MOMENTUM","VOLATILITY","VOLUME"]
    for cat in cats:
        cat_votes = [v for v in tally["detail"] if CAT_LABELS.get(v["name"])==cat]
        if not cat_votes: continue
        print(f"  [{cat}]")
        for v in cat_votes:
            s_icon = {"BUY":"▲","SELL":"▼","WAIT":"◆"}.get(v["signal"],"?")
            print(f"    {s_icon} {v['name']:<28} {v['reason']}")
    print(thin)

    # Trade levels
    if levels and sig in ("BUY","SELL"):
        print(f"  TRADE LEVELS")
        print(f"  Entry:       {levels['entry']:>14,.4f}")
        print(f"  Stop-loss:   {levels['stop_loss']:>14,.4f}  ← your max loss point")
        print(f"  Target 1:    {levels['target1']:>14,.4f}")
        print(f"  Target 2:    {levels['target2']:>14,.4f}")
        print(f"  Risk/Reward: {levels['risk_reward']}")
        if pos:
            print(thin)
            print(f"  POSITION SIZE")
            print(f"  Max loss on this trade:  £{pos['max_loss']:>8,.2f}")
            print(f"  Units to buy:            {pos['units']:>12,.6f}")
            print(f"  Total position value:   £{pos['position_value']:>8,.2f}")
    elif sig == "WAIT":
        print(f"  No trade — indicators disagree ({b} BUY vs {s} SELL).")
        print(f"  Wait for stronger consensus before entering.")

    # Sentiment
    print(thin)
    print(f"  SENTIMENT: {sentiment.get('score','?').upper()}  "
          f"(strength {sentiment.get('strength','?')}/10)")
    print(f"  {sentiment.get('summary','')}")
    for f in sentiment.get("key_factors",[]):
        print(f"    · {f}")
    print(sep)



# ═══════════════════════════════════════════════════════════════════════════════
#  TRADE ACTION TABLE — clean summary printed at the very end
# ═══════════════════════════════════════════════════════════════════════════════

def suggest_leverage(confidence, rr_str, signal):
    """Suggest conservative leverage based on signal strength."""
    if signal == "WAIT": return "—"
    try:
        rr_num = float(rr_str.split(":")[1]) if rr_str and ":" in rr_str else 1.0
    except: rr_num = 1.0
    if confidence >= 75 and rr_num >= 2.0: return "2x–3x"
    if confidence >= 60 and rr_num >= 1.5: return "1.5x–2x"
    return "1x (spot only)"

def print_trade_table(results, account_size, risk_pct):
    sep  = "═" * 100
    thin = "─" * 100
    now  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

    tradeable = [r for r in results
                 if r["tally"]["signal"] != "WAIT" and r.get("levels")]
    tradeable.sort(key=lambda x: x["tally"]["confidence"], reverse=True)

    print(f"\n{sep}")
    print(f"  TRADE ACTION TABLE  ·  {now}")
    print(f"  Account: £{account_size:,.0f}  |  Risk per trade: {risk_pct}%  "
          f"(max loss £{account_size*risk_pct/100:,.2f} per trade)")
    print(sep)

    if not tradeable:
        print("  No strong signals right now — all markets show mixed indicators.")
        print("  Best action: wait for clearer consensus before entering any trade.")
        print(sep)
        return

    # Header row
    col = {
        "asset":    14,
        "signal":    6,
        "conf":      6,
        "votes":    10,
        "entry":    12,
        "sl":       12,
        "tp1":      12,
        "tp2":      12,
        "rr":        6,
        "lev":      12,
        "risk":     10,
    }
    hdr = (f"  {'ASSET':<{col['asset']}}{'ACT':<{col['signal']}}"
           f"{'CONF':<{col['conf']}}{'VOTES':<{col['votes']}}"
           f"{'ENTRY':>{col['entry']}}{'STOP-LOSS':>{col['sl']}}"
           f"{'TARGET 1':>{col['tp1']}}{'TARGET 2':>{col['tp2']}}"
           f"{'RR':<{col['rr']}}{'LEVERAGE':<{col['lev']}}{'MAX RISK':<{col['risk']}}")
    print(hdr)
    print(thin)

    for r in tradeable:
        t   = r["tally"]
        lv  = r["levels"]
        sig = t["signal"]
        conf = t["confidence"]
        votes = f"{t['buy_votes']}B/{t['sell_votes']}S"
        entry = lv.get("entry", 0)
        sl    = lv.get("stop_loss", 0)
        tp1   = lv.get("target1", 0)
        tp2   = lv.get("target2", 0)
        rr    = lv.get("risk_reward", "—")
        risk_amt = account_size * risk_pct / 100
        lev   = suggest_leverage(conf, rr, sig)

        # Format numbers — crypto needs more decimals than forex
        def fmt(v):
            if v > 1000:   return f"{v:>12,.2f}"
            elif v > 1:    return f"{v:>12,.4f}"
            else:          return f"{v:>12,.6f}"

        row = (f"  {r['asset']:<{col['asset']}}{sig:<{col['signal']}}"
               f"{str(conf)+'%':<{col['conf']}}{votes:<{col['votes']}}"
               f"{fmt(entry)}{fmt(sl)}{fmt(tp1)}{fmt(tp2)}"
               f"{rr:<{col['rr']}}{lev:<{col['lev']}}£{risk_amt:<{col['risk']-1},.2f}")
        print(row)

    print(sep)

    # Plain-English action block for each trade
    print()
    for r in tradeable:
        t   = r["tally"]
        lv  = r["levels"]
        sig = t["signal"]
        entry = lv.get("entry", 0)
        sl    = lv.get("stop_loss", 0)
        tp1   = lv.get("target1", 0)
        tp2   = lv.get("target2", 0)
        rr    = lv.get("risk_reward", "—")
        lev   = suggest_leverage(t["confidence"], rr, sig)
        action_word = "BUY" if sig == "BUY" else "SHORT SELL"
        direction   = "rises to" if sig == "BUY" else "drops to"
        sl_word     = "above" if sig == "SELL" else "below"

        def p(v):
            return f"${v:,.2f}" if v > 10 else f"${v:,.5f}"

        print(f"  ► {r['asset']} — {action_word}")
        print(f"    Enter at:   {p(entry)}")
        print(f"    Stop-loss:  {p(sl)}  (exit immediately if price goes {sl_word} this — no exceptions)")
        print(f"    Target 1:   {p(tp1)}  ← take 50% profit here")
        print(f"    Target 2:   {p(tp2)}  ← let rest run to here")
        print(f"    Leverage:   {lev}  (start at 1x if you are new)")
        print(f"    Confidence: {t['confidence']}% ({t['buy_votes']} of {t['total']} indicators agree)")
        print(f"    Max risk:   £{account_size*2/100:.2f} of your account")
        print()

    print(f"  ⚠  REMINDER: Always set your stop-loss the moment you enter.")
    print(f"  ⚠  Never move your stop-loss further away once set.")
    print(f"  ⚠  Only use leverage if you fully understand how it works.")
    print(sep + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_analysis(account_size=1000.0, risk_pct=2.0):
    print(f"\n{'═'*62}")
    print(f"  AI TRADING SIGNAL AGENT  v2 — 20-Indicator Voting System")
    print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"  Account: £{account_size:,.0f}  |  Risk/trade: {risk_pct}%  |  Min votes: {MIN_VOTES_TO_TRADE}")
    print(f"{'═'*62}")

    results = []

    for asset in ASSETS:
        print(f"\n→ Scanning {asset['name']}...")

        md = get_market_data(asset)
        if not md or len(md["prices"]) < 30:
            reason = "API rate limit hit (Alpha Vantage: 25 calls/day max)" if md is None else "insufficient price history"
            print(f"  Skipped — {reason}.")
            continue

        # Run all 20 indicators
        all_votes = run_all_indicators(md)
        tally     = tally_votes(all_votes)

        # Trade levels + position sizing
        levels = calc_levels(md, tally["signal"])
        pos    = position_size(account_size, risk_pct,
                               levels.get("entry"), levels.get("stop_loss")) if levels else {}

        # News sentiment
        headlines = fetch_news(asset["name"])
        sentiment = analyse_sentiment(asset["name"], headlines)

        print_full_briefing(asset, md["prices"][-1], tally, levels, pos, sentiment)
        results.append({"asset": asset["name"], "tally": tally, "levels": levels})
        time.sleep(12)  # Alpha Vantage free = 5 req/min

    # ── Final Trade Action Table ─────────────────────────────────────────────
    print_trade_table(results, account_size, risk_pct)
    return results


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    YOUR_ACCOUNT_SIZE = 1000.0   # your capital in £
    YOUR_RISK_PCT     = 2.0      # % to risk per trade (keep 1-2%)

    run_analysis(account_size=YOUR_ACCOUNT_SIZE, risk_pct=YOUR_RISK_PCT)