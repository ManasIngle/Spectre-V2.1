package handlers

import (
"net/http"

"github.com/gin-gonic/gin"
"spectre/services"
)

func GetTradeSignals(c *gin.Context) {
sig, err := services.GenerateTradeSignal()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, sig)
}

func GetStabilityState(c *gin.Context) {
	c.JSON(http.StatusOK, services.GetStabilityState())
}

func ResetStability(c *gin.Context) {
	services.ResetStability()
	c.JSON(http.StatusOK, gin.H{"status": "ok", "message": "Stability engine reset"})
}
