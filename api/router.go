package api

import (
"github.com/gin-gonic/gin"
"spectre/api/handlers"
)

func NewRouter() *gin.Engine {
r := gin.Default()

	// CORS
	r.Use(func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	})

	api := r.Group("/api")
	{
		api.GET("/health",           handlers.GetHealth)
		api.GET("/dashboard",        handlers.GetDashboard)
		api.GET("/market-direction", handlers.GetMarketDirection)
		api.GET("/oi-chain",         handlers.GetOIChain)
		api.GET("/trade-signals",          handlers.GetTradeSignals)
		api.GET("/institutional-outlook",  handlers.GetInstitutionalOutlook)
		api.GET("/stability-state",        handlers.GetStabilityState)
		api.POST("/stability-reset",       handlers.ResetStability)
	}

	return r
}
