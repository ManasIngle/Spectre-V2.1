package services

import (
"fmt"
"math"

"spectre/config"
"spectre/models"
)

var directionCache = NewTTLCache()

// ComputeDirection fetches multi-TF data and returns the directional bias score.
func ComputeDirection() (*models.DirectionResult, error) {
	if v, ok := directionCache.Get("dir"); ok {
		return v.(*models.DirectionResult), nil
	}

	tfOrder := []string{"1m", "3m", "5m", "15m"}
	allSignals := map[string]models.TFDetail{}

	for _, tf := range tfOrder {
		cfg := config.Timeframes[tf]
		bars, err := FetchOHLCV(config.NiftyTicker, cfg.Interval, cfg.Range, config.CacheTTLFast)
		if err != nil || len(bars) < 50 {
			continue
		}
		detail := computeTFDetail(bars)
		allSignals[tf] = detail
	}

	oi, _ := FetchOIChain()
	result := aggregateDirection(allSignals, oi)

	// LTP from fastest available TF
	for _, tf := range tfOrder {
		if d, ok := allSignals[tf]; ok && d.LTP > 0 {
			result.NiftyLTP = d.LTP
			break
		}
	}

	directionCache.Set("dir", result, config.DirCacheTTL)
	return result, nil
}

func computeTFDetail(bars []models.OHLCV) models.TFDetail {
	c := closes(bars)
	h := highs(bars)
	l := lows(bars)
	v := vols(bars)
	last := len(bars) - 1

	sigs := map[string]string{}

	// VWAP
	sumCV, sumV := 0.0, 0.0
	for i := range bars {
		sumCV += c[i] * v[i]; sumV += v[i]
	}
	vwapVal := 0.0
	if sumV > 0 { vwapVal = sumCV / sumV }
	if c[last] > vwapVal { sigs["VWAP"] = "Buy" } else { sigs["VWAP"] = "Sell" }

	// Supertrend
	sigs["ST_21_1"] = supertrendDir(bars, 21, 1.0)
	sigs["ST_14_2"] = supertrendDir(bars, 14, 2.0)
	sigs["ST_10_3"] = supertrendDir(bars, 10, 3.0)

	// RSI
	rsiVals := rsiSlice(c, 14)
	rsi := rsiVals[last]
	switch {
	case rsi > 70: sigs["RSI"] = "Sell+"
	case rsi > 60: sigs["RSI"] = "Buy"
	case rsi < 30: sigs["RSI"] = "Buy+"
	case rsi < 40: sigs["RSI"] = "Sell"
	default:        sigs["RSI"] = "Neutral"
	}

	// MACD
	_, _, hist := macdLine(c)
	if hist[last] > 0 { sigs["MACD"] = "Buy" } else { sigs["MACD"] = "Sell" }
	sigs["_macd_hist"] = fmt.Sprintf("%.4f", hist[last])

	// EMA cross
	e9 := ema(c, 9); e21 := ema(c, 21)
	if e9[last] > e21[last] { sigs["EMA_Cross"] = "Buy" } else { sigs["EMA_Cross"] = "Sell" }

	// ADX (simplified via DI)
	at := atr(h, l, c, 14)
	dmPlus := math.Max(h[last]-h[last-1], 0)
	dmMinus := math.Max(l[last-1]-l[last], 0)
	diPlus, diMinus := 0.0, 0.0
	if at[last] > 0 { diPlus = dmPlus / at[last] * 100; diMinus = dmMinus / at[last] * 100 }
	if diPlus > diMinus { sigs["ADX"] = "Buy" } else { sigs["ADX"] = "Sell" }

	// Volume
	avgVol := 0.0
	for i := last - 19; i <= last && i >= 0; i++ { avgVol += v[i] }
	avgVol /= 20
	if v[last] > avgVol*1.5 { sigs["Volume"] = "High" } else { sigs["Volume"] = "Normal" }

	// Alligator (simplified: 3 SMAs)
	sigs["Alligator"] = "Neutral"
	if len(c) >= 13 {
		jaw := smaLast(c, 13); teeth := smaLast(c, 8); lips := smaLast(c, 5)
		if lips > teeth && teeth > jaw { sigs["Alligator"] = "Buy" } else if lips < teeth && teeth < jaw { sigs["Alligator"] = "Sell" }
	}

	// FRAMA (approximated as EMA34)
	fr := ema(c, 34)
	if c[last] > fr[last] { sigs["FRAMA"] = "Buy" } else { sigs["FRAMA"] = "Sell" }

	// Score
	scoreKeys := []string{"VWAP","ST_21_1","ST_14_2","ST_10_3","Alligator","ADX","RSI","MACD","FRAMA","EMA_Cross"}
	raw := 0
	for _, k := range scoreKeys { raw += signalBias(sigs[k]) }

	mom := 0.0
	if last >= 5 && c[last-5] != 0 { mom = (c[last]-c[last-5]) / c[last-5] * 100 }
	chng := 0.0
	if last > 0 { chng = c[last] - c[last-1] }

	return models.TFDetail{
		RawScore: raw, Normalized: float64(raw) / float64(len(scoreKeys)) * 10,
		LTP: c[last], Change: chng, RSI: rsi,
		MACDHist: hist[last], Momentum: mom,
		VWAP: vwapVal, EMA9: e9[last], EMA21: e21[last],
		Signals: sigs,
	}
}

func smaLast(src []float64, period int) float64 {
	if len(src) < period { return 0 }
	sum := 0.0
	for _, v := range src[len(src)-period:] { sum += v }
	return sum / float64(period)
}

func aggregateDirection(tfs map[string]models.TFDetail, oi *models.OIChainData) *models.DirectionResult {
	total, weight := 0.0, 0.0
	for tf, cfg := range config.Timeframes {
		d, ok := tfs[tf]
		if !ok { continue }
		total += d.Normalized * cfg.Weight
		weight += cfg.Weight
	}
	score := 0.0
	if weight > 0 { score = total / weight }

	oiBias := 0.0
	oiAn := models.OIAnalysis{}
	if oi != nil && oi.Error == "" {
		pcr := oi.PCR
		switch {
		case pcr > 1.2: oiBias = 15
		case pcr > 1.0: oiBias = 8
		case pcr < 0.7: oiBias = -15
		case pcr < 0.9: oiBias = -8
		}
		if oi.TotalPEOIChg > oi.TotalCEOIChg { oiBias += 5 } else if oi.TotalCEOIChg > oi.TotalPEOIChg { oiBias -= 5 }

		oiAn.PCR = pcr
		if pcr > 1.0 { oiAn.PCRBias = "Bullish" } else if pcr < 0.9 { oiAn.PCRBias = "Bearish" } else { oiAn.PCRBias = "Neutral" }
		oiAn.CEOIChange = oi.TotalCEOIChg
		oiAn.PEOIChange = oi.TotalPEOIChg

		// Max strike OI
		for _, s := range oi.Strikes {
			if float64(s.CEOI) > oiAn.MaxCEStrike { oiAn.MaxCEStrike = float64(s.CEOI); oiAn.Resistance = s.Strike }
			if float64(s.PEOI) > oiAn.MaxPEStrike { oiAn.MaxPEStrike = float64(s.PEOI); oiAn.Support = s.Strike }
		}
	}

	combined := math.Max(-100, math.Min(100, score+oiBias))

	dir, action := "", ""
	switch {
	case combined > 30:  dir = "STRONGLY BULLISH";  action = "BUY CE / SELL PE"
	case combined > 15:  dir = "BULLISH";            action = "BUY CE"
	case combined > 5:   dir = "MILDLY BULLISH";     action = "BUY CE (with caution)"
	case combined > -5:  dir = "SIDEWAYS / NEUTRAL"; action = "AVOID or SELL STRADDLE"
	case combined > -15: dir = "MILDLY BEARISH";     action = "BUY PE (with caution)"
	case combined > -30: dir = "BEARISH";            action = "BUY PE"
	default:             dir = "STRONGLY BEARISH";   action = "BUY PE / SELL CE"
	}

	return &models.DirectionResult{
		Score: math.Round(combined*10) / 10,
		Direction: dir, SuggestedAction: action,
		Confidence: math.Min(math.Abs(combined), 100),
		IndicatorScore: math.Round(score*10) / 10,
		OIBias: oiBias, Timeframes: tfs, OIAnalysis: oiAn,
	}
}

