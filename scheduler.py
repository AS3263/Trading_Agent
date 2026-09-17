"""
scheduler.py — runs the trading agent automatically every N minutes
Usage: python scheduler.py
"""

import time
import schedule
from datetime import datetime
from agent import run_analysis

# ── Your settings ─────────────────────────────────────────────────
ACCOUNT_SIZE   = 10.0   # your capital in £/$
RISK_PCT       = 2.0      # % risk per trade
RUN_EVERY_MINS = 60       # how often to scan (60 = hourly)
# ─────────────────────────────────────────────────────────────────

def job():
    print(f"\n[{datetime.now().strftime('%H:%M')}] Scheduled scan starting...")
    try:
        run_analysis(account_size=ACCOUNT_SIZE, risk_pct=RISK_PCT)
    except Exception as e:
        print(f"[ERROR] {e}")

# Run immediately on start, then every N minutes
job()
schedule.every(RUN_EVERY_MINS).minutes.do(job)

print(f"\nScheduler running — scanning every {RUN_EVERY_MINS} minutes.")
print("Press Ctrl+C to stop.\n")

while True:
    schedule.run_pending()
    time.sleep(30)
