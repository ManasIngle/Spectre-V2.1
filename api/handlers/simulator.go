package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// GetSimulatorState returns today's open + closed simulator positions.
func GetSimulatorState(c *gin.Context) {
	open, closed := services.GetSimState()
	c.JSON(http.StatusOK, gin.H{
		"open":   open,
		"closed": closed,
		"counts": gin.H{
			"open":   len(open),
			"closed": len(closed),
		},
	})
}

// GetModelScorecard returns the per-model scorecard for the last N days (default 7).
func GetModelScorecard(c *gin.Context) {
	daysStr := c.DefaultQuery("days", "7")
	days, err := strconv.Atoi(daysStr)
	if err != nil || days < 1 {
		days = 7
	}
	rows, err := services.LoadScorecard(days)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": []interface{}{}, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": rows, "days": days})
}

// DownloadExecutedTrades streams executed_trades.csv.
func DownloadExecutedTrades(c *gin.Context) {
	c.FileAttachment(services.ExecutedTradesPath(), "executed_trades.csv")
}

// DownloadSignalGrades streams signal_grades.csv.
func DownloadSignalGrades(c *gin.Context) {
	c.FileAttachment(services.SignalGradesPath(), "signal_grades.csv")
}

// DownloadModelScorecard streams model_scorecard.csv.
func DownloadModelScorecard(c *gin.Context) {
	c.FileAttachment(services.ModelScorecardPath(), "model_scorecard.csv")
}

// GetJournalList returns closed trades for a date or recent N days.
//   ?date=YYYY-MM-DD  → exact date
//   ?days=7           → last N days (default 7 if neither provided)
func GetJournalList(c *gin.Context) {
	if date := c.Query("date"); date != "" {
		trades, err := services.LoadClosedTradesForDate(date)
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"data": []interface{}{}, "error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"data": trades, "date": date})
		return
	}

	daysStr := c.DefaultQuery("days", "7")
	days, err := strconv.Atoi(daysStr)
	if err != nil || days < 1 {
		days = 7
	}
	trades, err := services.LoadClosedTradesRange(days)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": []interface{}{}, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": trades, "days": days})
}

// GetJournalDetail returns a single trade enriched with spot + premium trajectories.
//   ?date=YYYY-MM-DD&time=HH:MM:SS&strike=24100&type=CE
func GetJournalDetail(c *gin.Context) {
	date := c.Query("date")
	entryTime := c.Query("time")
	strike, _ := strconv.ParseFloat(c.Query("strike"), 64)
	optType := c.Query("type")

	if date == "" || entryTime == "" || strike == 0 || optType == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "date, time, strike, type are required"})
		return
	}

	detail, err := services.LoadTradeDetail(date, entryTime, strike, optType)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, detail)
}
