package models

type OHLCV struct {
	Time   int64   `json:"time"`
	Open   float64 `json:"open"`
	High   float64 `json:"high"`
	Low    float64 `json:"low"`
	Close  float64 `json:"close"`
	Volume float64 `json:"volume"`
}

type OptionStrike struct {
	Strike  float64 `json:"strike"`
	CELTP   float64 `json:"ce_ltp"`
	PELTP   float64 `json:"pe_ltp"`
	CEOI    int64   `json:"ce_oi"`
	PEOI    int64   `json:"pe_oi"`
	CEOIChg int64   `json:"ce_oi_chg"`
	PEOIChg int64   `json:"pe_oi_chg"`
}

type OIChainData struct {
	Strikes      []OptionStrike `json:"strikes"`
	PCR          float64        `json:"pcr_oi"`
	Underlying   float64        `json:"underlying,omitempty"`
	TotalCEOI    int64          `json:"total_ce_oi"`
	TotalPEOI    int64          `json:"total_pe_oi"`
	TotalCEOIChg int64          `json:"total_ce_oi_chg"`
	TotalPEOIChg int64          `json:"total_pe_oi_chg"`
	Error        string         `json:"error,omitempty"`
}

// OISnapshot is one entry in the intraday OI trend history (one per successful NSE fetch).
type OISnapshot struct {
	Timestamp    string  `json:"timestamp"`
	Time         int64   `json:"time"`
	Underlying   float64 `json:"underlying"`
	TotalCEOIChg int64   `json:"total_ce_oi_chg"`
	TotalPEOIChg int64   `json:"total_pe_oi_chg"`
	PCR          float64 `json:"pcr_oi"`
}

type TFDetail struct {
	RawScore    int               `json:"raw_score"`
	Normalized  float64           `json:"normalized"`
	LTP         float64           `json:"ltp"`
	Change      float64           `json:"change"`
	RSI         float64           `json:"rsi"`
	ADXStrength float64           `json:"adx_strength"`
	MACDHist    float64           `json:"macd_hist"`
	Momentum    float64           `json:"momentum"`
	VWAP        float64           `json:"vwap"`
	EMA9        float64           `json:"ema9"`
	EMA21       float64           `json:"ema21"`
	Signals     map[string]string `json:"signals"`
}

type OIAnalysis struct {
	PCR         float64 `json:"pcr"`
	PCRBias     string  `json:"pcr_bias"`
	CEOIChange  int64   `json:"ce_oi_change"`
	PEOIChange  int64   `json:"pe_oi_change"`
	MaxCEStrike float64 `json:"max_ce_strike"`
	MaxPEStrike float64 `json:"max_pe_strike"`
	Resistance  float64 `json:"resistance"`
	Support     float64 `json:"support"`
}

type DirectionResult struct {
	Score           float64             `json:"score"`
	Confidence      float64             `json:"confidence"`
	IndicatorScore  float64             `json:"indicator_score"`
	OIBias          float64             `json:"oi_bias"`
	NiftyLTP        float64             `json:"nifty_ltp"`
	Direction       string              `json:"direction"`
	SuggestedAction string              `json:"action"`
	Timeframes      map[string]TFDetail `json:"timeframes"`
	OIAnalysis      OIAnalysis          `json:"oi_analysis"`
}

type KeyFactor struct {
	Factor string `json:"factor"`
	Value  string `json:"value"`
	Bias   string `json:"bias"`
}

type StabilityInfo struct {
	StableSignal      string  `json:"stable_signal"`
	StableDirection   string  `json:"stable_direction"`
	Status            string  `json:"status"`
	RawDirection      string  `json:"raw_direction"`
	Detail            string  `json:"detail"`
	ConvictionOK      bool    `json:"conviction_ok"`
	ProbGap           float64 `json:"prob_gap"`
	CooldownRemaining float64 `json:"cooldown_remaining"`
	FlipsPrevented    int     `json:"flips_prevented"`
	ConfirmedSignals  int     `json:"confirmed_signals"`
	ConfirmedFlips    int     `json:"confirmed_flips"`
}

type ModelOutput struct {
	Prediction int        `json:"prediction"`
	Signal     string     `json:"signal"`
	Probs      [3]float64 `json:"probs"`
	Label      string     `json:"label"`
	Accuracy   float64    `json:"accuracy"`
}

type ModelsBreakdown struct {
	Rolling      ModelOutput  `json:"rolling"`
	Direction    ModelOutput  `json:"direction"`
	CrossAsset   ModelOutput  `json:"cross_asset"`
	OldDirection *ModelOutput `json:"old_direction,omitempty"`
	Scalper      *ModelOutput `json:"scalper,omitempty"`
}

type TradeSignal struct {
	Signal               string          `json:"signal"`
	RawSignal            string          `json:"raw_signal"`
	CrossAssetSignal     string          `json:"CrossAssetSignal"`
	Prediction           string          `json:"prediction"`
	CrossAssetPrediction string          `json:"cross_asset_prediction"`
	OptionType           string          `json:"option_type"`
	ValidUntil           string          `json:"valid_until"`
	Strike               float64         `json:"strike"`
	NiftySpot            float64         `json:"nifty_spot"`
	EntryEst             float64         `json:"entry_est"`
	TargetEst            float64         `json:"target_est"`
	SLEst                float64         `json:"sl_est"`
	TargetNifty          float64         `json:"target_nifty"`
	SLNifty              float64         `json:"sl_nifty"`
	Confidence           float64         `json:"confidence"`
	ProbUp               float64         `json:"prob_up"`
	ProbDown             float64         `json:"prob_down"`
	ProbSideways         float64         `json:"prob_sideways"`
	CrossAssetProbs      []float64       `json:"cross_asset_probs,omitempty"`
	OptionLTP            *float64        `json:"option_ltp"`
	PCR                  *float64        `json:"pcr"`
	OIConfirms           bool            `json:"oi_confirms"`
	EquityConfirms       bool            `json:"equity_confirms"`
	EnsembleMode         bool            `json:"ensemble_mode"`
	Support              float64         `json:"support"`
	Resistance           float64         `json:"resistance"`
	ModelAccuracy        float64         `json:"model_accuracy"`
	EquityReturn         float64         `json:"equity_return"`
	EquityAdvPct         float64         `json:"equity_advance_pct"`
	KeyFactors           []KeyFactor     `json:"key_factors"`
	Stability            StabilityInfo   `json:"stability"`
	Models               ModelsBreakdown `json:"models"`
	Error                string          `json:"error,omitempty"`
}

type StabilityStateResp struct {
	ConfirmedDirection, PendingDirection           string
	ConfirmedAt, CooldownUntil, FlipPreventionRate float64
	PendingCount, TotalRaw, FlipsPrevented         int
	ConfirmedSignals, ConfirmedFlips, HistoryDepth int
}

type HeatmapItem struct {
	Ticker        string  `json:"ticker"`
	LTP           float64 `json:"ltp"`
	ChangePercent float64 `json:"changePercent"`
}

type TickerRow struct {
	Script    string  `json:"Script"`
	Status    string  `json:"Status"`
	LTP       float64 `json:"LTP"`
	Chng      float64 `json:"Chng"`
	RSI       string  `json:"RSI"`
	MACD      string  `json:"MACD"`
	EMACross  string  `json:"EMACross"`
	VWAP      string  `json:"VWAP"`
	ST211     string  `json:"ST211"`
	ST142     string  `json:"ST142"`
	ST103     string  `json:"ST103"`
	Alligator string  `json:"Alligator"`
	ADX       string  `json:"ADX"`
	Volume    string  `json:"Vol"`
	FRAMA     string  `json:"FRAMA"`
	RS        string  `json:"RS"`
}

type MorningSignal struct {
	Prediction      string  `json:"prediction"`
	Confidence      float64 `json:"confidence"`
	FilteredConf    float64 `json:"filtered_confidence"`
	ProbGap         float64 `json:"prob_gap"`
	RawSignal       string  `json:"raw_signal"`
	OptionType      string  `json:"option_type"`
	NiftySpot       float64 `json:"nifty_spot"`
	PrevDayClose    float64 `json:"prev_day_close"`
	TodayOpen       float64 `json:"today_open"`
	GapPct          float64 `json:"gap_pct"`
	GapType         string  `json:"gap_type"`
	GapSeverity     string  `json:"gap_severity"`
	GapFilter       string  `json:"gap_filter"`
	PrevDayTrend    string  `json:"prev_day_trend"`
	ModelAccuracy   float64 `json:"model_accuracy"`
	GeneratedAt     string  `json:"generated_at"`
	ValidForMinutes int     `json:"valid_for_minutes"`
	Error           string  `json:"error,omitempty"`
}
