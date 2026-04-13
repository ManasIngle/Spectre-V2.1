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
			"Timestamp", "NiftySpot", "RawSignal", "StableSignal", "CrossAssetSignal",
			"Confidence", "Strike", "OptionType", "Option_LTP", "TargetNifty", "SLNifty",
			"ProbUp", "ProbDown", "CrossAssetProbUp", "CrossAssetProbDown",
		})
	}

	optLTP := ""
	if s.OptionLTP != nil {
		optLTP = fmt.Sprintf("%.2f", *s.OptionLTP)
	}

	crossProbUp, crossProbDown := 0.0, 0.0
	if len(s.CrossAssetProbs) >= 3 {
		crossProbDown = s.CrossAssetProbs[0]
		crossProbUp = s.CrossAssetProbs[2]
	}

	record := []string{
		t.Format("2006-01-02 15:04:05"),
		fmt.Sprintf("%.2f", s.NiftySpot),
		s.RawSignal,
		s.Signal,
		s.CrossAssetSignal,
		fmt.Sprintf("%.1f", s.Confidence),
		fmt.Sprintf("%.0f", s.Strike),
		s.OptionType,
		optLTP,
		fmt.Sprintf("%.2f", s.TargetNifty),
		fmt.Sprintf("%.2f", s.SLNifty),
		fmt.Sprintf("%.1f", s.ProbUp),
		fmt.Sprintf("%.1f", s.ProbDown),
		fmt.Sprintf("%.1f", crossProbUp),
		fmt.Sprintf("%.1f", crossProbDown),
	}

	if err := writer.Write(record); err != nil {
		log.Println("Error writing cron log:", err)
	}
}
