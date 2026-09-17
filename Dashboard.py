"""
dashboard.py — AI Trading Signal Web Dashboard
===============================================
Run this file in PyCharm, then open your browser at:
  http://localhost:5000

It runs the full 20-indicator agent and shows results
as a live trading platform in your browser.

HOW TO RUN:
  1. Open PyCharm terminal
  2. pip install flask
  3. Right-click dashboard.py → Run 'dashboard'
  4. Open browser → http://localhost:5000
"""

from flask import Flask, jsonify, render_template_string
import threading, time, json
from datetime import datetime

# Import our agent functions
from agent import (
    ASSETS, get_market_data, run_all_indicators, tally_votes,
    calc_levels, fetch_news, analyse_sentiment, position_size,
    MIN_VOTES_TO_TRADE, suggest_leverage
)

app = Flask(__name__)

# ── Global state — updated by background scanner ──────────────────────────────
scan_state = {
    "last_scan":   None,
    "scanning":    False,
    "results":     [],
    "error":       None,
    "account":     1000.0,
    "risk_pct":    2.0,
}

# ─── TIMEFRAME GUIDE ──────────────────────────────────────────────────────────
TIMEFRAME_GUIDE = {
    "DAY_TRADE": {
        "label":       "Day Trade (your style)",
        "chart":       "5-minute + 15-minute",
        "hold":        "30 minutes – 4 hours",
        "enter":       "After signal fires on 15m chart confirmation",
        "exit":        "Same session — close all trades before market/exchange closes",
        "best_assets": ["BTC/USD", "ETH/USD", "EUR/USD", "GBP/USD"],
        "best_time":   "London open (8–11am GMT) or NY open (1–4pm GMT)",
        "notes":       "For crypto: any time. For forex: stick to London/NY overlap (1–4pm GMT)"
    }
}

# ─── Background scanner ───────────────────────────────────────────────────────
def run_scan_background():
    while True:
        if not scan_state["scanning"]:
            scan_state["scanning"] = True
            scan_state["error"]    = None
            results = []

            for asset in ASSETS:
                try:
                    md = get_market_data(asset)
                    if not md or len(md["prices"]) < 30:
                        results.append({
                            "name": asset["name"], "symbol": asset["symbol"],
                            "skipped": True, "reason": "Rate limit or no data"
                        })
                        continue

                    votes  = run_all_indicators(md)
                    tally  = tally_votes(votes)
                    levels = calc_levels(md, tally["signal"])
                    pos    = position_size(
                        scan_state["account"], scan_state["risk_pct"],
                        levels.get("entry"), levels.get("stop_loss")
                    ) if levels else {}

                    headlines = fetch_news(asset["name"])
                    sentiment = analyse_sentiment(asset["name"], headlines)
                    lev = suggest_leverage(
                        tally["confidence"],
                        levels.get("risk_reward",""),
                        tally["signal"]
                    ) if levels else "—"

                    # Build indicator list for UI
                    ind_list = []
                    for v in tally["detail"]:
                        ind_list.append({
                            "name":   v["name"],
                            "signal": v["signal"].lower(),
                            "reason": v["reason"]
                        })

                    results.append({
                        "name":        asset["name"],
                        "symbol":      asset["symbol"],
                        "icon":        asset["symbol"].split("/")[0][:3],
                        "icon_class":  asset["name"].lower().replace(" ","").replace("&",""),
                        "price":       md["prices"][-1],
                        "change_pct":  round((md["prices"][-1]-md["prices"][-2])/md["prices"][-2]*100, 2),
                        "signal":      tally["signal"],
                        "confidence":  tally["confidence"],
                        "buy_votes":   tally["buy_votes"],
                        "sell_votes":  tally["sell_votes"],
                        "wait_votes":  tally["wait_votes"],
                        "total_votes": tally["total"],
                        "entry":       levels.get("entry"),
                        "stop_loss":   levels.get("stop_loss"),
                        "target1":     levels.get("target1"),
                        "target2":     levels.get("target2"),
                        "rr":          levels.get("risk_reward","—"),
                        "leverage":    lev,
                        "max_loss":    pos.get("max_loss", scan_state["account"]*scan_state["risk_pct"]/100),
                        "units":       pos.get("units"),
                        "position_val":pos.get("position_value"),
                        "sentiment":   sentiment.get("score","neutral"),
                        "sentiment_str": sentiment.get("strength",5),
                        "news_summary":sentiment.get("summary",""),
                        "key_factors": sentiment.get("key_factors",[]),
                        "indicators":  ind_list,
                        "skipped":     False,
                    })
                    time.sleep(12)

                except Exception as e:
                    results.append({
                        "name": asset["name"], "symbol": asset["symbol"],
                        "skipped": True, "reason": str(e)
                    })

            scan_state["results"]   = results
            scan_state["last_scan"] = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            scan_state["scanning"]  = False

        time.sleep(3600)  # re-scan every hour


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/scan")
def api_scan():
    """Returns latest scan results as JSON."""
    return jsonify({
        "last_scan":    scan_state["last_scan"],
        "scanning":     scan_state["scanning"],
        "account":      scan_state["account"],
        "risk_pct":     scan_state["risk_pct"],
        "min_votes":    MIN_VOTES_TO_TRADE,
        "results":      scan_state["results"],
        "timeframe":    TIMEFRAME_GUIDE["DAY_TRADE"],
        "error":        scan_state["error"],
    })

@app.route("/api/rescan")
def api_rescan():
    """Force a new scan immediately."""
    scan_state["scanning"] = False
    scan_state["last_scan"] = None
    return jsonify({"status": "rescan triggered"})

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


# ─── Dashboard HTML ───────────────────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SignalOS — AI Trading Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#090c10;--bg2:#0d1117;--bg3:#161b22;--bg4:#21262d;--border:rgba(255,255,255,.07);--border2:rgba(255,255,255,.12);--green:#00ff9d;--green-dim:rgba(0,255,157,.1);--green-mid:rgba(0,255,157,.2);--red:#ff4d6a;--red-dim:rgba(255,77,106,.1);--amber:#f5a623;--amber-dim:rgba(245,166,35,.1);--blue:#58a6ff;--blue-dim:rgba(88,166,255,.1);--text:#e6edf3;--muted:#7d8590;--muted2:#484f58;--mono:'Space Mono',monospace;--sans:'DM Sans',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;min-height:100vh}
body::before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.03) 2px,rgba(0,0,0,.03) 4px);pointer-events:none;z-index:9999}

/* Header */
header{display:flex;align-items:center;justify-content:space-between;padding:16px 28px;border-bottom:1px solid var(--border);background:var(--bg2);position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:10px}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:30px;height:30px;border:1.5px solid var(--green);border-radius:6px;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:10px;color:var(--green);background:var(--green-dim)}
.logo-name{font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:.05em}
.logo-name span{color:var(--green)}
.hdr-right{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.live-badge{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;color:var(--green)}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;box-shadow:0 0 8px var(--green)}50%{opacity:.5;box-shadow:0 0 3px var(--green)}}
.ts{font-family:var(--mono);font-size:11px;color:var(--muted)}
.btn{background:var(--green-dim);border:1px solid rgba(0,255,157,.3);color:var(--green);font-family:var(--mono);font-size:11px;padding:7px 14px;border-radius:5px;cursor:pointer;transition:all .2s}
.btn:hover{background:var(--green-mid);box-shadow:0 0 12px rgba(0,255,157,.2)}
.btn.secondary{background:var(--bg3);border-color:var(--border2);color:var(--muted)}

/* Layout */
.main{padding:22px 28px;max-width:1440px;margin:0 auto}

/* Tabs */
.tabs{display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid var(--border);padding-bottom:0}
.tab{font-family:var(--mono);font-size:11px;padding:8px 18px;cursor:pointer;color:var(--muted);border-bottom:2px solid transparent;letter-spacing:.05em;transition:all .2s;text-transform:uppercase}
.tab.active{color:var(--green);border-bottom-color:var(--green)}
.tab-content{display:none}.tab-content.active{display:block}

/* Account bar */
.acc-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:22px}
.acc-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:14px 16px;position:relative;overflow:hidden}
.acc-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.acc-card.g::before{background:var(--green)}.acc-card.r::before{background:var(--red)}.acc-card.a::before{background:var(--amber)}.acc-card.b::before{background:var(--blue)}
.acc-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-family:var(--mono);margin-bottom:5px}
.acc-val{font-family:var(--mono);font-size:19px;font-weight:700}
.acc-val.g{color:var(--green)}.acc-val.r{color:var(--red)}.acc-val.a{color:var(--amber)}

/* Section label */
.sec{font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin-bottom:12px;display:flex;align-items:center;gap:10px}
.sec::after{content:'';flex:1;height:1px;background:var(--border)}

/* Signal grid */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px;margin-bottom:24px}

/* Card */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden;transition:border-color .2s,transform .2s}
.card:hover{border-color:var(--border2);transform:translateY(-1px)}
.card.buy{border-top:2px solid var(--green)}.card.sell{border-top:2px solid var(--red)}.card.wait{border-top:2px solid var(--muted2)}.card.skip{border-top:2px solid var(--muted2);opacity:.5}
.card-hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)}
.asset-info{display:flex;align-items:center;gap:10px}
.aicon{width:36px;height:36px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:10px;font-weight:700}
.aicon.btc{background:rgba(247,147,26,.15);color:#f7931a;border:1px solid rgba(247,147,26,.3)}
.aicon.eth{background:rgba(98,126,234,.15);color:#627eea;border:1px solid rgba(98,126,234,.3)}
.aicon.gold,.aicon.gld{background:rgba(245,166,35,.15);color:var(--amber);border:1px solid rgba(245,166,35,.3)}
.aicon.fx,.aicon.eurusd,.aicon.gbpusd{background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3)}
.aicon.sp,.aicon.sp500,.aicon.spy{background:rgba(0,255,157,.1);color:var(--green);border:1px solid rgba(0,255,157,.25)}
.aname{font-size:14px;font-weight:600}.asym{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:1px}
.badge{font-family:var(--mono);font-size:11px;font-weight:700;padding:5px 12px;border-radius:4px;letter-spacing:.06em}
.badge.buy{background:var(--green-dim);color:var(--green);border:1px solid rgba(0,255,157,.3)}
.badge.sell{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,77,106,.3)}
.badge.wait{background:var(--amber-dim);color:var(--amber);border:1px solid rgba(245,166,35,.3)}
.badge.skip{background:rgba(125,133,144,.1);color:var(--muted);border:1px solid var(--border)}
.card-body{padding:14px 16px}
.price-row{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:12px}
.price{font-family:var(--mono);font-size:21px;font-weight:700}
.chg{font-family:var(--mono);font-size:11px;margin-left:8px}
.chg.pos{color:var(--green)}.chg.neg{color:var(--red)}
.conf-block{text-align:right}
.conf-lbl{font-size:10px;color:var(--muted);font-family:var(--mono);text-transform:uppercase;letter-spacing:.06em}
.conf-val{font-family:var(--mono);font-size:18px;font-weight:700}
.conf-val.hi{color:var(--green)}.conf-val.md{color:var(--amber)}.conf-val.lo{color:var(--muted)}

/* Vote bars */
.votes{margin-bottom:12px}
.vrow{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.vlbl{font-family:var(--mono);font-size:10px;width:30px;color:var(--muted)}
.vbg{flex:1;height:5px;background:var(--bg4);border-radius:3px;overflow:hidden}
.vfill{height:100%;border-radius:3px;transition:width .8s}
.vfill.buy{background:var(--green)}.vfill.sell{background:var(--red)}.vfill.wait{background:var(--muted2)}
.vcnt{font-family:var(--mono);font-size:10px;color:var(--muted);width:20px;text-align:right}

/* Levels */
.levels{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:12px}
.lbox{background:var(--bg3);border-radius:6px;padding:9px 11px;border:1px solid var(--border)}
.lbox.entry{border-color:rgba(88,166,255,.2);background:var(--blue-dim)}
.lbox.sl{border-color:rgba(255,77,106,.2);background:var(--red-dim)}
.lbox.tp1{border-color:rgba(0,255,157,.15);background:var(--green-dim)}
.lbox.tp2{border-color:rgba(0,255,157,.08);background:rgba(0,255,157,.04)}
.llbl{font-family:var(--mono);font-size:9px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.lbox.entry .llbl{color:var(--blue)}.lbox.sl .llbl{color:var(--red)}.lbox.tp1 .llbl{color:var(--green)}.lbox.tp2 .llbl{color:rgba(0,255,157,.5)}
.lval{font-family:var(--mono);font-size:13px;font-weight:700}

/* Pills */
.pills{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.pill{background:var(--bg3);border:1px solid var(--border);border-radius:4px;padding:4px 9px;font-family:var(--mono);font-size:10px;color:var(--muted);display:flex;gap:4px;align-items:center}
.pill span{color:var(--text);font-weight:700}

/* Sentiment */
.sent-row{display:flex;align-items:center;gap:7px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}
.sdot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.sdot.bullish{background:var(--green)}.sdot.bearish{background:var(--red)}.sdot.neutral{background:var(--muted2)}

/* Indicator expand */
details summary{padding:9px 16px;font-family:var(--mono);font-size:10px;color:var(--muted);cursor:pointer;list-style:none;text-transform:uppercase;letter-spacing:.08em;border-top:1px solid var(--border)}
details summary:hover{color:var(--text)}
.ind-cat{font-family:var(--mono);font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted2);padding:8px 16px 3px;border-top:1px solid var(--border)}
.ind-cat:first-child{border-top:none}
.ind-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px 16px}
.ind-item{display:flex;align-items:center;gap:6px;font-size:11px;padding:3px 0}
.idot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.idot.buy{background:var(--green)}.idot.sell{background:var(--red)}.idot.wait{background:var(--muted2)}
.iname{color:var(--muted);font-family:var(--mono);font-size:10px}

/* Trade table */
.tbl-wrap{background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:22px}
.tbl-head{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.tbl-title{font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.05em}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{font-family:var(--mono);font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);padding:10px 14px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
th.r{text-align:right}
td{padding:13px 14px;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:12px;white-space:nowrap}
td.r{text-align:right}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.td-asset{display:flex;align-items:center;gap:8px}
.sig.buy{color:var(--green)}.sig.sell{color:var(--red)}.sig.wait{color:var(--amber)}
.entry-c{color:var(--blue)}.sl-c{color:var(--red)}.tp1-c{color:var(--green)}.tp2-c{color:rgba(0,255,157,.6)}.rr-c{color:var(--amber)}
.lev-pill{font-size:9px;padding:3px 7px;border-radius:3px;background:var(--amber-dim);color:var(--amber);border:1px solid rgba(245,166,35,.2)}

/* Action cards */
.action-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-bottom:22px}
.ac{background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.ac-hdr{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--border)}
.ac-badge{font-family:var(--mono);font-size:11px;font-weight:700;padding:4px 12px;border-radius:4px}
.ac-badge.buy{background:var(--green-dim);color:var(--green);border:1px solid rgba(0,255,157,.3)}
.ac-badge.sell{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,77,106,.3)}
.ac-title{font-size:14px;font-weight:600}
.ac-steps{padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.step{display:flex;gap:10px;align-items:flex-start}
.snum{width:20px;height:20px;border-radius:50%;background:var(--bg4);border:1px solid var(--border2);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:9px;color:var(--muted);flex-shrink:0;margin-top:1px}
.slbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-family:var(--mono);margin-bottom:2px}
.sval{font-family:var(--mono);font-size:13px;font-weight:700}
.snote{font-size:11px;color:var(--muted);margin-top:2px}

/* Timeframe panel */
.tf-panel{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:0;margin-bottom:22px;overflow:hidden}
.tf-head{padding:14px 18px;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--green)}
.tf-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0}
.tf-item{padding:16px 18px;border-right:1px solid var(--border);border-bottom:1px solid var(--border)}
.tf-item:last-child{border-right:none}
.tf-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-family:var(--mono);margin-bottom:6px}
.tf-val{font-size:13px;color:var(--text);line-height:1.5}
.tf-val strong{color:var(--green);font-family:var(--mono)}
.tf-note{grid-column:1/-1;padding:14px 18px;border-top:1px solid var(--border);font-size:12px;color:var(--muted);line-height:1.7;border-bottom:none}

/* Warning */
.warn{background:rgba(245,166,35,.05);border:1px solid rgba(245,166,35,.2);border-radius:8px;padding:13px 16px;display:flex;gap:10px;align-items:flex-start;margin-bottom:22px}
.warn-icon{font-family:var(--mono);font-size:12px;color:var(--amber);flex-shrink:0;margin-top:1px}
.warn-text{font-size:12px;color:rgba(245,166,35,.8);line-height:1.7}
.rate-notice{background:rgba(88,166,255,.05);border:1px solid rgba(88,166,255,.15);border-radius:8px;padding:11px 14px;font-size:12px;color:rgba(88,166,255,.7);margin-bottom:18px;font-family:var(--mono);line-height:1.6;display:none}

/* Loading */
.loading{display:flex;align-items:center;justify-content:center;padding:50px;flex-direction:column;gap:14px}
.spinner{width:32px;height:32px;border:2px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-text{font-family:var(--mono);font-size:12px;color:var(--muted)}
.skip-msg{padding:18px 16px;font-family:var(--mono);font-size:11px;color:var(--muted);text-align:center}

/* Scrollbar */
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:3px}

footer{text-align:center;padding:18px;font-family:var(--mono);font-size:10px;color:var(--muted2);border-top:1px solid var(--border);margin-top:10px}
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">AI</div>
    <div class="logo-name">SIGNAL<span>OS</span></div>
  </div>
  <div class="hdr-right">
    <div class="live-badge"><div class="live-dot"></div>LIVE</div>
    <div class="ts" id="ts">--:--:--</div>
    <button class="btn secondary" onclick="forceRescan()">↻ FORCE RESCAN</button>
    <button class="btn" onclick="loadData()">⟳ REFRESH</button>
  </div>
</header>

<div class="main">
  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" onclick="switchTab('signals')">Signals</div>
    <div class="tab" onclick="switchTab('table')">Trade Table</div>
    <div class="tab" onclick="switchTab('actions')">How To Trade</div>
    <div class="tab" onclick="switchTab('timeframe')">Timeframe Guide</div>
  </div>

  <!-- Account bar (always visible) -->
  <div class="acc-bar">
    <div class="acc-card g"><div class="acc-lbl">Account</div><div class="acc-val g" id="a-acc">—</div></div>
    <div class="acc-card r"><div class="acc-lbl">Max risk/trade</div><div class="acc-val r" id="a-risk">—</div></div>
    <div class="acc-card a"><div class="acc-lbl">Votes needed</div><div class="acc-val a" id="a-votes">—</div></div>
    <div class="acc-card b"><div class="acc-lbl">Assets scanned</div><div class="acc-val" id="a-scanned">—</div></div>
    <div class="acc-card g"><div class="acc-lbl">Active signals</div><div class="acc-val g" id="a-sigs">—</div></div>
    <div class="acc-card a"><div class="acc-lbl">Last scan</div><div class="acc-val" style="font-size:12px" id="a-time">—</div></div>
  </div>

  <div class="rate-notice" id="rate-notice">
    ⚠ Alpha Vantage rate limit hit (25 calls/day). Gold, Forex &amp; S&amp;P 500 unavailable until tomorrow.
    CoinGecko (Bitcoin, Ethereum) has no daily limit.
  </div>

  <!-- SIGNALS TAB -->
  <div class="tab-content active" id="tab-signals">
    <div class="sec">Live market signals</div>
    <div class="grid" id="sig-grid">
      <div class="loading"><div class="spinner"></div><div class="loading-text">Scanning markets — please wait...</div></div>
    </div>
  </div>

  <!-- TABLE TAB -->
  <div class="tab-content" id="tab-table">
    <div class="sec">Trade action table</div>
    <div id="tbl-area">
      <div class="loading"><div class="spinner"></div><div class="loading-text">Loading...</div></div>
    </div>
  </div>

  <!-- HOW TO TRADE TAB -->
  <div class="tab-content" id="tab-actions">
    <div class="sec">Step-by-step trade instructions</div>
    <div class="action-grid" id="action-area">
      <div class="loading"><div class="spinner"></div><div class="loading-text">Loading...</div></div>
    </div>
  </div>

  <!-- TIMEFRAME GUIDE TAB -->
  <div class="tab-content" id="tab-timeframe">
    <div class="sec">Day trading timeframe guide</div>
    <div id="tf-area">
      <div class="loading"><div class="spinner"></div><div class="loading-text">Loading...</div></div>
    </div>
  </div>

  <div class="warn">
    <div class="warn-icon">⚠</div>
    <div class="warn-text">
      Always set your stop-loss the moment you enter. Never move it further away. This tool is for educational purposes only.
      Past signals do not guarantee future results. Only trade capital you can afford to lose completely.
    </div>
  </div>
</div>

<footer>SIGNALOS v2.0 · 20-INDICATOR VOTING ENGINE · AI-POWERED · DAY TRADING EDITION</footer>

<script>
let DATA = null;

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    const names = ['signals','table','actions','timeframe'];
    t.classList.toggle('active', names[i] === name);
  });
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
}

function fmt(v) {
  if (v === null || v === undefined) return '—';
  if (v > 10000) return '$' + v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  if (v > 1)     return '$' + v.toFixed(4);
  return '$' + v.toFixed(6);
}

function confCls(c) { return c>=65?'hi':c>=50?'md':'lo'; }

function renderCard(a) {
  if (a.skipped) return `<div class="card skip">
    <div class="card-hdr"><div class="asset-info">
      <div class="aicon ${a.icon_class||'fx'}">${a.icon||'?'}</div>
      <div><div class="aname">${a.name}</div><div class="asym">${a.symbol}</div></div>
    </div><span class="badge skip">UNAVAIL</span></div>
    <div class="skip-msg">Alpha Vantage rate limit — available tomorrow</div>
  </div>`;

  const sig = (a.signal||'wait').toLowerCase();
  const total = a.total_votes || 21;
  const chgCls = (a.change_pct||0) >= 0 ? 'pos' : 'neg';
  const chgStr = (a.change_pct||0) >= 0 ? '+' : '';

  const levelsHtml = a.entry ? `
    <div class="levels">
      <div class="lbox entry"><div class="llbl">Entry</div><div class="lval">${fmt(a.entry)}</div></div>
      <div class="lbox sl"><div class="llbl">Stop-loss ⚠</div><div class="lval">${fmt(a.stop_loss)}</div></div>
      <div class="lbox tp1"><div class="llbl">Target 1 (50%)</div><div class="lval">${fmt(a.target1)}</div></div>
      <div class="lbox tp2"><div class="llbl">Target 2 (rest)</div><div class="lval">${fmt(a.target2)}</div></div>
    </div>
    <div class="pills">
      <div class="pill">R:R <span>${a.rr||'—'}</span></div>
      <div class="pill">Leverage <span>${a.leverage||'1x'}</span></div>
      <div class="pill">Max loss <span style="color:var(--red)">£${(a.max_loss||0).toFixed(2)}</span></div>
    </div>` : `<div style="padding:8px 0;font-size:12px;color:var(--muted);font-family:var(--mono)">No trade — wait for stronger signal</div>`;

  // Indicators by category
  const cats = ['TREND','MOMENTUM','VOLATILITY','VOLUME'];
  let indHtml = '';
  cats.forEach(cat => {
    const items = (a.indicators||[]).filter(i => {
      const nm = i.name.toUpperCase();
      if(cat==='TREND') return ['EMA','SMA','PRICE VS','ICHIMOKU','ADX','PARABOLIC','SUPERTREND'].some(k=>nm.includes(k));
      if(cat==='MOMENTUM') return ['RSI','MACD','STOCHASTIC','WILLIAMS','MFI'].some(k=>nm.includes(k));
      if(cat==='VOLATILITY') return ['BOLLINGER','ATR','KELTNER'].some(k=>nm.includes(k));
      if(cat==='VOLUME') return ['OBV','VWAP','A/D','CHAIKIN'].some(k=>nm.includes(k));
      return false;
    });
    if(!items.length) return;
    indHtml += `<div class="ind-cat">${cat}</div><div class="ind-grid">`;
    items.forEach(i => {
      indHtml += `<div class="ind-item"><div class="idot ${i.signal}"></div><div class="iname">${i.name}</div></div>`;
    });
    indHtml += `</div>`;
  });

  return `<div class="card ${sig}">
    <div class="card-hdr">
      <div class="asset-info">
        <div class="aicon ${(a.icon_class||'fx').replace(/[^a-z]/g,'')}">${a.icon||'?'}</div>
        <div><div class="aname">${a.name}</div><div class="asym">${a.symbol}</div></div>
      </div>
      <span class="badge ${sig}">${a.signal||'WAIT'}</span>
    </div>
    <div class="card-body">
      <div class="price-row">
        <div><span class="price">${fmt(a.price)}</span><span class="chg ${chgCls}">${chgStr}${(a.change_pct||0).toFixed(2)}%</span></div>
        <div class="conf-block">
          <div class="conf-lbl">Confidence</div>
          <div class="conf-val ${confCls(a.confidence)}">${a.confidence}%</div>
        </div>
      </div>
      <div class="votes">
        <div class="vrow"><div class="vlbl">BUY</div><div class="vbg"><div class="vfill buy" style="width:${a.buy_votes/total*100}%"></div></div><div class="vcnt">${a.buy_votes}</div></div>
        <div class="vrow"><div class="vlbl">SELL</div><div class="vbg"><div class="vfill sell" style="width:${a.sell_votes/total*100}%"></div></div><div class="vcnt">${a.sell_votes}</div></div>
        <div class="vrow"><div class="vlbl">WAIT</div><div class="vbg"><div class="vfill wait" style="width:${a.wait_votes/total*100}%"></div></div><div class="vcnt">${a.wait_votes}</div></div>
      </div>
      ${levelsHtml}
      <div class="sent-row">
        <div class="sdot ${a.sentiment||'neutral'}"></div>
        Sentiment: ${(a.sentiment||'neutral').toUpperCase()} · ${a.news_summary||'No news data'}
      </div>
    </div>
    ${indHtml?`<details><summary>▸ View all ${total} indicators</summary>${indHtml}</details>`:''}
  </div>`;
}

function renderTable(tradeable, d) {
  if (!tradeable.length) return `<div class="tbl-wrap"><div class="tbl-head"><div class="tbl-title">TRADE ACTION TABLE</div></div>
    <div style="padding:30px;text-align:center;font-family:var(--mono);font-size:12px;color:var(--muted)">No strong signals — wait for clearer consensus.</div></div>`;

  const rows = tradeable.map(a => {
    const sig = (a.signal||'wait').toLowerCase();
    return `<tr>
      <td><div class="td-asset"><div class="aicon ${(a.icon_class||'fx').replace(/[^a-z]/g,'')} " style="width:26px;height:26px;font-size:9px">${a.icon}</div>${a.name}</div></td>
      <td class="sig ${sig}">${a.signal}</td>
      <td style="color:${a.confidence>=65?'var(--green)':a.confidence>=50?'var(--amber)':'var(--muted)'}">${a.confidence}%</td>
      <td>${a.buy_votes}B / ${a.sell_votes}S</td>
      <td class="r entry-c">${fmt(a.entry)}</td>
      <td class="r sl-c">${fmt(a.stop_loss)}</td>
      <td class="r tp1-c">${fmt(a.target1)}</td>
      <td class="r tp2-c">${fmt(a.target2)}</td>
      <td class="rr-c">${a.rr||'—'}</td>
      <td><span class="lev-pill">${a.leverage||'1x'}</span></td>
      <td class="r" style="color:var(--red)">£${(a.max_loss||0).toFixed(2)}</td>
    </tr>`;
  }).join('');

  return `<div class="tbl-wrap">
    <div class="tbl-head"><div class="tbl-title">TRADE ACTION TABLE</div><div style="font-family:var(--mono);font-size:10px;color:var(--muted)">${d.last_scan||''}</div></div>
    <div class="scroll"><table>
      <thead><tr>
        <th>Asset</th><th>Signal</th><th>Conf</th><th>Votes</th>
        <th class="r">Entry</th><th class="r">Stop-Loss</th>
        <th class="r">Target 1</th><th class="r">Target 2</th>
        <th>R:R</th><th>Leverage</th><th class="r">Max Risk</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </div>`;
}

function renderActions(tradeable, d) {
  if (!tradeable.length) return `<div style="padding:20px;font-family:var(--mono);font-size:12px;color:var(--muted)">No actionable trades right now.</div>`;
  return tradeable.map(a => {
    const sig = (a.signal||'wait').toLowerCase();
    const word = a.signal==='BUY'?'BUY / LONG':'SELL / SHORT';
    const slDir = a.signal==='BUY'?'drops below':'rises above';
    return `<div class="ac">
      <div class="ac-hdr"><span class="ac-badge ${sig}">${word}</span><div class="ac-title">${a.name}</div></div>
      <div class="ac-steps">
        <div class="step"><div class="snum">1</div><div><div class="slbl">Enter at</div><div class="sval" style="color:var(--blue)">${fmt(a.entry)}</div><div class="snote">Place a limit/market order at this price</div></div></div>
        <div class="step"><div class="snum">2</div><div><div class="slbl">Set stop-loss immediately</div><div class="sval" style="color:var(--red)">${fmt(a.stop_loss)}</div><div class="snote">Exit if price ${slDir} this — no exceptions, ever</div></div></div>
        <div class="step"><div class="snum">3</div><div><div class="slbl">Take 50% profit at Target 1</div><div class="sval" style="color:var(--green)">${fmt(a.target1)}</div><div class="snote">Close half position here — guaranteed partial profit</div></div></div>
        <div class="step"><div class="snum">4</div><div><div class="slbl">Let rest run to Target 2</div><div class="sval" style="color:rgba(0,255,157,.7)">${fmt(a.target2)}</div><div class="snote">Move stop-loss to entry price after T1 hits (free trade)</div></div></div>
        <div class="step"><div class="snum">5</div><div><div class="slbl">Position sizing</div><div class="sval" style="color:var(--amber)">£${(a.max_loss||0).toFixed(2)} at risk</div><div class="snote">Leverage: ${a.leverage||'1x'} · Confidence: ${a.confidence}% · R:R ${a.rr||'—'}</div></div></div>
      </div>
    </div>`;
  }).join('');
}

function renderTimeframe(tf) {
  if (!tf) return '';
  return `<div class="tf-panel">
    <div class="tf-head">▸ DAY TRADING — Recommended Setup</div>
    <div class="tf-grid">
      <div class="tf-item"><div class="tf-lbl">Chart timeframe</div><div class="tf-val"><strong>${tf.chart}</strong><br>Use 15m for signal, 5m for entry</div></div>
      <div class="tf-item"><div class="tf-lbl">Hold time</div><div class="tf-val"><strong>${tf.hold}</strong><br>Close all trades before day ends</div></div>
      <div class="tf-item"><div class="tf-lbl">Best trading hours</div><div class="tf-val"><strong>${tf.best_time}</strong></div></div>
      <div class="tf-item"><div class="tf-lbl">Best assets for day trading</div><div class="tf-val">${tf.best_assets.map(a=>`<strong>${a}</strong>`).join(' · ')}</div></div>
      <div class="tf-item"><div class="tf-lbl">When to enter</div><div class="tf-val">${tf.enter}</div></div>
      <div class="tf-item"><div class="tf-lbl">When to exit</div><div class="tf-val">${tf.exit}</div></div>
    </div>
    <div class="tf-note">
      <strong style="color:var(--green);font-family:var(--mono)">HOW TO USE THIS AGENT FOR DAY TRADING:</strong><br><br>
      1. Run the agent in the morning (8am GMT for forex, any time for crypto)<br>
      2. Check which assets have <strong style="color:var(--green)">BUY</strong> or <strong style="color:var(--red)">SELL</strong> signal with confidence ≥60%<br>
      3. Open your broker (Binance for crypto / Trading 212 for forex) on the <strong>15-minute chart</strong><br>
      4. Wait for price to reach the <strong style="color:var(--blue)">entry level</strong> shown, then place your trade<br>
      5. Immediately set stop-loss at the <strong style="color:var(--red)">stop-loss level</strong> shown<br>
      6. Walk away — let it run to Target 1, take 50% profit, then let rest go to Target 2<br>
      7. Close everything before 9pm GMT (crypto) or market close (forex)<br><br>
      <strong style="color:var(--amber);font-family:var(--mono)">NEVER hold a day trade overnight.</strong> Risk changes completely after hours.
    </div>
  </div>`;
}

async function loadData() {
  try {
    const res = await fetch('/api/scan');
    const d = await res.json();
    DATA = d;

    const riskAmt = (d.account * d.risk_pct / 100);
    const scanned = (d.results||[]).filter(r=>!r.skipped).length;
    const tradeable = (d.results||[]).filter(r=>!r.skipped && r.signal && r.signal!=='WAIT');
    const hasRateLimit = (d.results||[]).some(r=>r.skipped);

    document.getElementById('a-acc').textContent     = `£${(d.account||0).toLocaleString()}`;
    document.getElementById('a-risk').textContent    = `£${riskAmt.toFixed(2)}`;
    document.getElementById('a-votes').textContent   = `${d.min_votes||6} / 21`;
    document.getElementById('a-scanned').textContent = `${scanned} / ${(d.results||[]).length}`;
    document.getElementById('a-sigs').textContent    = `${tradeable.length} signal${tradeable.length!==1?'s':''}`;
    document.getElementById('a-time').textContent    = d.scanning ? 'Scanning...' : (d.last_scan||'—');

    document.getElementById('rate-notice').style.display = hasRateLimit ? 'block' : 'none';

    if (d.scanning) {
      document.getElementById('sig-grid').innerHTML = '<div class="loading"><div class="spinner"></div><div class="loading-text">Agent is scanning markets — this takes ~2 minutes on first run...</div></div>';
    } else {
      document.getElementById('sig-grid').innerHTML = (d.results||[]).map(renderCard).join('');
    }

    document.getElementById('tbl-area').innerHTML    = renderTable(tradeable, d);
    document.getElementById('action-area').innerHTML = renderActions(tradeable, d);
    document.getElementById('tf-area').innerHTML     = renderTimeframe(d.timeframe);

  } catch(e) {
    console.error(e);
    document.getElementById('sig-grid').innerHTML = `<div style="padding:20px;font-family:var(--mono);font-size:12px;color:var(--red)">Error loading data: ${e.message}<br>Make sure dashboard.py is running.</div>`;
  }
}

async function forceRescan() {
  await fetch('/api/rescan');
  setTimeout(loadData, 500);
}

setInterval(() => { document.getElementById('ts').textContent = new Date().toLocaleTimeString(); }, 1000);
setInterval(loadData, 30000); // auto refresh every 30s
loadData();
</script>
</body>
</html>"""


# ─── Start background scanner thread ─────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  AI Trading Dashboard")
    print("  Starting background market scanner...")
    print("  Open your browser at:  http://localhost:5000")
    print("="*60 + "\n")

    scanner_thread = threading.Thread(target=run_scan_background, daemon=True)
    scanner_thread.start()

    app.run(debug=False, port=5000, use_reloader=False)