package handlers

import (
"net/http"

"github.com/gin-gonic/gin"
"spectre/services"
)

func GetOIChain(c *gin.Context) {
data, err := services.FetchOIChain()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error(), "strikes": []interface{}{}})
		return
	}
	c.JSON(http.StatusOK, data)
}
