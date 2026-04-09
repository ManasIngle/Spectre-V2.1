package config

import "time"

const (
NiftyTicker     = "^NSEI"
BankNiftyTicker = "^NSEBANK"
CacheTTLFast    = 25 * time.Second
CacheTTLMed     = 60 * time.Second
SignalCacheTTL  = 25 * time.Second
DirCacheTTL     = 45 * time.Second
Port            = ":8239"
)

var TraderTickers = []string{
"^DJI", "^NSEI", "^NSEBANK",
"HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS",
"RELIANCE.NS", "TCS.NS", "INFY.NS", "ITC.NS", "LT.NS",
"BAJFINANCE.NS", "BHARTIARTL.NS", "HINDUNILVR.NS", "ASIANPAINT.NS",
"MARUTI.NS", "SUNPHARMA.NS", "TATAMOTORS.NS", "WIPRO.NS", "HCLTECH.NS",
"TITAN.NS", "NTPC.NS", "POWERGRID.NS",
}

var TopContributors = []string{
"HDFCBANK.NS", "RELIANCE.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
"BHARTIARTL.NS", "ITC.NS", "LT.NS", "SBIN.NS", "BAJFINANCE.NS",
}

var EquityWeights = map[string]float64{
"HDFCBANK": 0.13, "RELIANCE": 0.10, "ICICIBANK": 0.08, "INFY": 0.07,
"TCS": 0.04, "BHARTIARTL": 0.04, "ITC": 0.04, "LT": 0.03,
"SBIN": 0.03, "BAJFINANCE": 0.02,
}

type TFConfig struct{ Interval, Range string; Weight float64 }

var Timeframes = map[string]TFConfig{
"1m":  {"1m", "5d", 1.0},
"3m":  {"3m", "5d", 1.5},
"5m":  {"5m", "5d", 2.0},
"15m": {"15m", "1mo", 3.0},
}
