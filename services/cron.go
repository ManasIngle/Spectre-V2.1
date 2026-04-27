package services

import (
	"encoding/csv"
	"fmt"
	"log"
	"os"
	"time"

	"spectre/models"
)

const signalCSVName = "system_signals.csv"

// signalCSVPath resolves the CSV location at call time so SPECTRE_DATA_DIR
// can take effect even if set after package init.
func signalCSVPath() string { return DataPath(signalCSVName) }

func StartSystemCron() {
	go func() {
		ticker := time.NewTicker(1 * time.Minute)
		defer ticker.Stop()

		loc, err := time.LoadLocation("Asia/Kolkata")
		if err != nil {
			log.Println("Timezone error, using local for cron:", err)
			loc = time.Local
		}

		if err := migrateSignalCSV(); err != nil {
			log.Printf("CSV migration skipped: %v", err)
		}

		log.Println("System Caching Cron initialized (09:00 - 15:30 IST)")
		log.Println("Morning Signal Cron initialized (09:09, 09:18 IST)")

		for {
			<-ticker.C
			now := time.Now().In(loc)

			timeStr := fmt.Sprintf("%02d:%02d", now.Hour(), now.Minute())

			if timeStr == "09:09" || timeStr == "09:18" {
				log.Println("Morning Signal trigger at", timeStr)
				go RefreshMorningSignal()
			}

			if timeStr >= "09:00" && timeStr <= "15:30" {
				signalCache.Delete("signal")

				signal, err := GenerateTradeSignal()
				if err != nil {
					log.Printf("Cron Error generating signal: %v", err)
					continue
				}

				logSignalToCSV(now, signal)

				// Track suggested strikes + log per-minute option prices for analytics.
				TrackSignalIfNew(now, signal)
				oi, _ := FetchOIChain()
				LogOptionArraySnapshot(now, oi, signal.NiftySpot)

				// Simulator Mode (sandboxed): shadow position tracking.
				SimOnSignal(now, signal, oi)
				SimTick(now, oi, signal.NiftySpot)
			}

			// Daily grader at 15:35 IST — runs after market close.
			if timeStr == "15:35" {
				log.Println("Signal grader trigger at", timeStr)
				go GradeDay(now)
			}
		}
	}()
}

// migrateSignalCSV splices Scalper_* columns into an existing CSV that predates them.
// Inserted directly before "PCR" to match the new header order; old rows get "" padding.
func migrateSignalCSV() error {
	f, err := os.Open(signalCSVPath())
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	rows, err := csv.NewReader(f).ReadAll()
	f.Close()
	if err != nil || len(rows) == 0 {
		return err
	}

	header := rows[0]
	pcrIdx := -1
	for i, col := range header {
		if col == "Scalper_Signal" {
			return nil
		}
		if col == "PCR" {
			pcrIdx = i
		}
	}
	if pcrIdx < 0 {
		return fmt.Errorf("PCR column not found in header; refusing to migrate")
	}

	scalperCols := []string{"Scalper_Signal", "Scalper_Down", "Scalper_Side", "Scalper_Up"}
	pad := []string{"", "0.0", "0.0", "0.0"}

	splice := func(row, insert []string) []string {
		out := make([]string, 0, len(row)+len(insert))
		out = append(out, row[:pcrIdx]...)
		out = append(out, insert...)
		out = append(out, row[pcrIdx:]...)
		return out
	}

	rows[0] = splice(header, scalperCols)
	for i := 1; i < len(rows); i++ {
		if len(rows[i]) < pcrIdx {
			continue
		}
		rows[i] = splice(rows[i], pad)
	}

	tmp := signalCSVPath() + ".migrate.tmp"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	w := csv.NewWriter(out)
	if err := w.WriteAll(rows); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	w.Flush()
	if err := out.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, signalCSVPath()); err != nil {
		return err
	}
	log.Printf("Migrated %s: inserted Scalper_* columns for %d existing rows", signalCSVPath(), len(rows)-1)
	return nil
}

func logSignalToCSV(t time.Time, s *models.TradeSignal) {
	file, err := os.OpenFile(signalCSVPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("Failed to open csv: %v", err)
		return
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	info, _ := file.Stat()
	if info.Size() == 0 {
		writer.Write([]string{
			"Date", "Time", "Signal", "StableSignal", "Prediction", "Confidence",
			"Spot", "Strike", "OptionType", "Option_LTP", "Target", "SL",
			// Ensemble probs
			"Prob_Down", "Prob_Side", "Prob_Up",
			// Model 1: Rolling (Stable)
			"Rolling_Signal", "Rolling_Down", "Rolling_Side", "Rolling_Up",
			// Model 2: Direction (5m Scalp)
			"Direction_Signal", "Direction_Down", "Direction_Side", "Direction_Up",
			// Model 3: Cross-Asset (BankNifty)
			"CrossAsset_Signal", "CrossAsset_Down", "CrossAsset_Side", "CrossAsset_Up",
			// Model 4: Old Direction (1H Trend)
			"OldDir_Signal", "OldDir_Down", "OldDir_Side", "OldDir_Up",
			// Model 5: Scalper LSTM (3m horizon)
			"Scalper_Signal", "Scalper_Down", "Scalper_Side", "Scalper_Up",
			// Market context
			"PCR", "Equity_Ret",
		})
	}

	optLTP := ""
	if s.OptionLTP != nil {
		optLTP = fmt.Sprintf("%.2f", *s.OptionLTP)
	}

	pcr := ""
	if s.PCR != nil {
		pcr = fmt.Sprintf("%.2f", *s.PCR)
	}

	// Model 1: Rolling
	rollSig := s.Models.Rolling.Signal
	rollDown := fmt.Sprintf("%.1f", s.Models.Rolling.Probs[0])
	rollSide := fmt.Sprintf("%.1f", s.Models.Rolling.Probs[1])
	rollUp := fmt.Sprintf("%.1f", s.Models.Rolling.Probs[2])

	// Model 2: Direction (5m)
	dirSig := s.Models.Direction.Signal
	dirDown := fmt.Sprintf("%.1f", s.Models.Direction.Probs[0])
	dirSide := fmt.Sprintf("%.1f", s.Models.Direction.Probs[1])
	dirUp := fmt.Sprintf("%.1f", s.Models.Direction.Probs[2])

	// Model 3: Cross-Asset
	crossSig := s.Models.CrossAsset.Signal
	crossDown := fmt.Sprintf("%.1f", s.Models.CrossAsset.Probs[0])
	crossSide := fmt.Sprintf("%.1f", s.Models.CrossAsset.Probs[1])
	crossUp := fmt.Sprintf("%.1f", s.Models.CrossAsset.Probs[2])

	// Model 4: Old Direction (1H) — optional
	oldDirSig, oldDirDown, oldDirSide, oldDirUp := "", "0.0", "0.0", "0.0"
	if s.Models.OldDirection != nil {
		oldDirSig = s.Models.OldDirection.Signal
		oldDirDown = fmt.Sprintf("%.1f", s.Models.OldDirection.Probs[0])
		oldDirSide = fmt.Sprintf("%.1f", s.Models.OldDirection.Probs[1])
		oldDirUp = fmt.Sprintf("%.1f", s.Models.OldDirection.Probs[2])
	}

	// Model 5: Scalper LSTM (3m) — optional
	scalpSig, scalpDown, scalpSide, scalpUp := "", "0.0", "0.0", "0.0"
	if s.Models.Scalper != nil {
		scalpSig = s.Models.Scalper.Signal
		scalpDown = fmt.Sprintf("%.1f", s.Models.Scalper.Probs[0])
		scalpSide = fmt.Sprintf("%.1f", s.Models.Scalper.Probs[1])
		scalpUp = fmt.Sprintf("%.1f", s.Models.Scalper.Probs[2])
	}

	record := []string{
		t.Format("2006-01-02"),
		t.Format("15:04:05"),
		s.RawSignal,
		s.Signal,
		s.Prediction,
		fmt.Sprintf("%.1f", s.Confidence),
		fmt.Sprintf("%.2f", s.NiftySpot),
		fmt.Sprintf("%.0f", s.Strike),
		s.OptionType,
		optLTP,
		fmt.Sprintf("%.1f", s.TargetNifty),
		fmt.Sprintf("%.1f", s.SLNifty),
		fmt.Sprintf("%.1f", s.ProbDown),
		fmt.Sprintf("%.1f", s.ProbSideways),
		fmt.Sprintf("%.1f", s.ProbUp),
		rollSig, rollDown, rollSide, rollUp,
		dirSig, dirDown, dirSide, dirUp,
		crossSig, crossDown, crossSide, crossUp,
		oldDirSig, oldDirDown, oldDirSide, oldDirUp,
		scalpSig, scalpDown, scalpSide, scalpUp,
		pcr,
		fmt.Sprintf("%.3f", s.EquityReturn),
	}

	if err := writer.Write(record); err != nil {
		log.Println("Error writing cron log:", err)
	}
}
