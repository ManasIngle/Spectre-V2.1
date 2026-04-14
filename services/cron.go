package services

import (
	"encoding/csv"
	"fmt"
	"log"
	"os"
	"time"

	"spectre/models"
)

func StartSystemCron() {
	go func() {
		ticker := time.NewTicker(1 * time.Minute)
		defer ticker.Stop()

		loc, err := time.LoadLocation("Asia/Kolkata")
		if err != nil {
			log.Println("Timezone error, using local for cron:", err)
			loc = time.Local
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
			}
		}
	}()
}

func logSignalToCSV(t time.Time, s *models.TradeSignal) {
	filename := "system_signals.csv"
	file, err := os.OpenFile(filename, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
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
		pcr,
		fmt.Sprintf("%.3f", s.EquityReturn),
	}

	if err := writer.Write(record); err != nil {
		log.Println("Error writing cron log:", err)
	}
}
