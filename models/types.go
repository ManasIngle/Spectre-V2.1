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
	Signal               string        `json:"signal"`
	RawSignal            string        `json:"raw_signal"`
	CrossAssetSignal     string        `json:"CrossAssetSignal"`
	Prediction           string        `json:"prediction"`
	CrossAssetPrediction string        `json:"cross_asset_prediction"`
	OptionType           string        `json:"option_type"`
	ValidUntil           string        `json:"valid_until"`
	Strike               float64       `json:"strike"`
	NiftySpot            float64       `json:"nifty_spot"`
	EntryEst             float64       `json:"entry_est"`
	TargetEst            float64       `json:"target_est"`
	SLEst                float64       `json:"sl_est"`
	TargetNifty          float64       `json:"target_nifty"`
	SLNifty              float64       `json:"sl_nifty"`
	Confidence           float64       `json:"confidence"`
	ProbUp               float64       `json:"prob_up"`
	ProbDown             float64       `json:"prob_down"`
	ProbSideways         float64       `json:"prob_sideways"`
	CrossAssetProbs      []float64     `json:"cross_asset_probs,omitempty"`
	OptionLTP            *float64      `json:"option_ltp"`
	PCR                  *float64      `json:"pcr"`
	OIConfirms           bool          `json:"oi_confirms"`
	EquityConfirms       bool          `json:"equity_confirms"`
	EnsembleMode         bool          `json:"ensemble_mode"`
	Support              float64       `json:"support"`
	Resistance           float64       `json:"resistance"`
	ModelAccuracy        float64       `json:"model_accuracy"`
	EquityReturn         float64       `json:"equity_return"`
	EquityAdvPct         float64       `json:"equity_advance_pct"`
	KeyFactors           []KeyFactor   `json:"key_factors"`
	Stability            StabilityInfo `json:"stability"`
	Error                string        `json:"error,omitempty"`
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
