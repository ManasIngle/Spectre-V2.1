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

// smma computes a simple moving average (used as Alligator approximation)
func smma(src []float64, period int) []float64 {
	out := make([]float64, len(src))
	if len(src) < period {
		copy(out, src)
		return out
	}
	sum := 0.0
	for i := 0; i < period; i++ {
		sum += src[i]
		out[i] = sum / float64(i+1)
	}
	out[period-1] = sum / float64(period)
	for i := period; i < len(src); i++ {
		out[i] = (out[i-1]*float64(period-1) + src[i]) / float64(period)
	}
	return out
}

// alligatorSignal returns Buy/Sell/Neutral using Williams Alligator (13/8, 8/5, 5/3).
func alligatorSignal(bars []models.OHLCV) string {
	n := len(bars)
	if n < 30 {
		return "Neutral"
	}
	med := make([]float64, n)
	for i, b := range bars {
		med[i] = (b.High + b.Low) / 2
	}
	jaw := smma(med, 13)
	teeth := smma(med, 8)
	lips := smma(med, 5)
	// apply shifts: jaw+8, teeth+5, lips+3 — use the value from that many bars ago
	shiftOf := func(arr []float64, shift int) float64 {
		idx := n - 1 - shift
		if idx < 0 {
			return 0
		}
		return arr[idx]
	}
	j := shiftOf(jaw, 8)
	t := shiftOf(teeth, 5)
	l := shiftOf(lips, 3)
	if j == 0 || t == 0 || l == 0 {
		return "Neutral"
	}
	if l > t && t > j {
		return "Buy"
	}
	if l < t && t < j {
		return "Sell"
	}
	return "Neutral"
}

// framaSignal computes Fractal Adaptive Moving Average (period=16) and returns Buy/Sell.
func framaSignal(c []float64) string {
	period := 16
	n := len(c)
	if n < period+2 {
		return "-"
	}
	half := period / 2
	frama := make([]float64, n)
	copy(frama, c)
	for i := period; i < n; i++ {
		h1, l1 := c[i-period], c[i-period]
		for k := i - period; k < i-half; k++ {
			if c[k] > h1 {
				h1 = c[k]
			}
			if c[k] < l1 {
				l1 = c[k]
			}
		}
		h2, l2 := c[i-half], c[i-half]
		for k := i - half; k < i; k++ {
			if c[k] > h2 {
				h2 = c[k]
			}
			if c[k] < l2 {
				l2 = c[k]
			}
		}
		h3, l3 := c[i-period], c[i-period]
		for k := i - period; k < i; k++ {
			if c[k] > h3 {
				h3 = c[k]
			}
			if c[k] < l3 {
				l3 = c[k]
			}
		}
		n1 := (h1 - l1) / float64(half)
		n2 := (h2 - l2) / float64(half)
		n3 := (h3 - l3) / float64(period)
		d := 1.0
		if n1+n2 > 0 && n3 > 0 {
			d = (math.Log(n1+n2) - math.Log(n3)) / math.Log(2)
		}
		alpha := math.Exp(-4.6 * (d - 1))
		if alpha < 0.01 {
			alpha = 0.01
		} else if alpha > 1 {
			alpha = 1
		}
		frama[i] = alpha*c[i] + (1-alpha)*frama[i-1]
	}
	last := n - 1
	if c[last] > frama[last] {
		return "Buy"
	}
	return "Sell"
}

// rsSignal returns Buy if ticker outperformed Nifty since the start of the window.
func rsSignal(tickerCloses, niftyCloses []float64) string {
	if len(tickerCloses) < 2 || len(niftyCloses) < 2 {
		return "-"
	}
	n := len(tickerCloses)
	nn := len(niftyCloses)
	// align: use last min(n,nn) bars
	tStart := tickerCloses[n-min(n, nn)]
	nStart := niftyCloses[nn-min(n, nn)]
	if tStart == 0 || nStart == 0 {
		return "-"
	}
	tReturn := tickerCloses[n-1] / tStart
	nReturn := niftyCloses[nn-1] / nStart
	if nReturn == 0 {
		return "-"
	}
	if tReturn/nReturn > 1.0 {
		return "Buy"
	}
	return "Sell"
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// rsiSigLevel converts raw RSI value to multi-level signal.
func rsiSigLevel(rsi float64) string {
	switch {
	case rsi > 80:
		return "Buy++"
	case rsi > 70:
		return "Buy+"
	case rsi > 60:
		return "Buy"
	case rsi < 20:
		return "Sell++"
	case rsi < 30:
		return "Sell+"
	case rsi < 40:
		return "Sell"
	}
	return "Neutral"
}

// adxSigLevel computes proper ADX with DI+/DI- and returns multi-level signal.
func adxSigLevel(h, l, c []float64, period int) string {
	n := len(c)
	if n < period+2 {
		return "Neutral"
	}
	dmPlus := make([]float64, n)
	dmMinus := make([]float64, n)
	tr := make([]float64, n)
	tr[0] = h[0] - l[0]
	for i := 1; i < n; i++ {
		upMove := h[i] - h[i-1]
		downMove := l[i-1] - l[i]
		if upMove > downMove && upMove > 0 {
			dmPlus[i] = upMove
		}
		if downMove > upMove && downMove > 0 {
			dmMinus[i] = downMove
		}
		tr[i] = math.Max(h[i]-l[i], math.Max(math.Abs(h[i]-c[i-1]), math.Abs(l[i]-c[i-1])))
	}
	smoothTR := make([]float64, n)
	smoothPlus := make([]float64, n)
	smoothMinus := make([]float64, n)
	sum, sp, sm := 0.0, 0.0, 0.0
	for i := 0; i < period; i++ {
		sum += tr[i]
		sp += dmPlus[i]
		sm += dmMinus[i]
	}
	smoothTR[period-1] = sum
	smoothPlus[period-1] = sp
	smoothMinus[period-1] = sm
	for i := period; i < n; i++ {
		smoothTR[i] = smoothTR[i-1] - smoothTR[i-1]/float64(period) + tr[i]
		smoothPlus[i] = smoothPlus[i-1] - smoothPlus[i-1]/float64(period) + dmPlus[i]
		smoothMinus[i] = smoothMinus[i-1] - smoothMinus[i-1]/float64(period) + dmMinus[i]
	}
	adxArr := make([]float64, n)
	var adxSum float64
	var adxCount int
	for i := period; i < n; i++ {
		diPlus, diMinus := 0.0, 0.0
		if smoothTR[i] > 0 {
			diPlus = 100 * smoothPlus[i] / smoothTR[i]
			diMinus = 100 * smoothMinus[i] / smoothTR[i]
		}
		dx := 0.0
		if diPlus+diMinus > 0 {
			dx = 100 * math.Abs(diPlus-diMinus) / (diPlus + diMinus)
		}
		adxSum += dx
		adxCount++
		if adxCount >= period {
			adxArr[i] = adxSum / float64(period)
			adxSum -= adxArr[i-period+1]
		}
	}
	last := n - 1
	diPlus, diMinus := 0.0, 0.0
	if smoothTR[last] > 0 {
		diPlus = 100 * smoothPlus[last] / smoothTR[last]
		diMinus = 100 * smoothMinus[last] / smoothTR[last]
	}
	adxVal := adxArr[last]
	base := "Buy"
	if diMinus > diPlus {
		base = "Sell"
	}
	switch {
	case adxVal > 40:
		return base + "+++"
	case adxVal > 30:
		return base + "++"
	case adxVal > 25:
		return base + "+"
	}
	return base
}

// ─── Main Signal Computation ───────────────────────────────────────────────────

// ComputeSignals calculates all indicator signals for a slice of OHLCV bars.
// niftyBars is optional (pass nil to skip RS computation).
func ComputeSignals(bars []models.OHLCV, niftyBars []models.OHLCV) (models.TickerRow, error) {
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

	// VWAP (session)
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

	adxSig := adxSigLevel(h, l, c, 14)
	rsiSig := rsiSigLevel(rsi)
	alligSig := alligatorSignal(bars)
	framaSig := framaSignal(c)

	// Relative Strength vs Nifty
	rsSig := "-"
	if len(niftyBars) >= 2 {
		rsSig = rsSignal(c, closes(niftyBars))
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

	// Status: count Buy/Sell across all 10 signals
	allSigs := []string{vwapSig, alligSig, st211, st142, st103, adxSig, rsiSig, macdSig, framaSig, emaCross, rsSig}
	buyCount, sellCount := 0, 0
	for _, s := range allSigs {
		if len(s) >= 3 && s[:3] == "Buy" {
			buyCount++
		} else if len(s) >= 4 && s[:4] == "Sell" {
			sellCount++
		}
	}
	status := "Neutral"
	switch {
	case buyCount >= sellCount && buyCount >= 5:
		status = fmt.Sprintf("Buy [%d]", buyCount)
	case sellCount > buyCount && sellCount >= 5:
		status = fmt.Sprintf("Sell [%d]", sellCount)
	}

	chng := 0.0
	if last > 0 {
		chng = c[last] - c[last-1]
	}

	return models.TickerRow{
		LTP: c[last], Chng: chng, Status: status,
		RSI: rsiSig, MACD: macdSig, EMACross: emaCross,
		VWAP: vwapSig, ST211: st211, ST142: st142, ST103: st103,
		ADX: adxSig, Volume: volSig, Alligator: alligSig,
		FRAMA: framaSig, RS: rsSig,
	}, nil
}
