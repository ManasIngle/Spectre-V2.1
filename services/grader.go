package services

import (
	"encoding/csv"
	"fmt"
	"log"
	"math"
	"os"
	"sort"
	"strconv"
	"time"
)

// Daily grader — runs at 15:35 IST after market close.
// Reads system_signals.csv + option_price_array.csv, produces:
//   - signal_grades.csv: per-signal theoretical P&L at +5/+10/+15/+30 + best exit
//   - model_scorecard.csv: per-model directional accuracy aggregated per day

const (
	signalGradesCSVName  = "signal_grades.csv"
	modelScorecardCSVName = "model_scorecard.csv"
	dirThresholdPct       = 0.15 // |move| > 0.15% counts as directional
)

func signalGradesPath() string  { return DataPath(signalGradesCSVName) }
func modelScorecardPath() string { return DataPath(modelScorecardCSVName) }

type signalRow struct {
	date       string
	timeStr    string
	t          time.Time
	rawSignal  string
	stableSig  string
	prediction string
	conf       float64
	spot       float64
	strike     float64
	optType    string
	probUp     float64
	probDown   float64
	probSide   float64
	models     map[string]string  // modelName -> signal (BUY CE / BUY PE / NO TRADE)
	modelProbs map[string][3]float64
}

type optPriceRow struct {
	t       time.Time
	strike  float64
	optType string
	spot    float64
	ltp     float64
}

// GradeDay processes today's signals and writes grades + updates the scorecard.
func GradeDay(now time.Time) {
	day := now.Format("2006-01-02")
	log.Printf("[grader] starting for %s", day)

	signals, err := loadSignalsForDay(day)
	if err != nil {
		log.Printf("[grader] load signals: %v", err)
		return
	}
	if len(signals) == 0 {
		log.Printf("[grader] no signals to grade")
		return
	}

	prices, err := loadOptionPricesForDay(day)
	if err != nil {
		log.Printf("[grader] load option prices: %v", err)
		// fall through — we can still grade by spot
	}

	// Index option prices by (strike, type) → time-sorted slice
	priceIdx := map[string][]optPriceRow{}
	for _, p := range prices {
		k := fmt.Sprintf("%.0f|%s", p.strike, p.optType)
		priceIdx[k] = append(priceIdx[k], p)
	}
	for k := range priceIdx {
		sort.Slice(priceIdx[k], func(i, j int) bool { return priceIdx[k][i].t.Before(priceIdx[k][j].t) })
	}

	// Build a spot trajectory from signals (one spot per minute)
	spotTrack := map[time.Time]float64{}
	for _, s := range signals {
		spotTrack[s.t.Truncate(time.Minute)] = s.spot
	}

	gradedRows := [][]string{}
	for _, sig := range signals {
		grade := gradeOneSignal(sig, priceIdx, spotTrack)
		if grade != nil {
			gradedRows = append(gradedRows, grade)
		}
	}

	if err := writeGrades(day, gradedRows); err != nil {
		log.Printf("[grader] write grades: %v", err)
	}

	// Per-model scorecard for the day
	scorecard := computeModelScorecard(day, signals, spotTrack)
	if err := appendScorecard(scorecard); err != nil {
		log.Printf("[grader] write scorecard: %v", err)
	}

	log.Printf("[grader] done — %d signals graded, %d model rows", len(gradedRows), len(scorecard))
}

func loadSignalsForDay(day string) ([]signalRow, error) {
	f, err := os.Open(signalCSVPath())
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	rows, err := r.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}

	header := rows[0]
	idx := map[string]int{}
	for i, h := range header {
		idx[h] = i
	}

	loc, _ := time.LoadLocation("Asia/Kolkata")
	out := []signalRow{}
	for _, row := range rows[1:] {
		if len(row) < len(header) {
			continue
		}
		if row[idx["Date"]] != day {
			continue
		}
		t, err := time.ParseInLocation("2006-01-02 15:04:05", row[idx["Date"]]+" "+row[idx["Time"]], loc)
		if err != nil {
			continue
		}
		s := signalRow{
			date:       row[idx["Date"]],
			timeStr:    row[idx["Time"]],
			t:          t,
			rawSignal:  row[idx["Signal"]],
			stableSig:  row[idx["StableSignal"]],
			prediction: row[idx["Prediction"]],
			conf:       parseFloat(row[idx["Confidence"]]),
			spot:       parseFloat(row[idx["Spot"]]),
			strike:     parseFloat(row[idx["Strike"]]),
			optType:    row[idx["OptionType"]],
			probUp:     parseFloat(row[idx["Prob_Up"]]),
			probDown:   parseFloat(row[idx["Prob_Down"]]),
			probSide:   parseFloat(row[idx["Prob_Side"]]),
			models:     map[string]string{},
			modelProbs: map[string][3]float64{},
		}
		for _, m := range []string{"Rolling", "Direction", "CrossAsset", "OldDir", "Scalper"} {
			if i, ok := idx[m+"_Signal"]; ok {
				s.models[m] = row[i]
			}
			s.modelProbs[m] = [3]float64{
				parseFloat(getCol(row, idx, m+"_Down")),
				parseFloat(getCol(row, idx, m+"_Side")),
				parseFloat(getCol(row, idx, m+"_Up")),
			}
		}
		out = append(out, s)
	}
	return out, nil
}

func loadOptionPricesForDay(day string) ([]optPriceRow, error) {
	f, err := os.Open(optionArrayCSVPath())
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	rows, err := r.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}
	header := rows[0]
	idx := map[string]int{}
	for i, h := range header {
		idx[h] = i
	}

	loc, _ := time.LoadLocation("Asia/Kolkata")
	out := []optPriceRow{}
	for _, row := range rows[1:] {
		if len(row) < len(header) {
			continue
		}
		if row[idx["Date"]] != day {
			continue
		}
		t, err := time.ParseInLocation("2006-01-02 15:04:05", row[idx["Date"]]+" "+row[idx["Time"]], loc)
		if err != nil {
			continue
		}
		out = append(out, optPriceRow{
			t:       t,
			strike:  parseFloat(row[idx["Strike"]]),
			optType: row[idx["OptionType"]],
			spot:    parseFloat(row[idx["Spot"]]),
			ltp:     parseFloat(row[idx["LTP"]]),
		})
	}
	return out, nil
}

// gradeOneSignal computes premium trajectory + theoretical P&L for one signal.
// Returns a CSV row or nil if signal can't be graded (e.g., NO TRADE).
func gradeOneSignal(s signalRow, priceIdx map[string][]optPriceRow, spotTrack map[time.Time]float64) []string {
	if s.rawSignal == "NO TRADE" || s.optType == "-" || s.strike == 0 {
		// Still grade: theoretical move only, no premium
		return gradeNoTradeSignal(s, spotTrack)
	}

	key := fmt.Sprintf("%.0f|%s", s.strike, s.optType)
	prices := priceIdx[key]
	if len(prices) == 0 {
		return gradeNoTradeSignal(s, spotTrack)
	}

	// Find entry premium: closest price at or after signal time (within 2 min)
	var entry *optPriceRow
	for i := range prices {
		if !prices[i].t.Before(s.t) && prices[i].t.Sub(s.t) <= 2*time.Minute {
			entry = &prices[i]
			break
		}
	}
	if entry == nil || entry.ltp == 0 {
		return gradeNoTradeSignal(s, spotTrack)
	}

	// Premiums at +5/+10/+15/+30
	prem5 := premiumAtOffset(prices, s.t, 5*time.Minute)
	prem10 := premiumAtOffset(prices, s.t, 10*time.Minute)
	prem15 := premiumAtOffset(prices, s.t, 15*time.Minute)
	prem30 := premiumAtOffset(prices, s.t, 30*time.Minute)

	// Best exit (max premium in next 30 min)
	bestPrem, bestMin := entry.ltp, 0
	for _, p := range prices {
		if p.t.Before(s.t) {
			continue
		}
		minsAfter := int(p.t.Sub(s.t).Minutes())
		if minsAfter > 30 {
			break
		}
		if p.ltp > bestPrem {
			bestPrem = p.ltp
			bestMin = minsAfter
		}
	}

	spot5 := spotAtOffset(spotTrack, s.t, 5)
	spot10 := spotAtOffset(spotTrack, s.t, 10)
	spot15 := spotAtOffset(spotTrack, s.t, 15)
	spot30 := spotAtOffset(spotTrack, s.t, 30)

	move5 := pctMove(s.spot, spot5, s.optType)
	move10 := pctMove(s.spot, spot10, s.optType)
	move15 := pctMove(s.spot, spot15, s.optType)
	move30 := pctMove(s.spot, spot30, s.optType)

	bestPnL := pnlPct(entry.ltp, bestPrem)
	endPnL := pnlPct(entry.ltp, prem30)

	grade := "NEUTRAL"
	switch {
	case bestPnL >= 10:
		grade = "WIN"
	case bestPnL <= -15:
		grade = "LOSS"
	}

	return []string{
		s.date, s.timeStr, s.rawSignal, s.stableSig,
		fmt.Sprintf("%.0f", s.strike), s.optType,
		fmt.Sprintf("%.1f", s.conf),
		fmt.Sprintf("%.2f", s.spot), fmt.Sprintf("%.2f", entry.ltp),
		fmt.Sprintf("%.2f", spot5), fmt.Sprintf("%.2f", spot10),
		fmt.Sprintf("%.2f", spot15), fmt.Sprintf("%.2f", spot30),
		fmt.Sprintf("%.2f", prem5), fmt.Sprintf("%.2f", prem10),
		fmt.Sprintf("%.2f", prem15), fmt.Sprintf("%.2f", prem30),
		fmt.Sprintf("%.2f", bestPrem), fmt.Sprintf("%d", bestMin),
		fmt.Sprintf("%.3f", move5), fmt.Sprintf("%.3f", move10),
		fmt.Sprintf("%.3f", move15), fmt.Sprintf("%.3f", move30),
		fmt.Sprintf("%.2f", bestPnL), fmt.Sprintf("%.2f", endPnL),
		grade,
	}
}

func gradeNoTradeSignal(s signalRow, spotTrack map[time.Time]float64) []string {
	spot5 := spotAtOffset(spotTrack, s.t, 5)
	spot10 := spotAtOffset(spotTrack, s.t, 10)
	spot15 := spotAtOffset(spotTrack, s.t, 15)
	spot30 := spotAtOffset(spotTrack, s.t, 30)

	move30 := 0.0
	if spot30 != 0 {
		move30 = (spot30 - s.spot) / s.spot * 100
	}
	suppressionGrade := "SUPP_NEUTRAL"
	if math.Abs(move30) >= 0.5 {
		suppressionGrade = "SUPP_MOVED"
	}

	return []string{
		s.date, s.timeStr, s.rawSignal, s.stableSig,
		fmt.Sprintf("%.0f", s.strike), s.optType,
		fmt.Sprintf("%.1f", s.conf),
		fmt.Sprintf("%.2f", s.spot), "0.00",
		fmt.Sprintf("%.2f", spot5), fmt.Sprintf("%.2f", spot10),
		fmt.Sprintf("%.2f", spot15), fmt.Sprintf("%.2f", spot30),
		"0.00", "0.00", "0.00", "0.00", "0.00", "0",
		"0.000", "0.000", "0.000", fmt.Sprintf("%.3f", move30),
		"0.00", "0.00", suppressionGrade,
	}
}

func premiumAtOffset(prices []optPriceRow, base time.Time, offset time.Duration) float64 {
	target := base.Add(offset)
	// Closest match within ±60s
	for _, p := range prices {
		if !p.t.Before(target.Add(-60*time.Second)) && !p.t.After(target.Add(60*time.Second)) {
			return p.ltp
		}
	}
	return 0
}

func spotAtOffset(track map[time.Time]float64, base time.Time, offsetMin int) float64 {
	target := base.Truncate(time.Minute).Add(time.Duration(offsetMin) * time.Minute)
	for off := 0; off <= 2; off++ {
		if v, ok := track[target.Add(time.Duration(off)*time.Minute)]; ok && v != 0 {
			return v
		}
		if v, ok := track[target.Add(time.Duration(-off)*time.Minute)]; ok && v != 0 {
			return v
		}
	}
	return 0
}

func pctMove(entry, exit float64, optType string) float64 {
	if entry == 0 || exit == 0 {
		return 0
	}
	if optType == "CE" {
		return (exit - entry) / entry * 100
	}
	return (entry - exit) / entry * 100
}

func pnlPct(entry, exit float64) float64 {
	if entry == 0 {
		return 0
	}
	return (exit - entry) / entry * 100
}

func writeGrades(day string, rows [][]string) error {
	// Append-only; if file empty write header.
	path := signalGradesPath()
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	info, _ := f.Stat()
	if info.Size() == 0 {
		w.Write([]string{
			"Date", "Time", "RawSignal", "StableSignal", "Strike", "OptionType", "Confidence",
			"EntrySpot", "EntryPremium",
			"Spot_5m", "Spot_10m", "Spot_15m", "Spot_30m",
			"Premium_5m", "Premium_10m", "Premium_15m", "Premium_30m",
			"Premium_Best", "Best_Exit_Min",
			"Move_5m_pct", "Move_10m_pct", "Move_15m_pct", "Move_30m_pct",
			"Theoretical_BestPnL_pct", "Theoretical_EndPnL_pct",
			"Grade",
		})
	}
	for _, r := range rows {
		w.Write(r)
	}
	return nil
}

type modelStat struct {
	model         string
	total         int
	buyCount      int
	sellCount     int
	noTradeCount  int
	correct       int
	directional   int // signals that were BUY CE/BUY PE (excluding NO TRADE)
	confRightSum  float64
	confRightN    int
	confWrongSum  float64
	confWrongN    int
	pnlSum        float64
	pnlN          int
	hourCorrect   map[int]int
	hourTotal     map[int]int
}

func computeModelScorecard(day string, signals []signalRow, spotTrack map[time.Time]float64) []modelScorecardRow {
	stats := map[string]*modelStat{}
	for _, m := range []string{"Rolling", "Direction", "CrossAsset", "OldDir", "Scalper", "Ensemble"} {
		stats[m] = &modelStat{model: m, hourCorrect: map[int]int{}, hourTotal: map[int]int{}}
	}

	for _, sig := range signals {
		spot30 := spotAtOffset(spotTrack, sig.t, 30)
		if spot30 == 0 {
			continue
		}
		movePct := (spot30 - sig.spot) / sig.spot * 100
		actualDir := "FLAT"
		if movePct > dirThresholdPct {
			actualDir = "UP"
		} else if movePct < -dirThresholdPct {
			actualDir = "DOWN"
		}

		// Per individual model
		for mname, msig := range sig.models {
			st, ok := stats[mname]
			if !ok {
				continue
			}
			st.total++
			predDir := signalToDir(msig)
			if predDir == "BUY CE" {
				st.buyCount++
				predDir = "UP"
			} else if predDir == "BUY PE" {
				st.sellCount++
				predDir = "DOWN"
			} else {
				st.noTradeCount++
				continue
			}
			st.directional++
			hour := sig.t.Hour()
			st.hourTotal[hour]++
			if predDir == actualDir {
				st.correct++
				st.confRightSum += sig.conf
				st.confRightN++
				st.hourCorrect[hour]++
			} else {
				st.confWrongSum += sig.conf
				st.confWrongN++
			}
		}

		// Ensemble (using sig.rawSignal)
		st := stats["Ensemble"]
		st.total++
		predDir := ""
		if sig.rawSignal == "BUY CE" {
			st.buyCount++
			predDir = "UP"
		} else if sig.rawSignal == "BUY PE" {
			st.sellCount++
			predDir = "DOWN"
		} else {
			st.noTradeCount++
		}
		if predDir != "" {
			st.directional++
			hour := sig.t.Hour()
			st.hourTotal[hour]++
			if predDir == actualDir {
				st.correct++
				st.confRightSum += sig.conf
				st.confRightN++
				st.hourCorrect[hour]++
			} else {
				st.confWrongSum += sig.conf
				st.confWrongN++
			}
		}
	}

	out := []modelScorecardRow{}
	for _, st := range stats {
		acc := 0.0
		if st.directional > 0 {
			acc = float64(st.correct) / float64(st.directional) * 100
		}
		avgRight := safeDiv(st.confRightSum, st.confRightN)
		avgWrong := safeDiv(st.confWrongSum, st.confWrongN)
		bestHour, worstHour := bestWorstHour(st.hourCorrect, st.hourTotal)
		out = append(out, modelScorecardRow{
			Date: day, Model: st.model,
			Total: st.total, Directional: st.directional,
			Buy: st.buyCount, Sell: st.sellCount, NoTrade: st.noTradeCount,
			DirAccPct: acc,
			AvgConfRight: avgRight, AvgConfWrong: avgWrong,
			BestHour: bestHour, WorstHour: worstHour,
		})
	}
	return out
}

type modelScorecardRow struct {
	Date         string  `json:"date"`
	Model        string  `json:"model"`
	Total        int     `json:"total"`
	Directional  int     `json:"directional"`
	Buy          int     `json:"buy"`
	Sell         int     `json:"sell"`
	NoTrade      int     `json:"no_trade"`
	DirAccPct    float64 `json:"dir_acc_pct"`
	AvgConfRight float64 `json:"avg_conf_right"`
	AvgConfWrong float64 `json:"avg_conf_wrong"`
	BestHour     int     `json:"best_hour"`
	WorstHour    int     `json:"worst_hour"`
}

func appendScorecard(rows []modelScorecardRow) error {
	path := modelScorecardPath()
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	info, _ := f.Stat()
	if info.Size() == 0 {
		w.Write([]string{
			"Date", "Model", "Total", "Directional",
			"BuyCount", "SellCount", "NoTradeCount",
			"DirAccPct", "AvgConfRight", "AvgConfWrong",
			"BestHour", "WorstHour",
		})
	}
	for _, r := range rows {
		w.Write([]string{
			r.Date, r.Model,
			strconv.Itoa(r.Total), strconv.Itoa(r.Directional),
			strconv.Itoa(r.Buy), strconv.Itoa(r.Sell), strconv.Itoa(r.NoTrade),
			fmt.Sprintf("%.1f", r.DirAccPct),
			fmt.Sprintf("%.1f", r.AvgConfRight), fmt.Sprintf("%.1f", r.AvgConfWrong),
			strconv.Itoa(r.BestHour), strconv.Itoa(r.WorstHour),
		})
	}
	return nil
}

// LoadScorecard returns last N days of model scorecards (most recent first).
func LoadScorecard(days int) ([]modelScorecardRow, error) {
	f, err := os.Open(modelScorecardPath())
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := csv.NewReader(f)
	rows, err := r.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(rows) < 2 {
		return nil, nil
	}
	out := []modelScorecardRow{}
	for _, row := range rows[1:] {
		if len(row) < 12 {
			continue
		}
		out = append(out, modelScorecardRow{
			Date: row[0], Model: row[1],
			Total: atoi(row[2]), Directional: atoi(row[3]),
			Buy: atoi(row[4]), Sell: atoi(row[5]), NoTrade: atoi(row[6]),
			DirAccPct:    parseFloat(row[7]),
			AvgConfRight: parseFloat(row[8]), AvgConfWrong: parseFloat(row[9]),
			BestHour: atoi(row[10]), WorstHour: atoi(row[11]),
		})
	}
	// Sort newest first, cap to N days worth
	sort.Slice(out, func(i, j int) bool { return out[i].Date > out[j].Date })
	if days > 0 {
		seen := map[string]bool{}
		filtered := []modelScorecardRow{}
		for _, r := range out {
			seen[r.Date] = true
			if len(seen) > days {
				break
			}
			filtered = append(filtered, r)
		}
		return filtered, nil
	}
	return out, nil
}

// helpers
func parseFloat(s string) float64 {
	f, _ := strconv.ParseFloat(s, 64)
	return f
}
func atoi(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}
func getCol(row []string, idx map[string]int, key string) string {
	i, ok := idx[key]
	if !ok || i >= len(row) {
		return ""
	}
	return row[i]
}
func signalToDir(s string) string {
	switch s {
	case "BUY CE", "BUY PE":
		return s
	}
	return "NO TRADE"
}
func safeDiv(sum float64, n int) float64 {
	if n == 0 {
		return 0
	}
	return sum / float64(n)
}
func bestWorstHour(correct, total map[int]int) (int, int) {
	best, worst := -1, -1
	bestAcc, worstAcc := -1.0, 2.0
	for h, t := range total {
		if t < 2 {
			continue
		}
		a := float64(correct[h]) / float64(t)
		if a > bestAcc {
			bestAcc = a
			best = h
		}
		if a < worstAcc {
			worstAcc = a
			worst = h
		}
	}
	return best, worst
}

// SignalGradesPath is exported for the download/UI handlers.
func SignalGradesPath() string  { return signalGradesPath() }
func ModelScorecardPath() string { return modelScorecardPath() }
func ExecutedTradesPath() string { return executedTradesCSVPath() }
