package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

func GetMorningSignal(c *gin.Context) {
	sig, err := services.GetMorningSignal()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, sig)
}

func RefreshMorningSignalHandler(c *gin.Context) {
	go services.RefreshMorningSignal()
	c.JSON(http.StatusOK, gin.H{"status": "refreshing"})
}
