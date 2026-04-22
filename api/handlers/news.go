package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// GetNews returns aggregated financial news headlines with sentiment tags.
func GetNews(c *gin.Context) {
	c.JSON(http.StatusOK, services.FetchNews())
}
