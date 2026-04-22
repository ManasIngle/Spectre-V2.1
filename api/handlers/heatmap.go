package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// GetHeatmap returns LTP + change% for the full NSE equity universe.
func GetHeatmap(c *gin.Context) {
	data, err := services.FetchHeatmap()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error(), "data": []interface{}{}})
		return
	}
	c.JSON(http.StatusOK, data)
}
