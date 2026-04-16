package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// GetScalperSignal calls the 3-minute scalper LSTM on the Python sidecar
// and returns the signal for the next 3 minutes.
func GetScalperSignal(c *gin.Context) {
	pred, err := services.FetchScalperPrediction()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, pred)
}
