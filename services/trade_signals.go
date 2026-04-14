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
		return nil, fmt.Errorf("cannot fetch Nifty data: %w", err)
	}
	ltp := bars[len(bars)-1].Close

	mlPred, err := FetchMLPrediction()
	if err != nil {
		return nil, fmt.Errorf("ML prediction failed: %w", err)
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
			p := oi.PCR
			pcr = &p
		}
		var maxPEOI, maxCEOI int64
		for _, s := range oi.Strikes {
			if s.PEOI > maxPEOI {
				maxPEOI = s.PEOI
				support = s.Strike
			}
			if s.CEOI > maxCEOI {
				maxCEOI = s.CEOI
				resistance = s.Strike
			}
		}
	}

	// Build raw signal
	classMaps := [3]string{"DOWN", "SIDEWAYS", "UP"}
	predIdx := mlPred.Prediction
	if predIdx < 0 || predIdx > 2 {
		return &models.TradeSignal{Error: fmt.Sprintf("invalid prediction class: %d", predIdx), Signal: "NO TRADE", RawSignal: "NO TRADE", NiftySpot: ltp}, nil
	}
	pred := classMaps[predIdx]
	conf := mlPred.Probs[predIdx] * 100
	probDown := mlPred.Probs[0] * 100
	probSide := mlPred.Probs[1] * 100
	probUp := mlPred.Probs[2] * 100

	atrPct := 0.5
	if len(bars) > 14 {
		h := highs(bars)
		l := lows(bars)
		c := closes(bars)
		at := atr(h, l, c, 14)
		atrPct = at[len(at)-1] / ltp * 100
	}
	expectedMove := math.Round(ltp * atrPct / 100 * 2)

	rawSig, optType := "NO TRADE", "-"
	strike := atm
	entry, target, sl, targetNifty, slNifty := 0.0, 0.0, 0.0, ltp, ltp

	if pred == "UP" && conf > 35 {
		rawSig, optType = "BUY CE", "CE"
		if conf > 45 {
			strike = atm
		} else {
			strike = atm + 50
		}
		entry = math.Round(ltp*0.005*10) / 10
		target = math.Round(entry*1.3*10) / 10
		sl = math.Round(entry*0.7*10) / 10
		targetNifty = math.Round(ltp + expectedMove)
		slNifty = math.Round(ltp - expectedMove*0.5)
	} else if pred == "DOWN" && conf > 35 {
		rawSig, optType = "BUY PE", "PE"
		if conf > 45 {
			strike = atm
		} else {
			strike = atm - 50
		}
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
				if optType == "CE" {
					lp = s.CELTP
				} else {
					lp = s.PELTP
				}
				if lp > 0 {
					optionLTP = &lp
				}
				break
			}
		}
	}

	// OI confirms?
	oiConfirms := false
	if pcr != nil {
		if pred == "UP" && *pcr > 1.0 {
			oiConfirms = true
		}
		if pred == "DOWN" && *pcr < 0.9 {
			oiConfirms = true
		}
	}

	// Equity momentum: session open (first bar of day) vs current close
	equityReturn := 0.0
	equityAdvPct := 0.0
	if len(bars) > 0 {
		sessionOpen := bars[0].Open
		currentClose := bars[len(bars)-1].Close
		if sessionOpen > 0 {
			equityReturn = math.Round((currentClose-sessionOpen)/sessionOpen*10000) / 100
		}
		lookback := 20
		if lookback > len(bars) {
			lookback = len(bars)
		}
		advCount := 0
		for _, b := range bars[len(bars)-lookback:] {
			if b.Close > b.Open {
				advCount++
			}
		}
		equityAdvPct = math.Round(float64(advCount)/float64(lookback)*1000) / 10
	}
	equityConfirms := (pred == "UP" && equityReturn > 0) || (pred == "DOWN" && equityReturn < 0)

	// Dynamic Hold Time (Valid Until) — calibrated from backtest on 3,527 signals
	// BUY PE (DOWN): optimal exit at 8 min (win rate 47.9%, decays after)
	// BUY CE (UP): optimal exit at 30 min (win rate 63.1%)
	//   - conf > 60%: 8-10 min (signal is correct but move exhausts fast)
	//   - conf > 45%: 25 min (solid sweet spot)
	//   - conf < 45%: 15 min (weaker signal, limit exposure)
	var baseMinutes float64
	if pred == "DOWN" {
		baseMinutes = 8.0 // BUY PE — exit fast, direction decays quickly
	} else {
		// BUY CE
		if conf > 60 {
			baseMinutes = 10.0 // High confidence but move peaks early — take profit quickly
		} else if conf > 45 {
			baseMinutes = 25.0 // Solid confidence — allow the move to develop
		} else {
			baseMinutes = 15.0 // Weaker signal — limit time exposure
		}
	}

	// Adjust for volatility (ATR)
	// High volatility: market moves fast, target/SL hit sooner
	if atrPct > 0.6 {
		baseMinutes *= 0.7
	} else if atrPct < 0.3 {
		// Low volatility: takes longer to hit targets
		baseMinutes *= 1.3
	}

	holdDuration := time.Duration(baseMinutes) * time.Minute
	ist, err := time.LoadLocation("Asia/Kolkata")
	if err != nil {
		ist = time.FixedZone("IST", 5*3600+1800) // Fallback to explicitly defined +05:30 offset
	}
	nowIST := time.Now().In(ist)

	marketClose := time.Date(nowIST.Year(), nowIST.Month(), nowIST.Day(), 15, 30, 0, 0, ist)
	validUntilTime := nowIST.Add(holdDuration)
	if validUntilTime.After(marketClose) {
		validUntilTime = marketClose
	}
	if holdDuration < 5*time.Minute {
		holdDuration = 5 * time.Minute
		validUntilTime = nowIST.Add(holdDuration)
		if validUntilTime.After(marketClose) {
			validUntilTime = marketClose
		}
	}
	validUntil := validUntilTime.Format("03:04 PM")

	// Add it to the detail so the trader sees the exact expected duration
	stability.Detail = fmt.Sprintf("%s | Est. Hold: %.0f mins", stability.Detail, baseMinutes)

	crossIdx := mlPred.CrossAssetPrediction
	if crossIdx < 0 || crossIdx > 2 {
		crossIdx = predIdx
	}

	result := &models.TradeSignal{
		Signal: stability.StableSignal, RawSignal: rawSig,
		CrossAssetSignal: classMaps[crossIdx], CrossAssetPrediction: classMaps[crossIdx],
		Prediction: pred, OptionType: optType,
		CrossAssetProbs: []float64{mlPred.CrossAssetProbs[0] * 100, mlPred.CrossAssetProbs[1] * 100, mlPred.CrossAssetProbs[2] * 100},
		Strike:          strike, NiftySpot: ltp,
		EntryEst: entry, TargetEst: target, SLEst: sl,
		TargetNifty: targetNifty, SLNifty: slNifty,
		OptionLTP:  optionLTP,
		Confidence: math.Round(conf*10) / 10,
		ProbUp:     probUp, ProbDown: probDown, ProbSideways: probSide,
		OIConfirms: oiConfirms, EquityConfirms: equityConfirms, PCR: pcr,
		EquityReturn: equityReturn, EquityAdvPct: equityAdvPct,
		Support: support, Resistance: resistance,
		ModelAccuracy: mlPred.ModelAccuracy, EnsembleMode: mlPred.EnsembleMode,
		ValidUntil: validUntil, Stability: stability,
		KeyFactors: buildKeyFactors(mlPred.Probs, atrPct),
		Models:     buildModelsBreakdown(mlPred),
	}

	signalCache.Set("signal", result, config.SignalCacheTTL)
	return result, nil
}

func buildModelsBreakdown(mlPred *MLPrediction) models.ModelsBreakdown {
	classMaps := [3]string{"DOWN", "SIDEWAYS", "UP"}
	toModelOutput := func(mo ModelOutput) models.ModelOutput {
		sig := "NO TRADE"
		p := classMaps[mo.Prediction]
		if p == "UP" && mo.Probs[2]*100 > 35 {
			sig = "BUY CE"
		} else if p == "DOWN" && mo.Probs[0]*100 > 35 {
			sig = "BUY PE"
		}
		return models.ModelOutput{
			Prediction: mo.Prediction,
			Signal:     sig,
			Probs:      [3]float64{mo.Probs[0] * 100, mo.Probs[1] * 100, mo.Probs[2] * 100},
			Label:      mo.Label,
			Accuracy:   mo.Accuracy,
		}
	}

	bd := models.ModelsBreakdown{
		Rolling:    toModelOutput(mlPred.Models.Rolling),
		Direction:  toModelOutput(mlPred.Models.Direction),
		CrossAsset: toModelOutput(mlPred.Models.CrossAsset),
	}

	if mlPred.Models.OldDirection != nil {
		old := toModelOutput(*mlPred.Models.OldDirection)
		bd.OldDirection = &old
	}

	return bd
}

func buildKeyFactors(probs [3]float64, atrPct float64) []models.KeyFactor {
	factors := []models.KeyFactor{
		{Factor: "Volatility", Value: fmt.Sprintf("%.2f%%", atrPct), Bias: func() string {
			if atrPct > 0.7 {
				return "High"
			}
			return "Low"
		}()},
	}
	if probs[2] > 0.4 {
		factors = append(factors, models.KeyFactor{Factor: "ML Prob UP", Value: fmt.Sprintf("%.1f%%", probs[2]*100), Bias: "Bullish"})
	}
	if probs[0] > 0.4 {
		factors = append(factors, models.KeyFactor{Factor: "ML Prob DOWN", Value: fmt.Sprintf("%.1f%%", probs[0]*100), Bias: "Bearish"})
	}
	return factors
}
