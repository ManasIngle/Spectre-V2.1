package handlers

import (
	"encoding/csv"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"
)

const signalCSVPath = "system_signals.csv"

func GetMLLogs(c *gin.Context) {
	ist, err := time.LoadLocation("Asia/Kolkata")
	if err != nil {
		ist = time.FixedZone("IST", 5*3600+1800)
	}
	today := time.Now().In(ist).Format("2006-01-02")

	logs, err := readCSVLogs(today)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"logs": []interface{}{}})
		return
	}

	c.JSON(http.StatusOK, gin.H{"logs": logs})
}

func DownloadMLLogs(c *gin.Context) {
	abs, err := filepath.Abs(signalCSVPath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "path error"})
		return
	}
	c.Header("Content-Disposition", "attachment; filename=system_signals.csv")
	c.Header("Content-Type", "text/csv")
	c.File(abs)
}

func readCSVLogs(datePrefix string) ([]map[string]string, error) {
	f, err := os.Open(signalCSVPath)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	headers, err := r.Read()
	if err != nil {
		return nil, err
	}

	// Build header index map
	idx := make(map[string]int, len(headers))
	for i, h := range headers {
		idx[h] = i
	}

	var logs []map[string]string
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			continue
		}
		if len(row) == 0 {
			continue
		}

		// Support both old format (combined Timestamp) and new format (separate Date, Time)
		dateVal := colVal(row, idx, "Date")
		timeVal := colVal(row, idx, "Time")

		if dateVal == "" {
			// Fallback for old format with combined Timestamp column
			ts := colVal(row, idx, "Timestamp")
			if len(ts) >= 10 {
				dateVal = ts[:10]
			}
			if len(ts) >= 19 {
				timeVal = ts[11:19]
			}
		}

		if dateVal != datePrefix {
			continue
		}

		// Format time as 12h
		timeStr := timeVal
		if t, err := time.Parse("15:04:05", timeVal); err == nil {
			timeStr = t.Format("03:04 PM")
		}

		entry := map[string]string{
			"Time":        timeStr,
			"Signal":      colVal(row, idx, "Signal"),
			"StableSignal": colVal(row, idx, "StableSignal"),
			"Prediction":  colVal(row, idx, "Prediction"),
			"Confidence":  colVal(row, idx, "Confidence"),
			"Spot":        colVal(row, idx, "Spot"),
			"Strike":      colVal(row, idx, "Strike"),
			"OptionType":  colVal(row, idx, "OptionType"),
			"Option_LTP":  colVal(row, idx, "Option_LTP"),
			"Target":      colVal(row, idx, "Target"),
			"SL":          colVal(row, idx, "SL"),
			// Ensemble
			"Prob_Down":   colVal(row, idx, "Prob_Down"),
			"Prob_Side":   colVal(row, idx, "Prob_Side"),
			"Prob_Up":     colVal(row, idx, "Prob_Up"),
			// Model 1: Rolling
			"Rolling_Signal": colVal(row, idx, "Rolling_Signal"),
			"Rolling_Down":   colVal(row, idx, "Rolling_Down"),
			"Rolling_Side":   colVal(row, idx, "Rolling_Side"),
			"Rolling_Up":     colVal(row, idx, "Rolling_Up"),
			// Model 2: Direction (5m)
			"Direction_Signal": colVal(row, idx, "Direction_Signal"),
			"Direction_Down":   colVal(row, idx, "Direction_Down"),
			"Direction_Side":   colVal(row, idx, "Direction_Side"),
			"Direction_Up":     colVal(row, idx, "Direction_Up"),
			// Model 3: Cross-Asset
			"CrossAsset_Signal": colVal(row, idx, "CrossAsset_Signal"),
			"CrossAsset_Down":   colVal(row, idx, "CrossAsset_Down"),
			"CrossAsset_Side":   colVal(row, idx, "CrossAsset_Side"),
			"CrossAsset_Up":     colVal(row, idx, "CrossAsset_Up"),
			// Model 4: Old Direction (1H)
			"OldDir_Signal": colVal(row, idx, "OldDir_Signal"),
			"OldDir_Down":   colVal(row, idx, "OldDir_Down"),
			"OldDir_Side":   colVal(row, idx, "OldDir_Side"),
			"OldDir_Up":     colVal(row, idx, "OldDir_Up"),
			// Market context
			"PCR":         colVal(row, idx, "PCR"),
			"Equity_Ret":  colVal(row, idx, "Equity_Ret"),
			// Backward compat: map to old names for frontend
			"LSTM_Up":     colVal(row, idx, "Direction_Up"),
			"LSTM_Down":   colVal(row, idx, "Direction_Down"),
			"XGB_Up":      colVal(row, idx, "Rolling_Up"),
			"XGB_Down":    colVal(row, idx, "Rolling_Down"),
		}
		logs = append(logs, entry)
	}

	if logs == nil {
		logs = []map[string]string{}
	}
	return logs, nil
}

func colVal(row []string, idx map[string]int, col string) string {
	i, ok := idx[col]
	if !ok || i >= len(row) {
		return ""
	}
	return row[i]
}
