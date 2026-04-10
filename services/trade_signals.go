package services

import (
"fmt"
"math"
"time"

"spectre/config"
"spectre/models"
)

var signalCache = NewTTLCache()

// GenerateTradeSignal fetches ML prediction + OI + direction, applies stability engine.
func GenerateTradeSignal() (*models.TradeSignal, error) {
	if v, ok := signalCache.Get("signal"); ok {
		return v.(*models.TradeSignal), nil
	}

	// Fetch Nifty 5m data for live LTP
	bars, err := FetchOHLCV(config.NiftyTicker, "5m", "5d", config.CacheTTLFast)
	if err != nil || len(bars) == 0 {
		return &models.TradeSignal{Error: "cannot fetch Nifty data", Signal: "NO TRADE", RawSignal: "NO TRADE"}, nil
	}
	ltp := bars[len(bars)-1].Close

	// Fetch ML prediction from Python sidecar
	mlPred, err := FetchMLPrediction()
	if err != nil {
		return &models.TradeSignal{Error: err.Error(), Signal: "NO TRADE", RawSignal: "NO TRADE", NiftySpot: ltp}, nil
	}

	// Fetch direction engine score for stability cross-check
	var dirScore *float64
	if dir, err := ComputeDirection(); err == nil && dir != nil {
		s := dir.Score
		dirScore = &s
	}

	// Run stability engine
	stability := ProcessPrediction(mlPred.Prediction, mlPred.Probs, dirScore)

	// Fetch OI chain
	oi, _ := FetchOIChain()

	// ATM strike (nearest 50)
	atm := math.Round(ltp/50) * 50
	support, resistance := atm-200, atm+200
	var optionLTP *float64
	var pcr *float64

	if oi != nil {
		if oi.TotalCEOI > 0 {
			p := oi.PCR; pcr = &p
		}
		for _, s := range oi.Strikes {
			if s.PEOI > int64(support) { support = s.Strike }
			if s.CEOI > int64(resistance) { resistance = s.Strike }
		}
	}

	// Build raw signal
	classMaps := [3]string{"DOWN", "SIDEWAYS", "UP"}
	pred := classMaps[mlPred.Prediction]
	conf := mlPred.Probs[mlPred.Prediction] * 100
	probDown := mlPred.Probs[0] * 100
	probSide := mlPred.Probs[1] * 100
	probUp := mlPred.Probs[2] * 100

	atrPct := 0.5
	if len(bars) > 14 {
		h := highs(bars); l := lows(bars); c := closes(bars)
		at := atr(h, l, c, 14)
		atrPct = at[len(at)-1] / ltp * 100
	}
	expectedMove := math.Round(ltp * atrPct / 100 * 2)

	rawSig, optType := "NO TRADE", "-"
	strike := atm
	entry, target, sl, targetNifty, slNifty := 0.0, 0.0, 0.0, ltp, ltp

	if pred == "UP" && conf > 35 {
		rawSig, optType = "BUY CE", "CE"
		if conf > 45 { strike = atm } else { strike = atm + 50 }
		entry = math.Round(ltp*0.005*10) / 10
		target = math.Round(entry*1.3*10) / 10
		sl = math.Round(entry*0.7*10) / 10
		targetNifty = math.Round(ltp + expectedMove)
		slNifty = math.Round(ltp - expectedMove*0.5)
	} else if pred == "DOWN" && conf > 35 {
		rawSig, optType = "BUY PE", "PE"
		if conf > 45 { strike = atm } else { strike = atm - 50 }
		entry = math.Round(ltp*0.005*10) / 10
		target = math.Round(entry*1.3*10) / 10
		sl = math.Round(entry*0.7*10) / 10
		targetNifty = math.Round(ltp - expectedMove)
		slNifty = math.Round(ltp + expectedMove*0.5)
	}

	// Look up option LTP from OI chain
	if oi != nil && optType != "-" {
		for _, s := range oi.Strikes {
			if int(s.Strike) == int(strike) {
				var lp float64
				if optType == "CE" { lp = s.CELTP } else { lp = s.PELTP }
				if lp > 0 { optionLTP = &lp }
				break
			}
		}
	}

	// OI confirms?
	oiConfirms := false
	if pcr != nil {
		if pred == "UP" && *pcr > 1.0 { oiConfirms = true }
		if pred == "DOWN" && *pcr < 0.9 { oiConfirms = true }
	}

	// Equity momentum from Nifty price action on current bars
	equityReturn := 0.0
	equityAdvPct := 0.0
	if len(bars) > 0 {
		last := bars[len(bars)-1]
		if last.Open > 0 {
			equityReturn = math.Round((last.Close-last.Open)/last.Open*10000) / 100
		}
		lookback := 20
		if lookback > len(bars) { lookback = len(bars) }
		advCount := 0
		for _, b := range bars[len(bars)-lookback:] {
			if b.Close > b.Open { advCount++ }
		}
		equityAdvPct = math.Round(float64(advCount)/float64(lookback)*1000) / 10
	}
	equityConfirms := (pred == "UP" && equityReturn > 0) || (pred == "DOWN" && equityReturn < 0)

	// Dynamic Hold Time (Valid Until) Calculation
	baseMinutes := 30.0
	if conf > 55 {
		baseMinutes = 90.0 // Strong trend conviction
	} else if conf > 45 {
		baseMinutes = 60.0 // Moderate conviction
	} else {
		baseMinutes = 20.0 // Weak conviction, quick scalp
	}

	// Adjust for volatility (ATR)
	// If ATR% > 0.6 (High volatility), market moves fast, cut hold time.
	if atrPct > 0.6 {
		baseMinutes *= 0.6
	} else if atrPct < 0.3 {
		// Low volatility, takes longer to hit targets
		baseMinutes *= 1.4
	}

	holdDuration := time.Duration(baseMinutes) * time.Minute
	validUntil := time.Now().Add(holdDuration).Format("03:04 PM")
	
	// Add it to the detail so the trader sees the exact expected duration
	stability.Detail = fmt.Sprintf("%s | Est. Hold: %.0f mins", stability.Detail, baseMinutes)

	result := &models.TradeSignal{
		Signal: stability.StableSignal, RawSignal: rawSig,
		CrossAssetSignal: classMaps[mlPred.CrossAssetPrediction], CrossAssetPrediction: classMaps[mlPred.CrossAssetPrediction],
		Prediction: pred, OptionType: optType,
		CrossAssetProbs: []float64{mlPred.CrossAssetProbs[0] * 100, mlPred.CrossAssetProbs[1] * 100, mlPred.CrossAssetProbs[2] * 100},
		Strike: strike, NiftySpot: ltp,
		EntryEst: entry, TargetEst: target, SLEst: sl,
		TargetNifty: targetNifty, SLNifty: slNifty,
		OptionLTP: optionLTP,
		Confidence: math.Round(conf*10) / 10,
		ProbUp: probUp, ProbDown: probDown, ProbSideways: probSide,
		OIConfirms: oiConfirms, EquityConfirms: equityConfirms, PCR: pcr,
		EquityReturn: equityReturn, EquityAdvPct: equityAdvPct,
		Support: support, Resistance: resistance,
		ModelAccuracy: mlPred.ModelAccuracy, EnsembleMode: mlPred.EnsembleMode,
		ValidUntil: validUntil, Stability: stability,
		KeyFactors: buildKeyFactors(mlPred.Probs, atrPct),
	}

	signalCache.Set("signal", result, config.SignalCacheTTL)
	return result, nil
}

func buildKeyFactors(probs [3]float64, atrPct float64) []models.KeyFactor {
	factors := []models.KeyFactor{
		{Factor: "Volatility", Value: fmt.Sprintf("%.2f%%", atrPct), Bias: func() string { if atrPct > 0.7 { return "High" }; return "Low" }()},
	}
	if probs[2] > 0.4 { factors = append(factors, models.KeyFactor{Factor: "ML Prob UP", Value: fmt.Sprintf("%.1f%%", probs[2]*100), Bias: "Bullish"}) }
	if probs[0] > 0.4 { factors = append(factors, models.KeyFactor{Factor: "ML Prob DOWN", Value: fmt.Sprintf("%.1f%%", probs[0]*100), Bias: "Bearish"}) }
	return factors
}
