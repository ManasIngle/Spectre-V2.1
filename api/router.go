package api

import (
	"net/http"
	"os"

	"github.com/gin-gonic/gin"
	"spectre/api/handlers"
)

func guardReset(c *gin.Context) {
	key := c.GetHeader("X-Reset-Key")
	expected := os.Getenv("RESET_KEY")
	if key == "" || (expected != "" && key != expected) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid or missing X-Reset-Key"})
		c.Abort()
		return
	}
	c.Next()
}

func NewRouter() *gin.Engine {
	r := gin.Default()

	api := r.Group("/api")
	{
		api.GET("/health", handlers.GetHealth)
		api.GET("/dashboard", handlers.GetDashboard)
		api.GET("/market-direction", handlers.GetMarketDirection)
		api.GET("/oi-chain", handlers.GetOIChain)
		api.GET("/oi-trend", handlers.GetOITrend)
		api.GET("/trade-signals", handlers.GetTradeSignals)
		api.GET("/morning-signal", handlers.GetMorningSignal)
		api.POST("/morning-signal/refresh", handlers.RefreshMorningSignalHandler)
		api.GET("/institutional-outlook", handlers.GetInstitutionalOutlook)
		api.GET("/stability-state", handlers.GetStabilityState)
		api.POST("/stability-reset", guardReset, handlers.ResetStability)
		api.GET("/ml-logs", handlers.GetMLLogs)
		api.GET("/ml-logs/download", handlers.DownloadMLLogs)
		api.GET("/scalper-signal", handlers.GetScalperSignal)
		api.GET("/news", handlers.GetNews)
		api.GET("/heatmap", handlers.GetHeatmap)
	}

	return r
}
