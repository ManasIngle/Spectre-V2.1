package services

import (
	"encoding/csv"
	"fmt"
	"os"
	"sort"
	"time"
)

// Trade Journal — read-only views into executed_trades.csv enriched with
// the spot + premium trajectory around each trade. Used by the Journal UI.

type JournalTradeSummary struct {
	Date          string  `json:"date"`
	EntryTime     string  `json:"entry_time"`
	ExitTime      string  `json:"exit_time"`
	Strike        float64 `json:"strike"`
	OptionType    string  `json:"option_type"`
	Signal        string  `json:"signal"`
	Confidence    float64 `json:"confidence"`
	EntrySpot     float64 `json:"entry_spot"`
	ExitSpot      float64 `json:"exit_spot"`
	EntryPremium  float64 `json:"entry_premium"`
	ExitPremium   float64 `json:"exit_premium"`
	TargetNifty   float64 `json:"target_nifty"`
	SLNifty       float64 `json:"sl_nifty"`
	ExitReason    string  `json:"exit_reason"`
	HoldMin       float64 `json:"hold_min"`
	PnLSpotPct    float64 `json:"pnl_spot_pct"`
	PnLPremiumPct float64 `json:"pnl_premium_pct"`
	PnLRupees     float64 `json:"pnl_rupees"`
	RollingSig    string  `json:"rolling_sig"`
	DirectionSig  string  `json:"direction_sig"`
	CrossAssetSig string  `json:"cross_asset_sig"`
}

type JournalSpotPoint struct {
	Time  string  `json:"time"`
	Spot  float64 `json:"spot"`
	Phase string  `json:"phase"` // "before" | "during" | "after"
}

type JournalPremiumPoint struct {
	Time    string  `json:"time"`
	Premium float64 `json:"premium"`
	Phase   string  `json:"phase"` // "during" | "after"
}

type JournalDetail struct {
	Trade       JournalTradeSummary    `json:"trade"`
	SpotSeries  []JournalSpotPoint     `json:"spot_series"`
	PremSeries  []JournalPremiumPoint  `json:"prem_series"`
	BestPremium float64                `json:"best_premium"`
	BestExitMin int                    `json:"best_exit_min"`
	MFEPct      float64                `json:"mfe_pct"`
	MAEPct      float64                `json:"mae_pct"`
	Efficiency  float64                `json:"efficiency_pct"` // actual / best
}

// LoadClosedTradesForDate returns all closed trades on a given date (newest first).
func LoadClosedTradesForDate(date string) ([]JournalTradeSummary, error) {
	rows, err := readCSV(executedTradesCSVPath())
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}
	idx := headerIndex(rows[0])

	out := []JournalTradeSummary{}
	for _, row := range rows[1:] {
		if len(row) < len(rows[0]) {
			continue
		}
		if getCol(row, idx, "Kind") != "EXIT" {
			continue
		}
		if getCol(row, idx, "Date") != date {
			continue
		}
		out = append(out, parseTradeRow(row, idx))
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EntryTime > out[j].EntryTime })
	return out, nil
}

// LoadClosedTradesRange returns trades within the last N days (most recent first).
func LoadClosedTradesRange(days int) ([]JournalTradeSummary, error) {
	rows, err := readCSV(executedTradesCSVPath())
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}
	idx := headerIndex(rows[0])

	loc, _ := time.LoadLocation("Asia/Kolkata")
	cutoff := time.Now().In(loc).AddDate(0, 0, -days).Format("2006-01-02")

	out := []JournalTradeSummary{}
	for _, row := range rows[1:] {
		if len(row) < len(rows[0]) {
			continue
		}
		if getCol(row, idx, "Kind") != "EXIT" {
			continue
		}
		if getCol(row, idx, "Date") < cutoff {
			continue
		}
		out = append(out, parseTradeRow(row, idx))
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Date != out[j].Date {
			return out[i].Date > out[j].Date
		}
		return out[i].EntryTime > out[j].EntryTime
	})
	return out, nil
}

// LoadTradeDetail finds a specific trade and enriches it with spot + premium trajectories.
func LoadTradeDetail(date, entryTime string, strike float64, optType string) (*JournalDetail, error) {
	trades, err := LoadClosedTradesForDate(date)
	if err != nil {
		return nil, err
	}
	var trade *JournalTradeSummary
	for i := range trades {
		if trades[i].EntryTime == entryTime &&
			trades[i].Strike == strike &&
			trades[i].OptionType == optType {
			trade = &trades[i]
			break
		}
	}
	if trade == nil {
		return nil, fmt.Errorf("trade not found: %s %s %.0f %s", date, entryTime, strike, optType)
	}

	loc, _ := time.LoadLocation("Asia/Kolkata")
	entryT, _ := time.ParseInLocation("2006-01-02 15:04:05", date+" "+entryTime, loc)
	exitT, _ := time.ParseInLocation("2006-01-02 15:04:05", date+" "+trade.ExitTime, loc)

	// Spot series: entry-10min → exit+10min
	spotStart := entryT.Add(-10 * time.Minute)
	spotEnd := exitT.Add(10 * time.Minute)
	spotSeries := loadSpotSeries(date, spotStart, spotEnd, entryT, exitT)

	// Premium series: entry → exit+30min
	premEnd := exitT.Add(30 * time.Minute)
	premSeries := loadPremiumSeries(date, strike, optType, entryT, premEnd, exitT)

	// Compute MFE/MAE/best from premium series during trade
	var bestPrem, mfe, mae float64
	bestPrem = trade.EntryPremium
	bestExitMin := 0
	for _, p := range premSeries {
		if p.Phase != "during" || p.Premium == 0 {
			continue
		}
		pnl := 0.0
		if trade.EntryPremium > 0 {
			pnl = (p.Premium - trade.EntryPremium) / trade.EntryPremium * 100
		}
		if p.Premium > bestPrem {
			bestPrem = p.Premium
			pT, _ := time.ParseInLocation("2006-01-02 15:04:05", date+" "+p.Time, loc)
			bestExitMin = int(pT.Sub(entryT).Minutes())
		}
		if pnl > mfe {
			mfe = pnl
		}
		if pnl < mae {
			mae = pnl
		}
	}

	efficiency := 0.0
	bestPnL := 0.0
	if trade.EntryPremium > 0 {
		bestPnL = (bestPrem - trade.EntryPremium) / trade.EntryPremium * 100
	}
	if bestPnL > 0 {
		efficiency = trade.PnLPremiumPct / bestPnL * 100
	}

	return &JournalDetail{
		Trade:       *trade,
		SpotSeries:  spotSeries,
		PremSeries:  premSeries,
		BestPremium: bestPrem,
		BestExitMin: bestExitMin,
		MFEPct:      mfe,
		MAEPct:      mae,
		Efficiency:  efficiency,
	}, nil
}

func loadSpotSeries(date string, start, end, entryT, exitT time.Time) []JournalSpotPoint {
	rows, err := readCSV(signalCSVPath())
	if err != nil {
		return nil
	}
	if len(rows) < 2 {
		return nil
	}
	idx := headerIndex(rows[0])
	loc, _ := time.LoadLocation("Asia/Kolkata")

	out := []JournalSpotPoint{}
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
		if t.Before(start) || t.After(end) {
			continue
		}
		spot := parseFloat(getCol(row, idx, "Spot"))
		if spot == 0 {
			continue
		}
		phase := "after"
		switch {
		case t.Before(entryT):
			phase = "before"
		case !t.After(exitT):
			phase = "during"
		}
		out = append(out, JournalSpotPoint{Time: ts, Spot: spot, Phase: phase})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Time < out[j].Time })
	return out
}

func loadPremiumSeries(date string, strike float64, optType string, entryT, end, exitT time.Time) []JournalPremiumPoint {
	rows, err := readCSV(optionArrayCSVPath())
	if err != nil {
		return nil
	}
	if len(rows) < 2 {
		return nil
	}
	idx := headerIndex(rows[0])
	loc, _ := time.LoadLocation("Asia/Kolkata")

	out := []JournalPremiumPoint{}
	for _, row := range rows[1:] {
		if len(row) < len(rows[0]) {
			continue
		}
		if getCol(row, idx, "Date") != date {
			continue
		}
		if parseFloat(getCol(row, idx, "Strike")) != strike {
			continue
		}
		if getCol(row, idx, "OptionType") != optType {
			continue
		}
		ts := getCol(row, idx, "Time")
		t, err := time.ParseInLocation("2006-01-02 15:04:05", date+" "+ts, loc)
		if err != nil {
			continue
		}
		if t.Before(entryT) || t.After(end) {
			continue
		}
		ltp := parseFloat(getCol(row, idx, "LTP"))
		phase := "after"
		if !t.After(exitT) {
			phase = "during"
		}
		out = append(out, JournalPremiumPoint{Time: ts, Premium: ltp, Phase: phase})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Time < out[j].Time })
	return out
}

func parseTradeRow(row []string, idx map[string]int) JournalTradeSummary {
	return JournalTradeSummary{
		Date:          getCol(row, idx, "Date"),
		EntryTime:     getCol(row, idx, "EntryTime"),
		ExitTime:      getCol(row, idx, "ExitTime"),
		Strike:        parseFloat(getCol(row, idx, "Strike")),
		OptionType:    getCol(row, idx, "OptionType"),
		Signal:        getCol(row, idx, "Signal"),
		Confidence:    parseFloat(getCol(row, idx, "Confidence")),
		EntrySpot:     parseFloat(getCol(row, idx, "EntrySpot")),
		ExitSpot:      parseFloat(getCol(row, idx, "ExitSpot")),
		EntryPremium:  parseFloat(getCol(row, idx, "EntryPremium")),
		ExitPremium:   parseFloat(getCol(row, idx, "ExitPremium")),
		TargetNifty:   parseFloat(getCol(row, idx, "TargetNifty")),
		SLNifty:       parseFloat(getCol(row, idx, "SLNifty")),
		ExitReason:    getCol(row, idx, "ExitReason"),
		HoldMin:       parseFloat(getCol(row, idx, "HoldMin")),
		PnLSpotPct:    parseFloat(getCol(row, idx, "PnLSpotPct")),
		PnLPremiumPct: parseFloat(getCol(row, idx, "PnLPremiumPct")),
		PnLRupees:     parseFloat(getCol(row, idx, "PnLRupees")),
		RollingSig:    getCol(row, idx, "RollingSig"),
		DirectionSig:  getCol(row, idx, "DirectionSig"),
		CrossAssetSig: getCol(row, idx, "CrossAssetSig"),
	}
}

func headerIndex(header []string) map[string]int {
	idx := map[string]int{}
	for i, h := range header {
		idx[h] = i
	}
	return idx
}

func readCSV(path string) ([][]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := csv.NewReader(f)
	r.FieldsPerRecord = -1 // tolerate variable-width rows from schema migrations
	return r.ReadAll()
}
