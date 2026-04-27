package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

func GetOvernightPrediction(c *gin.Context) {
	pred, err := services.FetchOvernightPrediction()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, pred)
}

func GetOvernightLog(c *gin.Context) {
	limit := 30
	if s := c.Query("limit"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			limit = n
		}
	}
	rows, err := services.FetchOvernightLog(limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, rows)
}

// RefreshOvernightData triggers a background backfill of the parquet + a fresh prediction.
// Returns immediately. Frontend should poll /api/overnight-prediction/status until done.
func RefreshOvernightData(c *gin.Context) {
	out, err := services.RefreshOvernightData()
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, out)
}

// GetOvernightDataStatus returns parquet existence + fetch lifecycle state.
func GetOvernightDataStatus(c *gin.Context) {
	st, err := services.FetchOvernightDataStatus()
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, st)
}
