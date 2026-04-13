package services

import (
	"fmt"
	"math"

	"spectre/models"
)

// ─── Helpers ──────────────────────────────────────────────────────────────────

func closes(bars []models.OHLCV) []float64 {
	out := make([]float64, len(bars))
	for i, b := range bars {
		out[i] = b.Close
	}
	return out
}

func highs(bars []models.OHLCV) []float64 {
	out := make([]float64, len(bars))
	for i, b := range bars {
		out[i] = b.High
	}
	return out
}

func lows(bars []models.OHLCV) []float64 {
	out := make([]float64, len(bars))
	for i, b := range bars {
		out[i] = b.Low
	}
	return out
}

func vols(bars []models.OHLCV) []float64 {
	out := make([]float64, len(bars))
	for i, b := range bars {
		out[i] = b.Volume
	}
	return out
}

func ema(src []float64, period int) []float64 {
	out := make([]float64, len(src))
	if len(src) < period {
		for i := range src {
			out[i] = src[i]
		}
		return out
	}
	sum := 0.0
	for i := 0; i < period; i++ {
		sum += src[i]
	}
	sma := sum / float64(period)
	for i := 0; i < period; i++ {
		out[i] = sma
	}
	k := 2.0 / float64(period+1)
	for i := period; i < len(src); i++ {
		out[i] = src[i]*k + out[i-1]*(1-k)
	}
	return out
}

func rsiSlice(src []float64, period int) []float64 {
	out := make([]float64, len(src))
	if len(src) < period+1 {
		return out
	}
	var avgGain, avgLoss float64
	for i := 1; i <= period; i++ {
		d := src[i] - src[i-1]
		if d > 0 {
			avgGain += d
		} else {
			avgLoss -= d
		}
	}
	avgGain /= float64(period)
	avgLoss /= float64(period)
	for i := period; i < len(src); i++ {
		if i > period {
			d := src[i] - src[i-1]
			g, l := 0.0, 0.0
			if d > 0 {
				g = d
			} else {
				l = -d
			}
			avgGain = (avgGain*float64(period-1) + g) / float64(period)
			avgLoss = (avgLoss*float64(period-1) + l) / float64(period)
		}
		if avgLoss == 0 {
			out[i] = 100
		} else {
			rs := avgGain / avgLoss
			out[i] = 100 - 100/(1+rs)
		}
	}
	return out
}

func atr(h, l, c []float64, period int) []float64 {
	n := len(h)
	tr := make([]float64, n)
	tr[0] = h[0] - l[0]
	for i := 1; i < n; i++ {
		tr[i] = math.Max(h[i]-l[i], math.Max(math.Abs(h[i]-c[i-1]), math.Abs(l[i]-c[i-1])))
	}
	out := make([]float64, n)
	sum := 0.0
	for i := 0; i < period && i < n; i++ {
		sum += tr[i]
	}
	out[period-1] = sum / float64(period)
	for i := period; i < n; i++ {
		out[i] = (out[i-1]*float64(period-1) + tr[i]) / float64(period)
	}
	return out
}

func macdLine(src []float64) (macdL, signal, hist []float64) {
	fast := ema(src, 12)
	slow := ema(src, 26)
	macdL = make([]float64, len(src))
	for i := range src {
		macdL[i] = fast[i] - slow[i]
	}
	signal = ema(macdL, 9)
	hist = make([]float64, len(src))
	for i := range src {
		hist[i] = macdL[i] - signal[i]
	}
	return
}

func vwapDev(bars []models.OHLCV) float64 {
	if len(bars) < 20 {
		return 0
	}
	c := closes(bars)
	v := vols(bars)
	sumCV, sumV := 0.0, 0.0
	for i := len(bars) - 20; i < len(bars); i++ {
		sumCV += c[i] * v[i]
		sumV += v[i]
	}
	if sumV == 0 {
		return 0
	}
	vw := sumCV / sumV
	last := c[len(c)-1]
	return (last - vw) / last * 100
}

func supertrendDir(bars []models.OHLCV, period int, multiplier float64) string {
	if len(bars) < period+2 {
		return "Neutral"
	}
	h := highs(bars)
	l := lows(bars)
	c := closes(bars)
	at := atr(h, l, c, period)
	n := len(bars)

	var prevUpper, prevLower, prevDir float64
	for i := period; i < n; i++ {
		mid := (h[i] + l[i]) / 2
		upper := mid + multiplier*at[i]
		lower := mid - multiplier*at[i]

		if i > period {
			if upper < prevUpper {
				upper = prevUpper
			}
			if lower > prevLower {
				lower = prevLower
			}
		}

		dir := 1.0
		if prevUpper < prevLower && c[i] < prevUpper {
			dir = -1
		} else if prevLower > prevUpper && c[i] > prevLower {
			dir = 1
		} else {
			dir = prevDir
		}

		prevUpper = upper
		prevLower = lower
		prevDir = dir
	}

	if prevDir == 1 {
		return "Buy"
	}
	return "Sell"
}

// signalBias converts raw signal string to +1/0/-1
func signalBias(s string) int {
	switch s {
	case "Buy+++":
		return 4
	case "Buy++":
		return 3
	case "Buy+":
		return 2
	case "Buy":
		return 1
	case "Sell":
		return -1
	case "Sell+":
		return -2
	case "Sell++":
		return -3
	case "Sell+++":
		return -4
	}
	return 0
}

// ─── Main Signal Computation ───────────────────────────────────────────────────

// ComputeSignals calculates all indicator signals for a slice of OHLCV bars.
func ComputeSignals(bars []models.OHLCV) (models.TickerRow, error) {
	if len(bars) < 50 {
		return models.TickerRow{}, fmt.Errorf("insufficient bars: %d", len(bars))
	}

	c := closes(bars)
	h := highs(bars)
	l := lows(bars)
	v := vols(bars)
	last := len(bars) - 1

	rsiVals := rsiSlice(c, 14)
	rsi := rsiVals[last]

	ema9v := ema(c, 9)
	ema21v := ema(c, 21)
	emaCross := "Buy"
	if ema9v[last] < ema21v[last] {
		emaCross = "Sell"
	}

	_, _, histArr := macdLine(c)
	macdSig := "Buy"
	if histArr[last] < 0 {
		macdSig = "Sell"
	}

	// VWAP
	sumCV, sumV := 0.0, 0.0
	for i := range bars {
		sumCV += c[i] * v[i]
		sumV += v[i]
	}
	vwapVal := 0.0
	if sumV > 0 {
		vwapVal = sumCV / sumV
	}
	vwapSig := "Buy"
	if c[last] < vwapVal {
		vwapSig = "Sell"
	}

	st211 := supertrendDir(bars, 21, 1.0)
	st142 := supertrendDir(bars, 14, 2.0)
	st103 := supertrendDir(bars, 10, 3.0)

	// ADX simplified
	adxSig := "Neutral"
	at := atr(h, l, c, 14)
	if at[last] > 0 {
		if c[last] > c[last-1] {
			adxSig = "Buy"
		} else {
			adxSig = "Sell"
		}
	}

	// RSI signal
	rsiSig := "Neutral"
	if rsi > 60 {
		rsiSig = "Buy"
	} else if rsi < 40 {
		rsiSig = "Sell"
	}

	// Volume
	avgVol := 0.0
	for i := last - 19; i <= last && i >= 0; i++ {
		avgVol += v[i]
	}
	avgVol /= 20
	volSig := "Neutral"
	if v[last] > avgVol*1.5 {
		volSig = "High Vol"
	}

	sigs := []string{vwapSig, st211, st142, st103, adxSig, rsiSig, macdSig, emaCross}
	buyCount, sellCount := 0, 0
	for _, s := range sigs {
		if s == "Buy" {
			buyCount++
		} else if s == "Sell" {
			sellCount++
		}
	}
	status := "Neutral"
	switch {
	case buyCount >= 8:
		status = fmt.Sprintf("Buy [%d]", buyCount)
	case buyCount >= 5:
		status = fmt.Sprintf("Buy [%d]", buyCount)
	case sellCount >= 8:
		status = fmt.Sprintf("Sell [%d]", sellCount)
	case sellCount >= 5:
		status = fmt.Sprintf("Sell [%d]", sellCount)
	}

	chng := 0.0
	if last > 0 {
		chng = c[last] - c[last-1]
	}

	return models.TickerRow{
		LTP: c[last], Change: chng, Status: status,
		RSI: rsiSig, MACD: macdSig, EMACross: emaCross,
		VWAP: vwapSig, ST211: st211, ST142: st142, ST103: st103,
		ADX: adxSig, Volume: volSig, Alligator: "Neutral",
	}, nil
}
