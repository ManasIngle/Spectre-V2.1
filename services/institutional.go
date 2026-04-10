package services

import (
	"math"
	"sync"

	"spectre/config"
	"spectre/models"
)

var instCache = NewTTLCache()

// InstitutionalOutlook computes all 9 modules and returns the composite verdict.
func InstitutionalOutlook() map[string]interface{} {
	if v, ok := instCache.Get("inst"); ok {
		return v.(map[string]interface{})
	}

	// Fetch Nifty data (5m bars for indicators)
	bars, _ := FetchOHLCV(config.NiftyTicker, "5m", "5d", config.CacheTTLFast)
	bars15m, _ := FetchOHLCV(config.NiftyTicker, "15m", "1mo", config.CacheTTLMed)

	// OI chain
	oi, _ := FetchOIChain()

	// Fetch intermarket tickers concurrently
	type tickResult struct {
		name    string
		price   float64
		changePct float64
	}
	interTickers := map[string]string{
		"India VIX": "^INDIAVIX",
		"S&P 500 Futures": "^GSPC",
		"Gold": "GC=F",
		"Crude Oil": "CL=F",
	}
	interCh := make(chan tickResult, len(interTickers))
	var wgInter sync.WaitGroup
	for name, ticker := range interTickers {
		wgInter.Add(1)
		go func(n, t string) {
			defer wgInter.Done()
			b, err := FetchOHLCV(t, "5m", "5d", config.CacheTTLFast)
			if err != nil || len(b) < 2 {
				interCh <- tickResult{name: n}
				return
			}
			last := b[len(b)-1].Close
			prev := b[0].Close
			chg := 0.0
			if prev > 0 {
				chg = (last - prev) / prev * 100
			}
			interCh <- tickResult{name: n, price: last, changePct: chg}
		}(name, ticker)
	}
	wgInter.Wait()
	close(interCh)
	interMarkets := map[string]map[string]float64{}
	var vixPrice, vixChange float64
	for r := range interCh {
		interMarkets[r.name] = map[string]float64{"price": r.price, "change_pct": r.changePct}
		if r.name == "India VIX" {
			vixPrice = r.price
			vixChange = r.changePct
		}
	}

	// Fetch top contributors for breadth and sector rotation
	contribCh := make(chan contribResult, len(config.TopContributors))
	var wgC sync.WaitGroup
	for _, t := range config.TopContributors {
		wgC.Add(1)
		go func(tk string) {
			defer wgC.Done()
			b, err := FetchOHLCV(tk, "5m", "5d", config.CacheTTLFast)
			if err != nil || len(b) < 2 {
				contribCh <- contribResult{ticker: tk}
				return
			}
			last := b[len(b)-1].Close
			prev := b[0].Close
			chg := 0.0
			if prev > 0 {
				chg = (last - prev) / prev * 100
			}
			contribCh <- contribResult{ticker: tk, change: chg}
		}(t)
	}
	wgC.Wait()
	close(contribCh)

	var contribChanges []contribResult
	for r := range contribCh {
		contribChanges = append(contribChanges, r)
	}

	modules := map[string]interface{}{}

	// ── Module 1: Smart Money ─────────────────────────────────────────
	modules["smart_money"] = computeSmartMoney(bars)

	// ── Module 2: Gamma Exposure ──────────────────────────────────────
	modules["gamma_exposure"] = computeGammaExposure(oi, bars)

	// ── Module 3: Intermarket ─────────────────────────────────────────
	modules["intermarket"] = computeIntermarket(interMarkets, vixPrice, vixChange)

	// ── Module 4: Breadth ─────────────────────────────────────────────
	modules["breadth"] = computeBreadth(contribChanges)

	// ── Module 5: Sector Rotation ─────────────────────────────────────
	modules["sector_rotation"] = computeSectorRotation(contribChanges)

	// ── Module 6: Volatility Regime ───────────────────────────────────
	modules["volatility_regime"] = computeVolatilityRegime(bars, vixPrice, vixChange)

	// ── Module 7: Momentum ────────────────────────────────────────────
	modules["momentum"] = computeMomentum(bars)

	// ── Module 8: Flow Proxy ──────────────────────────────────────────
	modules["flow_proxy"] = computeFlowProxy(contribChanges)

	// ── Module 9: Risk Assessment ─────────────────────────────────────
	modules["risk_assessment"] = computeRiskAssessment(bars, bars15m, oi)

	// ── Composite ─────────────────────────────────────────────────────
	composite := computeComposite(modules)

	result := map[string]interface{}{
		"composite": composite,
		"modules":   modules,
	}

	instCache.Set("inst", result, config.CacheTTLMed)
	return result
}

// ═══════════════════════════════════════════════════════════════════════
// Individual module implementations
// ═══════════════════════════════════════════════════════════════════════

func computeSmartMoney(bars []models.OHLCV) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A", "cmf": 0.0, "obv_trend": "N/A", "divergence": "None"}
	if len(bars) < 50 {
		return m
	}
	c := closes(bars)
	h := highs(bars)
	l := lows(bars)
	v := vols(bars)
	last := len(bars) - 1

	// CMF (Chaikin Money Flow) over 20 periods
	cmfSum, volSum := 0.0, 0.0
	for i := last - 19; i <= last; i++ {
		rng := h[i] - l[i]
		mfm := 0.0
		if rng > 0 {
			mfm = ((c[i] - l[i]) - (h[i] - c[i])) / rng
		}
		cmfSum += mfm * v[i]
		volSum += v[i]
	}
	cmf := 0.0
	if volSum > 0 {
		cmf = cmfSum / volSum
	}

	// OBV trend (last 20 bars)
	obv := make([]float64, len(bars))
	for i := 1; i < len(bars); i++ {
		if c[i] > c[i-1] {
			obv[i] = obv[i-1] + v[i]
		} else if c[i] < c[i-1] {
			obv[i] = obv[i-1] - v[i]
		} else {
			obv[i] = obv[i-1]
		}
	}
	obvTrend := "Flat"
	obvStart := obv[last-19]
	obvEnd := obv[last]
	if obvEnd > obvStart*1.02 {
		obvTrend = "Rising"
	} else if obvEnd < obvStart*0.98 {
		obvTrend = "Declining"
	}

	// Divergence: price up but OBV down or vice versa
	divergence := "None"
	priceUp := c[last] > c[last-19]
	obvUp := obvEnd > obvStart
	if priceUp && !obvUp {
		divergence = "Bearish Divergence"
	} else if !priceUp && obvUp {
		divergence = "Bullish Divergence"
	}

	score := cmf * 200 // Scale CMF to roughly -100..+100
	if obvTrend == "Rising" {
		score += 15
	} else if obvTrend == "Declining" {
		score -= 15
	}
	if divergence == "Bearish Divergence" {
		score -= 20
	} else if divergence == "Bullish Divergence" {
		score += 20
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	m["cmf"] = math.Round(cmf*10000) / 10000
	m["obv_trend"] = obvTrend
	m["divergence"] = divergence
	return m
}

func computeGammaExposure(oi *models.OIChainData, bars []models.OHLCV) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A", "gex_direction": "N/A", "pcr": 0.0, "max_pain": 0.0}
	if oi == nil || oi.Error != "" {
		return m
	}

	pcr := oi.PCR
	m["pcr"] = math.Round(pcr*100) / 100

	// GEX direction: net CE OI change vs PE OI change
	gexDir := "Neutral"
	if oi.TotalPEOIChg > oi.TotalCEOIChg*2 {
		gexDir = "Positive (Support)"
	} else if oi.TotalCEOIChg > oi.TotalPEOIChg*2 {
		gexDir = "Negative (Resistance)"
	}
	m["gex_direction"] = gexDir

	// Max pain: strike with highest total OI
	var maxPainStrike float64
	var maxTotalOI int64
	for _, s := range oi.Strikes {
		total := s.CEOI + s.PEOI
		if total > maxTotalOI {
			maxTotalOI = total
			maxPainStrike = s.Strike
		}
	}
	m["max_pain"] = maxPainStrike

	score := 0.0
	if pcr > 1.2 {
		score = 30
	} else if pcr > 1.0 {
		score = 15
	} else if pcr < 0.7 {
		score = -30
	} else if pcr < 0.9 {
		score = -15
	}
	if gexDir == "Positive (Support)" {
		score += 15
	} else if gexDir == "Negative (Resistance)" {
		score -= 15
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	return m
}

func computeIntermarket(markets map[string]map[string]float64, vixPrice, vixChange float64) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A", "vix": vixPrice, "vix_status": "N/A", "vix_change": vixChange, "markets": markets}

	vixStatus := "Low"
	if vixPrice > 25 {
		vixStatus = "High Fear"
	} else if vixPrice > 18 {
		vixStatus = "Elevated"
	} else if vixPrice > 12 {
		vixStatus = "Normal"
	}
	m["vix_status"] = vixStatus

	score := 0.0
	// VIX impact: high VIX = bearish for equities
	if vixPrice > 25 {
		score -= 40
	} else if vixPrice > 18 {
		score -= 15
	} else if vixPrice < 12 {
		score += 15
	}
	// VIX change: rising VIX = bearish
	if vixChange > 5 {
		score -= 20
	} else if vixChange < -5 {
		score += 20
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	return m
}

type contribResult struct {
	ticker string
	change float64
}

func computeBreadth(contribs []contribResult) map[string]interface{} {
	advancing, declining := 0, 0
	strongUp, strongDown := 0, 0
	for _, c := range contribs {
		if c.change > 0 {
			advancing++
			if c.change > 1.0 {
				strongUp++
			}
		} else if c.change < 0 {
			declining++
			if c.change < -1.0 {
				strongDown++
			}
		}
	}
	total := advancing + declining
	breadthPct := 0.0
	adRatio := 0.0
	if total > 0 {
		breadthPct = float64(advancing) / float64(total) * 100
		if declining > 0 {
			adRatio = float64(advancing) / float64(declining)
		} else {
			adRatio = float64(advancing)
		}
	}

	score := (breadthPct - 50) * 2 // 0..100 mapped to -100..+100
	score = math.Max(-100, math.Min(100, score))

	return map[string]interface{}{
		"score":       math.Round(score*10) / 10,
		"bias":        scoreToBias(score),
		"advancing":   advancing,
		"declining":   declining,
		"breadth_pct": math.Round(breadthPct*10) / 10,
		"ad_ratio":    math.Round(adRatio*100) / 100,
		"strong_up":   strongUp,
		"strong_down": strongDown,
	}
}

func computeSectorRotation(contribs []contribResult) map[string]interface{} {
	// Classify tickers: banking = cyclical, IT/pharma = defensive
	cyclical := []string{"HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "BAJFINANCE.NS"}
	defensive := []string{"ITC.NS", "INFY.NS", "TCS.NS", "BHARTIARTL.NS"}

	cyclicalSum, cyclicalN := 0.0, 0
	defensiveSum, defensiveN := 0.0, 0
	var sectors []map[string]interface{}

	for _, c := range contribs {
		name := DisplayName(c.ticker)
		sectors = append(sectors, map[string]interface{}{"name": name, "change": math.Round(c.change*100) / 100})
		for _, cy := range cyclical {
			if c.ticker == cy {
				cyclicalSum += c.change
				cyclicalN++
			}
		}
		for _, df := range defensive {
			if c.ticker == df {
				defensiveSum += c.change
				defensiveN++
			}
		}
	}

	cyclicalAvg, defensiveAvg := 0.0, 0.0
	if cyclicalN > 0 {
		cyclicalAvg = cyclicalSum / float64(cyclicalN)
	}
	if defensiveN > 0 {
		defensiveAvg = defensiveSum / float64(defensiveN)
	}

	regime := "Mixed"
	score := 0.0
	if cyclicalAvg > defensiveAvg+0.3 {
		regime = "Risk-On (Cyclical)"
		score = 25
	} else if defensiveAvg > cyclicalAvg+0.3 {
		regime = "Risk-Off (Defensive)"
		score = -25
	}
	if cyclicalAvg > 0 && defensiveAvg > 0 {
		score += 15
	} else if cyclicalAvg < 0 && defensiveAvg < 0 {
		score -= 15
	}
	score = math.Max(-100, math.Min(100, score))

	return map[string]interface{}{
		"score":         math.Round(score*10) / 10,
		"bias":          scoreToBias(score),
		"regime":        regime,
		"cyclical_avg":  math.Round(cyclicalAvg*100) / 100,
		"defensive_avg": math.Round(defensiveAvg*100) / 100,
		"sectors":       sectors,
	}
}

func computeVolatilityRegime(bars []models.OHLCV, vixLevel, vixChange float64) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A", "vix_level": vixLevel, "vix_zone": "N/A",
		"vol_trend": "N/A", "vol_ratio": 1.0, "realized_vol": 0.0, "nifty_vix_divergence": "None"}

	if len(bars) < 50 {
		return m
	}

	c := closes(bars)
	h := highs(bars)
	l := lows(bars)
	last := len(bars) - 1

	// Realized vol from ATR
	at := atr(h, l, c, 14)
	realizedVol := 0.0
	if c[last] > 0 {
		realizedVol = at[last] / c[last] * 100
	}
	m["realized_vol"] = math.Round(realizedVol*100) / 100

	// Vol trend: compare short ATR vs long ATR
	shortATR := atr(h, l, c, 5)
	volRatio := 1.0
	if at[last] > 0 {
		volRatio = shortATR[last] / at[last]
	}
	volTrend := "Stable"
	if volRatio > 1.3 {
		volTrend = "Expanding"
	} else if volRatio < 0.7 {
		volTrend = "Contracting"
	}
	m["vol_trend"] = volTrend
	m["vol_ratio"] = math.Round(volRatio*100) / 100

	// VIX zone
	vixZone := "Complacency"
	if vixLevel > 25 {
		vixZone = "High Fear"
	} else if vixLevel > 18 {
		vixZone = "Elevated Fear"
	} else if vixLevel > 12 {
		vixZone = "Normal"
	}
	m["vix_zone"] = vixZone

	// VIX-Nifty divergence
	priceUp := c[last] > c[last-10]
	vixUp := vixChange > 0
	div := "None"
	if priceUp && vixUp {
		div = "Bearish (VIX rising with price)"
	} else if !priceUp && !vixUp {
		div = "Bullish (VIX falling with price)"
	}
	m["nifty_vix_divergence"] = div

	score := 0.0
	if vixZone == "High Fear" {
		score = -40
	} else if vixZone == "Complacency" {
		score = 20
	}
	if volTrend == "Expanding" {
		score -= 15
	} else if volTrend == "Contracting" {
		score += 10
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	return m
}

func computeMomentum(bars []models.OHLCV) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A",
		"rsi_7": 50.0, "rsi_14": 50.0, "rsi_21": 50.0,
		"rsi_alignment": "N/A", "macd_alignment": "N/A", "ema_score": "N/A", "structure": "N/A"}

	if len(bars) < 50 {
		return m
	}

	c := closes(bars)
	last := len(bars) - 1

	rsi7 := rsiSlice(c, 7)
	rsi14 := rsiSlice(c, 14)
	rsi21 := rsiSlice(c, 21)
	m["rsi_7"] = math.Round(rsi7[last]*10) / 10
	m["rsi_14"] = math.Round(rsi14[last]*10) / 10
	m["rsi_21"] = math.Round(rsi21[last]*10) / 10

	// RSI alignment
	rsiAlign := "Mixed"
	if rsi7[last] > rsi14[last] && rsi14[last] > rsi21[last] {
		rsiAlign = "Bullish Cascade"
	} else if rsi7[last] < rsi14[last] && rsi14[last] < rsi21[last] {
		rsiAlign = "Bearish Cascade"
	}
	m["rsi_alignment"] = rsiAlign

	// MACD
	macdL, sig, _ := macdLine(c)
	macdAlign := "Neutral"
	if macdL[last] > sig[last] && macdL[last] > 0 {
		macdAlign = "Strong Bullish"
	} else if macdL[last] > sig[last] {
		macdAlign = "Bullish Cross"
	} else if macdL[last] < sig[last] && macdL[last] < 0 {
		macdAlign = "Strong Bearish"
	} else if macdL[last] < sig[last] {
		macdAlign = "Bearish Cross"
	}
	m["macd_alignment"] = macdAlign

	// EMA stack
	e9 := ema(c, 9)
	e21 := ema(c, 21)
	e50 := ema(c, 50)
	emaScore := "Tangled"
	if e9[last] > e21[last] && e21[last] > e50[last] {
		emaScore = "Bullish Stack"
	} else if e9[last] < e21[last] && e21[last] < e50[last] {
		emaScore = "Bearish Stack"
	}
	m["ema_score"] = emaScore

	// Price structure
	structure := "Ranging"
	if c[last] > e21[last] && c[last] > e50[last] {
		structure = "Uptrend"
	} else if c[last] < e21[last] && c[last] < e50[last] {
		structure = "Downtrend"
	}
	m["structure"] = structure

	// Score
	score := 0.0
	if rsiAlign == "Bullish Cascade" {
		score += 20
	} else if rsiAlign == "Bearish Cascade" {
		score -= 20
	}
	if emaScore == "Bullish Stack" {
		score += 25
	} else if emaScore == "Bearish Stack" {
		score -= 25
	}
	if structure == "Uptrend" {
		score += 15
	} else if structure == "Downtrend" {
		score -= 15
	}
	// Add RSI-14 bias
	if rsi14[last] > 60 {
		score += 10
	} else if rsi14[last] < 40 {
		score -= 10
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	return m
}

func computeFlowProxy(contribs []contribResult) map[string]interface{} {
	// Large-cap (top 5) vs mid-cap (bottom 5) proxy for institutional flow
	lcTickers := map[string]bool{"HDFCBANK.NS": true, "RELIANCE.NS": true, "ICICIBANK.NS": true, "INFY.NS": true, "TCS.NS": true}

	lcSum, lcN := 0.0, 0
	mcSum, mcN := 0.0, 0
	for _, c := range contribs {
		if lcTickers[c.ticker] {
			lcSum += c.change
			lcN++
		} else {
			mcSum += c.change
			mcN++
		}
	}

	lcAvg, mcAvg := 0.0, 0.0
	if lcN > 0 {
		lcAvg = lcSum / float64(lcN)
	}
	if mcN > 0 {
		mcAvg = mcSum / float64(mcN)
	}
	lcVsMc := lcAvg - mcAvg

	flowType := "Balanced"
	score := 0.0
	if lcVsMc > 0.5 {
		flowType = "Institutional Accumulation"
		score = 25
	} else if lcVsMc < -0.5 {
		flowType = "Retail Driven"
		score = -15
	}
	if lcAvg > 0 {
		score += 15
	} else if lcAvg < 0 {
		score -= 15
	}
	score = math.Max(-100, math.Min(100, score))

	return map[string]interface{}{
		"score":        math.Round(score*10) / 10,
		"bias":         scoreToBias(score),
		"flow_type":    flowType,
		"large_cap_avg": math.Round(lcAvg*100) / 100,
		"mid_cap_avg":  math.Round(mcAvg*100) / 100,
		"lc_vs_mc":     math.Round(lcVsMc*100) / 100,
	}
}

func computeRiskAssessment(bars, bars15m []models.OHLCV, oi *models.OIChainData) map[string]interface{} {
	m := map[string]interface{}{"score": 0.0, "bias": "N/A", "nifty_ltp": 0.0,
		"dist_from_20ema": 0.0, "dist_from_50ema": 0.0, "expected_range": "N/A",
		"rr_ratio": 0.0, "oi_support": "N/A", "oi_resistance": "N/A"}

	b := bars
	if len(bars15m) > 50 {
		b = bars15m // prefer 15m for higher-TF levels
	}
	if len(b) < 50 {
		return m
	}

	c := closes(b)
	h := highs(b)
	l := lows(b)
	last := len(b) - 1
	ltp := c[last]
	m["nifty_ltp"] = math.Round(ltp*100) / 100

	e20 := ema(c, 20)
	e50 := ema(c, 50)
	dist20 := 0.0
	dist50 := 0.0
	if e20[last] > 0 {
		dist20 = (ltp - e20[last]) / e20[last] * 100
	}
	if e50[last] > 0 {
		dist50 = (ltp - e50[last]) / e50[last] * 100
	}
	m["dist_from_20ema"] = math.Round(dist20*100) / 100
	m["dist_from_50ema"] = math.Round(dist50*100) / 100

	// Expected range from ATR
	at := atr(h, l, c, 14)
	expectedRange := at[last] * 2
	m["expected_range"] = math.Round(expectedRange*100) / 100

	// R:R ratio
	rrRatio := 0.0
	if at[last] > 0 {
		reward := expectedRange
		risk := at[last]
		rrRatio = reward / risk
	}
	m["rr_ratio"] = math.Round(rrRatio*100) / 100

	// OI support/resistance
	if oi != nil && oi.Error == "" {
		var maxPEStrike, maxCEStrike float64
		var maxPEOI, maxCEOI int64
		for _, s := range oi.Strikes {
			if s.PEOI > maxPEOI {
				maxPEOI = s.PEOI
				maxPEStrike = s.Strike
			}
			if s.CEOI > maxCEOI {
				maxCEOI = s.CEOI
				maxCEStrike = s.Strike
			}
		}
		m["oi_support"] = maxPEStrike
		m["oi_resistance"] = maxCEStrike
	}

	// Score: closer to 20 EMA is safer
	score := 0.0
	if math.Abs(dist20) < 0.5 {
		score += 15 // near mean
	} else if dist20 > 1.5 {
		score -= 20 // overextended up
	} else if dist20 < -1.5 {
		score -= 20 // overextended down
	}
	if rrRatio > 2 {
		score += 15
	} else if rrRatio < 1 {
		score -= 10
	}
	score = math.Max(-100, math.Min(100, score))

	m["score"] = math.Round(score*10) / 10
	m["bias"] = scoreToBias(score)
	return m
}

// ═══════════════════════════════════════════════════════════════════════
// Composite
// ═══════════════════════════════════════════════════════════════════════

func computeComposite(modules map[string]interface{}) map[string]interface{} {
	totalScore := 0.0
	count := 0
	bullish, bearish := 0, 0

	for _, mod := range modules {
		m := mod.(map[string]interface{})
		s, ok := m["score"].(float64)
		if !ok {
			continue
		}
		totalScore += s
		count++
		if s > 10 {
			bullish++
		} else if s < -10 {
			bearish++
		}
	}

	avgScore := 0.0
	if count > 0 {
		avgScore = totalScore / float64(count)
	}

	verdict := "NEUTRAL"
	if avgScore > 30 {
		verdict = "STRONGLY BULLISH"
	} else if avgScore > 15 {
		verdict = "BULLISH"
	} else if avgScore > 5 {
		verdict = "MILDLY BULLISH"
	} else if avgScore < -30 {
		verdict = "STRONGLY BEARISH"
	} else if avgScore < -15 {
		verdict = "BEARISH"
	} else if avgScore < -5 {
		verdict = "MILDLY BEARISH"
	}

	confidence := "LOW"
	agreementRatio := 0.0
	if count > 0 {
		majority := math.Max(float64(bullish), float64(bearish))
		agreementRatio = majority / float64(count)
		if agreementRatio > 0.7 {
			confidence = "HIGH"
		} else if agreementRatio > 0.5 {
			confidence = "MODERATE"
		}
	}

	return map[string]interface{}{
		"score":           math.Round(avgScore*10) / 10,
		"verdict":         verdict,
		"confidence":      confidence,
		"agreement_ratio": math.Round(agreementRatio*100) / 100,
	}
}

func scoreToBias(s float64) string {
	switch {
	case s > 30:
		return "Strongly Bullish"
	case s > 15:
		return "Bullish"
	case s > 5:
		return "Mildly Bullish"
	case s < -30:
		return "Strongly Bearish"
	case s < -15:
		return "Bearish"
	case s < -5:
		return "Mildly Bearish"
	default:
		return "Neutral"
	}
}
