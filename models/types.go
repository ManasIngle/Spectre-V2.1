package models

type OHLCV struct {
	Time                        int64
	Open, High, Low, Close, Volume float64
}

type OptionStrike struct {
	Strike, CELTP, PELTP        float64
	CEOI, PEOI, CEOIChg, PEOIChg int64
}

type OIChainData struct {
	Strikes                         []OptionStrike `json:"strikes"`
	PCR                             float64        `json:"pcr_oi"`
	TotalCEOI, TotalPEOI            int64
	TotalCEOIChg, TotalPEOIChg      int64
	Error                           string         `json:"error,omitempty"`
}

type TFDetail struct {
	RawScore                                                         int
	Normalized, LTP, Change, RSI, ADXStrength, MACDHist, Momentum   float64
	VWAP, EMA9, EMA21                                               float64
	Signals                                                          map[string]string `json:"signals"`
}

type OIAnalysis struct {
	PCR                             float64
	PCRBias                         string
	CEOIChange, PEOIChange          int64
	MaxCEStrike, MaxPEStrike        float64
	Resistance, Support             float64
}

type DirectionResult struct {
	Score, Confidence, IndicatorScore, OIBias, NiftyLTP float64
	Direction, SuggestedAction                           string
	Timeframes                                           map[string]TFDetail `json:"timeframes"`
	OIAnalysis                                           OIAnalysis          `json:"oi_analysis"`
}

type KeyFactor struct{ Factor, Value, Bias string }

type StabilityInfo struct {
	StableSignal, StableDirection, Status, RawDirection, Detail string
	ConvictionOK                                                 bool
	ProbGap, CooldownRemaining                                   float64
	FlipsPrevented, ConfirmedSignals, ConfirmedFlips             int
}

type TradeSignal struct {
	Signal, RawSignal, CrossAssetSignal, Prediction, CrossAssetPrediction, OptionType, ValidUntil string
	Strike, NiftySpot, EntryEst, TargetEst, SLEst         float64
	TargetNifty, SLNifty                                   float64
	Confidence, ProbUp, ProbDown, ProbSideways             float64
	CrossAssetProbs                                        []float64     `json:"cross_asset_probs,omitempty"`
	OptionLTP, PCR                                         *float64
	OIConfirms, EquityConfirms, EnsembleMode               bool
	Support, Resistance, ModelAccuracy                     float64
	EquityReturn, EquityAdvPct                             float64
	KeyFactors                                             []KeyFactor   `json:"key_factors"`
	Stability                                              StabilityInfo `json:"stability"`
	Error                                                  string        `json:"error,omitempty"`
}

type StabilityStateResp struct {
	ConfirmedDirection, PendingDirection            string
	ConfirmedAt, CooldownUntil, FlipPreventionRate  float64
	PendingCount, TotalRaw, FlipsPrevented          int
	ConfirmedSignals, ConfirmedFlips, HistoryDepth  int
}

type HeatmapItem struct {
	Ticker        string  `json:"ticker"`
	LTP           float64 `json:"ltp"`
	ChangePercent float64 `json:"changePercent"`
}

type TickerRow struct {
	Script, Status                                    string
	LTP, Change                                       float64
	RSI, MACD, EMACross, VWAP, ST211, ST142, ST103   string
	Alligator, ADX, Volume                            string
}
