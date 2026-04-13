package handlers

import (
	"encoding/csv"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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

		ts := colVal(row, idx, "Timestamp")
		if !strings.HasPrefix(ts, datePrefix) {
			continue
		}

		// Parse time portion from "2006-01-02 15:04:05"
		timeStr := ""
		if len(ts) >= 16 {
			t, perr := time.Parse("2006-01-02 15:04:05", ts)
			if perr == nil {
				timeStr = t.Format("03:04 PM")
			} else {
				timeStr = ts[11:16]
			}
		}

		entry := map[string]string{
			"Time":             timeStr,
			"Signal":          colVal(row, idx, "StableSignal"),
			"Confidence":      colVal(row, idx, "Confidence"),
			"Spot":            colVal(row, idx, "NiftySpot"),
			"Strike":          colVal(row, idx, "Strike"),
			"OptionType":      colVal(row, idx, "OptionType"),
			"Option_LTP":      colVal(row, idx, "Option_LTP"),
			"Target":          colVal(row, idx, "TargetNifty"),
			"SL":              colVal(row, idx, "SLNifty"),
			"LSTM_Up":         colVal(row, idx, "ProbUp"),
			"LSTM_Down":       colVal(row, idx, "ProbDown"),
			"XGB_Up":          colVal(row, idx, "CrossAssetProbUp"),
			"XGB_Down":        colVal(row, idx, "CrossAssetProbDown"),
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
