package handlers

import (
"net/http"

"github.com/gin-gonic/gin"
"spectre/services"
)

func GetMarketDirection(c *gin.Context) {
result, err := services.ComputeDirection()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, result)
}
