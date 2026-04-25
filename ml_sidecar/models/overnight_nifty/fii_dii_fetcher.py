"""
FII/DII flows fetcher — STUB / DEFERRED.

This is the single highest-value missing feature for the overnight Nifty model.
Foreign and Domestic Institutional Investor net flows are *the* leading indicator
for next-day Indian equity moves and are not encoded in any global ticker.

Why this is a stub:
  * Free sources (moneycontrol, NSE) are protected by Akamai / require live
    cookie machinery and break frequently.
  * Reliable 10-year historical coverage requires either:
      (a) Building a robust scraper with retry/backoff/captcha handling
          (~1-2 days of engineering + ongoing maintenance), or
      (b) A paid data API (e.g. NSE Trader Workstation, Refinitiv).

Until this is built, the model uses only yfinance global cues. Adding FII/DII
is expected to lift directional accuracy by several percentage points (the
dominant force on Nifty open is institutional flow, not US futures).

Sources to try when implementing:
  * NSE official:  https://www.nseindia.com/api/fiidiiTradeReact
                   (real-time only; needs cookie refresh from sidecar.py)
  * NSE archives:  https://archives.nseindia.com/content/fpi/  (historical CSVs)
  * jugaad-data:   pip install jugaad-data (community NSE wrapper)
  * Trendlyne:     scraping; known structure but rate-limited
  * Paid:          NSE TWS, Refinitiv DataScope

Expected schema once built:
    date, fii_buy_cr, fii_sell_cr, fii_net_cr, dii_buy_cr, dii_sell_cr, dii_net_cr
"""

raise NotImplementedError(
    "FII/DII fetcher not implemented — see module docstring for details. "
    "Run model without FII/DII features for now."
)
