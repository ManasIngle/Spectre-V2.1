package services

import (
	"encoding/csv"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"spectre/models"
)

// option_price_array.csv tracks per-minute option LTP for every strike that
// the model suggested at any point during the trading day. Used post-hoc to
// study optimal hold windows: e.g. "for the 24050 PE first suggested at 10:03,
// what was the LTP every minute from 10:03 to close?"
//
// Schema (one row per (minute, strike)):
//   Date, Time, Strike, OptionType, Spot, LTP,
//   FirstSuggestedAt, MinutesSinceSuggested, SuggestionConfidence
const optionArrayCSVName = "option_price_array.csv"

// optionArrayCSVPath resolves the path each call so SPECTRE_DATA_DIR is honored.
func optionArrayCSVPath() string { return DataPath(optionArrayCSVName) }

type trackedStrike struct {
	Strike     float64
	OptionType string  // "CE" or "PE"
	FirstAt    time.Time
	FirstConf  float64 // confidence at first suggestion
}

var (
	trackedMu       sync.Mutex
	trackedStrikes  = map[string]*trackedStrike{} // key: "YYYY-MM-DD|strike|type"
	trackedDayStamp string
)

// strikeKey generates the map key. The date prefix ensures the map auto-rolls
// at midnight (we just clear entries with stale date prefixes).
func strikeKey(date string, strike float64, optType string) string {
	return fmt.Sprintf("%s|%.0f|%s", date, strike, optType)
}

// resetIfNewDay clears the tracker if the date has rolled over.
// Call this with the lock already held.
func resetIfNewDay(today string) {
	if trackedDayStamp == today {
		return
	}
	trackedStrikes = map[string]*trackedStrike{}
	trackedDayStamp = today
}

// TrackSignalIfNew records the strike from a fresh trade signal. No-op for
// NO TRADE / signals without a real strike. Called once per minute by the cron.
func TrackSignalIfNew(now time.Time, s *models.TradeSignal) {
	if s == nil || s.OptionType == "-" || s.OptionType == "" {
		return
	}
	if s.Strike <= 0 {
		return
	}
	today := now.Format("2006-01-02")

	trackedMu.Lock()
	defer trackedMu.Unlock()
	resetIfNewDay(today)

	key := strikeKey(today, s.Strike, s.OptionType)
	if _, exists := trackedStrikes[key]; exists {
		return
	}
	trackedStrikes[key] = &trackedStrike{
		Strike:     s.Strike,
		OptionType: s.OptionType,
		FirstAt:    now,
		FirstConf:  s.Confidence,
	}
}

// LogOptionArraySnapshot writes one row per tracked strike to the CSV using
// the current OI chain for live LTPs. Called once per minute by the cron.
func LogOptionArraySnapshot(now time.Time, oi *models.OIChainData, spot float64) {
	if oi == nil {
		return
	}
	today := now.Format("2006-01-02")

	trackedMu.Lock()
	resetIfNewDay(today)
	// Snapshot the tracked entries while holding the lock, then release.
	snapshot := make([]*trackedStrike, 0, len(trackedStrikes))
	for k, v := range trackedStrikes {
		// Filter to today only (defensive — resetIfNewDay should have purged old days).
		if len(k) >= 10 && k[:10] != today {
			continue
		}
		snapshot = append(snapshot, v)
	}
	trackedMu.Unlock()

	if len(snapshot) == 0 {
		return
	}

	// Build a strike→LTP lookup once.
	ceLTP := map[int]float64{}
	peLTP := map[int]float64{}
	for _, s := range oi.Strikes {
		k := int(s.Strike)
		ceLTP[k] = s.CELTP
		peLTP[k] = s.PELTP
	}

	file, err := os.OpenFile(optionArrayCSVPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("Failed to open option_price_array.csv: %v", err)
		return
	}
	defer file.Close()

	w := csv.NewWriter(file)
	defer w.Flush()

	info, _ := file.Stat()
	if info.Size() == 0 {
		w.Write([]string{
			"Date", "Time", "Strike", "OptionType", "Spot", "LTP",
			"FirstSuggestedAt", "MinutesSinceSuggested", "SuggestionConfidence",
		})
	}

	for _, ts := range snapshot {
		k := int(ts.Strike)
		var lp float64
		if ts.OptionType == "CE" {
			lp = ceLTP[k]
		} else {
			lp = peLTP[k]
		}
		// Allow 0/missing LTPs through — important to know we couldn't get a
		// price at that minute; downstream analytics can filter.
		minutesSince := int(now.Sub(ts.FirstAt).Minutes())

		w.Write([]string{
			today,
			now.Format("15:04:05"),
			fmt.Sprintf("%.0f", ts.Strike),
			ts.OptionType,
			fmt.Sprintf("%.2f", spot),
			fmt.Sprintf("%.2f", lp),
			ts.FirstAt.Format("15:04:05"),
			fmt.Sprintf("%d", minutesSince),
			fmt.Sprintf("%.1f", ts.FirstConf),
		})
	}
}

// OptionArrayPath returns the absolute path to the CSV (used by download handler).
func OptionArrayPath() string {
	return optionArrayCSVPath()
}
