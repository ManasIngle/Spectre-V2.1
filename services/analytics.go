package services

import (
	"fmt"
	"math"
	"sort"
	"time"
)

// Analytics Desk — read-only aggregations across logged trades and signals.

// ── Equity curve ─────────────────────────────────────────────────────────────

type EquityPoint struct {
	Date         string  `json:"date"`
	DayPnLPct    float64 `json:"day_pnl_pct"`
	DayPnLRupees float64 `json:"day_pnl_rupees"`
	CumPnLPct    float64 `json:"cum_pnl_pct"`
	CumPnLRupees float64 `json:"cum_pnl_rupees"`
	Trades       int     `json:"trades"`
	Wins         int     `json:"wins"`
	Losses       int     `json:"losses"`
}

// LoadEquityCurve returns daily P&L aggregates and the running cumulative.
func LoadEquityCurve(days int) ([]EquityPoint, error) {
	trades, err := LoadClosedTradesRange(days)
	if err != nil {
		return nil, err
	}

	type bucket struct {
		pnlPct, pnlRupees float64
		trades, wins, losses int
	}
	byDate := map[string]*bucket{}
	for _, t := range trades {
		b := byDate[t.Date]
		if b == nil {
			b = &bucket{}
			byDate[t.Date] = b
		}
		b.pnlPct += t.PnLPremiumPct
		b.pnlRupees += t.PnLRupees
		b.trades++
		if t.PnLPremiumPct > 0 {
			b.wins++
		} else if t.PnLPremiumPct < 0 {
			b.losses++
		}
	}

	dates := make([]string, 0, len(byDate))
	for d := range byDate {
		dates = append(dates, d)
	}
	sort.Strings(dates)

	out := []EquityPoint{}
	cumPct, cumRup := 0.0, 0.0
	for _, d := range dates {
		b := byDate[d]
		cumPct += b.pnlPct
		cumRup += b.pnlRupees
		out = append(out, EquityPoint{
			Date:         d,
			DayPnLPct:    b.pnlPct,
			DayPnLRupees: b.pnlRupees,
			CumPnLPct:    cumPct,
			CumPnLRupees: cumRup,
			Trades:       b.trades,
			Wins:         b.wins,
			Losses:       b.losses,
		})
	}
	return out, nil
}

// ── Suppressed signals ───────────────────────────────────────────────────────

type SuppressedSignal struct {
	Date       string  `json:"date"`
	Time       string  `json:"time"`
	RawSignal  string  `json:"raw_signal"`
	StableSig  string  `json:"stable_signal"`
	Confidence float64 `json:"confidence"`
	Spot       float64 `json:"spot"`
	Strike     float64 `json:"strike"`
	OptionType string  `json:"option_type"`
	ProbUp     float64 `json:"prob_up"`
	ProbDown   float64 `json:"prob_down"`
	ProbSide   float64 `json:"prob_side"`
	// What-would-have-been: spot move in the direction of the raw signal
	Move5m  float64 `json:"move_5m_pct"`
	Move15m float64 `json:"move_15m_pct"`
	Move30m float64 `json:"move_30m_pct"`
	// Verdict: was the suppression right? "FILTER_RIGHT" if move stayed flat,
	// "FILTER_WRONG" if move went strongly in the predicted direction.
	Verdict string `json:"verdict"`
}

// LoadSuppressedSignals returns minutes where the raw model said BUY CE/PE
// but the stability engine downgraded to NO TRADE (or any non-matching signal).
func LoadSuppressedSignals(date string) ([]SuppressedSignal, error) {
	rows, err := readCSV(signalCSVPath())
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}
	idx := headerIndex(rows[0])

	// Build spot trajectory for forward-looking move computation.
	spotByT := map[time.Time]float64{}
	loc, _ := time.LoadLocation("Asia/Kolkata")

	parsedRows := []struct {
		raw, stable string
		conf, spot, strike float64
		optType            string
		probU, probD, probS float64
		t                  time.Time
		timeStr            string
	}{}

	for _, row := range rows[1:] {
		if len(row) < len(rows[0]) {
			continue
		}
		if getCol(row, idx, "Date") != date {
			continue
		}
		ts := getCol(row, idx, "Time")
		t, err := time.ParseInLocation("2006-01-02 15:04:05", date+" "+ts, loc)
		if err != nil {
			continue
		}
		spot := parseFloat(getCol(row, idx, "Spot"))
		spotByT[t.Truncate(time.Minute)] = spot

		raw := getCol(row, idx, "Signal")
		stable := getCol(row, idx, "StableSignal")
		// "Suppressed" = raw was actionable but stable was not the same actionable signal
		if raw != "BUY CE" && raw != "BUY PE" {
			continue
		}
		if stable == raw {
			continue
		}

		parsedRows = append(parsedRows, struct {
			raw, stable string
			conf, spot, strike float64
			optType            string
			probU, probD, probS float64
			t                  time.Time
			timeStr            string
		}{
			raw: raw, stable: stable,
			conf:    parseFloat(getCol(row, idx, "Confidence")),
			spot:    spot,
			strike:  parseFloat(getCol(row, idx, "Strike")),
			optType: getCol(row, idx, "OptionType"),
			probU:   parseFloat(getCol(row, idx, "Prob_Up")),
			probD:   parseFloat(getCol(row, idx, "Prob_Down")),
			probS:   parseFloat(getCol(row, idx, "Prob_Side")),
			t:       t, timeStr: ts,
		})
	}

	out := []SuppressedSignal{}
	for _, r := range parsedRows {
		s5 := lookupSpot(spotByT, r.t, 5)
		s15 := lookupSpot(spotByT, r.t, 15)
		s30 := lookupSpot(spotByT, r.t, 30)

		mv5 := directionalMove(r.spot, s5, r.raw)
		mv15 := directionalMove(r.spot, s15, r.raw)
		mv30 := directionalMove(r.spot, s30, r.raw)

		verdict := "FILTER_NEUTRAL"
		if mv30 >= 0.30 {
			verdict = "FILTER_WRONG" // raw signal was right, filter blocked a winner
		} else if mv30 <= -0.30 {
			verdict = "FILTER_RIGHT" // raw signal was wrong; filter saved us
		}

		out = append(out, SuppressedSignal{
			Date: date, Time: r.timeStr,
			RawSignal: r.raw, StableSig: r.stable,
			Confidence: r.conf, Spot: r.spot,
			Strike: r.strike, OptionType: r.optType,
			ProbUp: r.probU, ProbDown: r.probD, ProbSide: r.probS,
			Move5m: mv5, Move15m: mv15, Move30m: mv30,
			Verdict: verdict,
		})
	}
	return out, nil
}

func lookupSpot(spotByT map[time.Time]float64, base time.Time, offsetMin int) float64 {
	target := base.Truncate(time.Minute).Add(time.Duration(offsetMin) * time.Minute)
	for off := 0; off <= 2; off++ {
		if v, ok := spotByT[target.Add(time.Duration(off)*time.Minute)]; ok && v != 0 {
			return v
		}
		if v, ok := spotByT[target.Add(time.Duration(-off)*time.Minute)]; ok && v != 0 {
			return v
		}
	}
	return 0
}

func directionalMove(entry, future float64, signal string) float64 {
	if entry == 0 || future == 0 {
		return 0
	}
	pct := (future - entry) / entry * 100
	if signal == "BUY PE" {
		return -pct
	}
	return pct
}

// ── Suppressed signal detail (for chart in UI) ───────────────────────────────

type SuppressedDetail struct {
	Signal     SuppressedSignal       `json:"signal"`
	SpotSeries []JournalSpotPoint     `json:"spot_series"`
}

func LoadSuppressedDetail(date, timeStr string) (*SuppressedDetail, error) {
	all, err := LoadSuppressedSignals(date)
	if err != nil {
		return nil, err
	}
	var hit *SuppressedSignal
	for i := range all {
		if all[i].Time == timeStr {
			hit = &all[i]
			break
		}
	}
	if hit == nil {
		return nil, fmt.Errorf("suppressed signal not found: %s %s", date, timeStr)
	}

	loc, _ := time.LoadLocation("Asia/Kolkata")
	baseT, _ := time.ParseInLocation("2006-01-02 15:04:05", date+" "+timeStr, loc)
	startT := baseT.Add(-10 * time.Minute)
	endT := baseT.Add(40 * time.Minute)
	series := loadSpotSeries(date, startT, endT, baseT, baseT)
	return &SuppressedDetail{Signal: *hit, SpotSeries: series}, nil
}

// ── Scorecard A/B comparison ─────────────────────────────────────────────────

type ScorecardCompareEntry struct {
	Model  string  `json:"model"`
	A      float64 `json:"acc_a"`
	B      float64 `json:"acc_b"`
	Delta  float64 `json:"delta"`
	NA     int     `json:"n_a"`
	NB     int     `json:"n_b"`
}

// CompareScorecard aggregates per-model accuracy across two date ranges.
// Each range is given as inclusive start/end YYYY-MM-DD strings.
func CompareScorecard(startA, endA, startB, endB string) ([]ScorecardCompareEntry, error) {
	all, err := LoadScorecard(0)
	if err != nil {
		return nil, err
	}

	type acc struct {
		correctSum float64
		nSum       int
	}
	a := map[string]*acc{}
	b := map[string]*acc{}

	for _, r := range all {
		if r.Directional == 0 {
			continue
		}
		if r.Date >= startA && r.Date <= endA {
			x := a[r.Model]
			if x == nil {
				x = &acc{}
				a[r.Model] = x
			}
			x.correctSum += r.DirAccPct * float64(r.Directional)
			x.nSum += r.Directional
		}
		if r.Date >= startB && r.Date <= endB {
			x := b[r.Model]
			if x == nil {
				x = &acc{}
				b[r.Model] = x
			}
			x.correctSum += r.DirAccPct * float64(r.Directional)
			x.nSum += r.Directional
		}
	}

	models := []string{"Rolling", "Direction", "CrossAsset", "OldDir", "Scalper", "Ensemble"}
	out := []ScorecardCompareEntry{}
	for _, m := range models {
		var accA, accB float64
		nA, nB := 0, 0
		if x := a[m]; x != nil && x.nSum > 0 {
			accA = x.correctSum / float64(x.nSum)
			nA = x.nSum
		}
		if x := b[m]; x != nil && x.nSum > 0 {
			accB = x.correctSum / float64(x.nSum)
			nB = x.nSum
		}
		if nA == 0 && nB == 0 {
			continue
		}
		out = append(out, ScorecardCompareEntry{
			Model: m, A: accA, B: accB, Delta: accB - accA, NA: nA, NB: nB,
		})
	}
	return out, nil
}

// ── Helpers ──────────────────────────────────────────────────────────────────

func roundTo(v float64, decimals int) float64 {
	mult := math.Pow(10, float64(decimals))
	return math.Round(v*mult) / mult
}
