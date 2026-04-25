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
