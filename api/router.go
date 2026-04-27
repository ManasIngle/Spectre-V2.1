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
		api.GET("/overnight-prediction", handlers.GetOvernightPrediction)
		api.GET("/overnight-log", handlers.GetOvernightLog)
		api.GET("/option-array/today", handlers.GetOptionArrayToday)
		api.GET("/option-array/download", handlers.DownloadOptionArray)

		// Simulator Mode (sandboxed): shadow trades + per-model scorecard
		api.GET("/simulator/state", handlers.GetSimulatorState)
		api.GET("/simulator/scorecard", handlers.GetModelScorecard)
		api.GET("/simulator/executed/download", handlers.DownloadExecutedTrades)
		api.GET("/simulator/grades/download", handlers.DownloadSignalGrades)
		api.GET("/simulator/scorecard/download", handlers.DownloadModelScorecard)
		api.GET("/simulator/journal", handlers.GetJournalList)
		api.GET("/simulator/journal/detail", handlers.GetJournalDetail)
	}

	return r
}
