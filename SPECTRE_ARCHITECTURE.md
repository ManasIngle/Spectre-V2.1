# SPECTRE QUANTITATIVE TRADING SYSTEM: ARCHITECTURE (V2)

## Executive Summary
Spectre is a high-frequency, dual-algorithm quantitative trading system designed exclusively for the Nifty 50 Index. 
Unlike standard trading bots that rely on static technical indicators, Spectre utilizes a highly robust, multi-layered Architecture built around two custom Machine Learning (XGBoost) engines trained on 10 years of intrinsic market data. It runs natively in compiled Go for ultra-fast execution, while a separate Python Sidecar handles the heavy ML mathematical lifting in the background.

---

## 1. The Machine Learning Engine (Python Sidecar)
The system fundamentally relies on two highly tuned, heavily separated AIs that evaluate identical market structures and report back different trading strategies.

### A. The "Raw Vanilla" Model (1-Minute Rolling Model)
* **File:** `nifty_rolling_model.pkl`
* **Data Structure:** True 1-Minute tick data, stitched dynamically into a Rolling 5-Minute Window. This allows the AI to evaluate a fully closed, historically accurate 5-minute candlestick chart structure every 60 seconds.
* **Brain Profile:** This model is "Conservative." It operates on standard OHLCV (Open, High, Low, Close, Vol) data for Nifty 50. Because the stock market chops sideways most of the time, this model acts defensively.
* **Edge:** Achieving `47.5% Accuracy` over standard market noise. It excels at keeping the trader out of low-probability sideways chop by aggressively predicting `SIDEWAYS`, preventing theta/premium decay in option buying. 

### B. The "Aggressive Breakout" Model (BankNifty Cross-Asset Model)
* **File:** `nifty_cross_asset_model.pkl`
* **Data Structure:** Identical rolling 1m candles, but heavily augmented by syncing flawlessly to Nifty Bank (`^NSEBANK`) timestamps at the exact same minute.
* **Brain Profile:** This AI operates on **Aggressive Class Weights**. Mathematically, it was penalized severely during training for missing an `UP` or `DOWN` trend. It utilizes hidden sectoral alpha:
  1. `feat_bank_spread`: Is BankNifty diverging/leading the vanilla Nifty index?
  2. `feat_bank_volatility`: How violently is the Bank component breaking out?
* **Edge:** By refusing to play it safe, its overall generic accuracy drops, but its **Recall** surges massively. This model successfully catches over `54%` of all violent market crashes and rallies before they manifest on the vanilla 5m chart, making it an incredible tool for high-leverage "Hero Trades".

### The Target Window Matrix
Both AIs were trained to predict exact outcomes based on specific thresholds:
* **Horizon:** Does Nifty break out exactly `15 Minutes` after the signal is generated?
* **Threshold:** Does Nifty gap by at least `0.08%` within those 15 minutes? If not, the AI learns it was a fake-out (SIDEWAYS). 

---

## 2. The Core Backend (Go Microservice)
Because Python is too slow for production-level routing and state management, the main nervous system is written in Golang natively. 

### A. The Routing Network (Python Sidecar Handover)
* Go operates the webserver on port `:8239`.
* When it needs an analysis, it hits an invisible internal API hosted by Python (`:8240`) via `FastAPI`.
* Python concurrently downloads real-time tick data, manually calculates the 33 overlapping indicators natively, runs both AIs simultaneously, and serializes a JSON payload back to Go.

### B. The Stability Engine (Go Mathematical Wrapper)
The Go application acts as the "Adult in the Room". It parses the `Raw Prediction` coming from the Vanilla Python model and subjects it to strict Hysteresis rules:
* **Conviction Rule:** It prevents the signal from "whipsawing" (flipping constantly between UP and DOWN based on micro-volatility). If the ML predicts a trend reversal but the probability gap isn't strong enough (Conviction < 8%), Go rejects the signal and forces it to remain in the previous direction.
* **Est. Hold Framework:** By looking at live ATR (Average True Range), Go calculates the actual volatility speed of the market, dynamically adjusting how long the trader should hold the option (e.g. `Est. Hold: 20 mins` vs `60 mins`).

### C. The VPS Headless Automation Cron
Because Spectre is designed to run silently 24/7 on a remote server:
* Go has a native background `goroutine` (cron loop) that launches on boot.
* Every minute between `09:00 AM` and `03:30 PM IST`, it bypasses the internet cache, forces the Python AI to review the live data, processes the algorithmic outcome, and silently writes it row completely natively to a system file: `system_signals.csv`.
* This fundamentally decouples data accumulation from the Frontend GUI. The bot trades and records data constantly without a browser being required.
