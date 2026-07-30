package api

import (
	"crypto/subtle"
	"net/http"
	"os"

	"github.com/gin-gonic/gin"
	"spectre/api/handlers"
	"spectre/services"
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

// requireLogsAccess guards the historical-log API. Two ways in:
//
//  1. A valid admin session cookie (so the dashboard/browser works), or
//  2. X-API-Key matching the LOGS_API_KEY env var — for scripts/notebooks that
//     can't carry a session cookie.
//
// Default-deny: if LOGS_API_KEY is unset or empty, the header path is disabled
// entirely and only an admin cookie works. The key is env-only (Dokploy) — it is
// never hardcoded, and the endpoint is never public.
func requireLogsAccess(c *gin.Context) {
	if expected := os.Getenv("LOGS_API_KEY"); expected != "" {
		if key := c.GetHeader("X-API-Key"); key != "" && subtle.ConstantTimeCompare([]byte(key), []byte(expected)) == 1 {
			c.Next()
			return
		}
	}
	// Fall back to the normal admin session path.
	token, err := c.Cookie(services.CookieName())
	if err != nil || token == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "not authenticated (send an admin session cookie, or X-API-Key if LOGS_API_KEY is configured)"})
		c.Abort()
		return
	}
	sess, err := services.ValidateSessionToken(token)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		c.Abort()
		return
	}
	if sess.Role != "admin" {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin role required"})
		c.Abort()
		return
	}
	c.Set("session", sess)
	c.Next()
}

// requireAuth aborts with 401 unless the request has a valid session cookie.
// Stores the session in the gin context as "session" for downstream handlers.
func requireAuth(c *gin.Context) {
	token, err := c.Cookie(services.CookieName())
	if err != nil || token == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "not authenticated"})
		c.Abort()
		return
	}
	sess, err := services.ValidateSessionToken(token)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		c.Abort()
		return
	}
	c.Set("session", sess)
	c.Next()
}

// requireAdmin = requireAuth + role=admin
func requireAdmin(c *gin.Context) {
	v, exists := c.Get("session")
	if !exists {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "not authenticated"})
		c.Abort()
		return
	}
	sess := v.(*services.Session)
	if sess.Role != "admin" {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin role required"})
		c.Abort()
		return
	}
	c.Next()
}

func NewRouter() *gin.Engine {
	r := gin.Default()

	api := r.Group("/api")

	// ─── Public routes (no auth required) ──────────────────────────────────
	api.GET("/health", handlers.GetHealth)
	api.POST("/auth/login", handlers.Login)
	api.POST("/auth/logout", handlers.Logout)
	api.GET("/auth/me", handlers.Me)

	// ─── Historical logs API (admin cookie OR X-API-Key) ──────────────────
	// Serves the full accumulated history for offline analysis, so CSVs don't
	// have to be downloaded and re-uploaded by hand.
	logs := api.Group("/logs")
	logs.Use(requireLogsAccess)
	{
		logs.GET("", handlers.GetLogsManifest)
		logs.GET("/bundle", handlers.GetLogsBundle)
		logs.GET("/:key", handlers.GetLogFile)
	}

	// ─── Authenticated routes (any logged-in user) ────────────────────────
	authed := api.Group("")
	authed.Use(requireAuth)
	{
		authed.GET("/dashboard", handlers.GetDashboard)
		authed.GET("/market-direction", handlers.GetMarketDirection)
		authed.GET("/oi-chain", handlers.GetOIChain)
		authed.GET("/oi-trend", handlers.GetOITrend)
		authed.GET("/trade-signals", handlers.GetTradeSignals)
		authed.GET("/morning-signal", handlers.GetMorningSignal)
		authed.POST("/morning-signal/refresh", handlers.RefreshMorningSignalHandler)
		authed.GET("/institutional-outlook", handlers.GetInstitutionalOutlook)
		authed.GET("/stability-state", handlers.GetStabilityState)
		authed.GET("/scalper-signal", handlers.GetScalperSignal)
		authed.GET("/news", handlers.GetNews)
		authed.GET("/intraday-read", handlers.GetIntradayRead)
		authed.GET("/intraday-read/history", handlers.GetIntradayReadHistory)
		authed.POST("/intraday-read/refresh", handlers.RefreshIntradayRead)
		authed.GET("/heatmap", handlers.GetHeatmap)
		authed.GET("/overnight-prediction", handlers.GetOvernightPrediction)
		authed.POST("/overnight-prediction/refresh", handlers.RefreshOvernightData)
		authed.GET("/overnight-prediction/status", handlers.GetOvernightDataStatus)
		authed.GET("/overnight-log", handlers.GetOvernightLog)
		authed.GET("/option-array/today", handlers.GetOptionArrayToday)
		authed.GET("/simulator/state", handlers.GetSimulatorState)
		authed.GET("/simulator/scorecard", handlers.GetModelScorecard)
		authed.GET("/simulator/journal", handlers.GetJournalList)
		authed.GET("/simulator/journal/detail", handlers.GetJournalDetail)
	}

	// ─── Admin-only routes (CSV downloads, logs, user management) ─────────
	admin := api.Group("")
	admin.Use(requireAuth, requireAdmin)
	{
		admin.GET("/ml-logs", handlers.GetMLLogs)
		admin.GET("/ml-logs/download", handlers.DownloadMLLogs)
		admin.GET("/option-array/download", handlers.DownloadOptionArray)
		admin.GET("/simulator/executed/download", handlers.DownloadExecutedTrades)
		admin.GET("/simulator/grades/download", handlers.DownloadSignalGrades)
		admin.GET("/simulator/scorecard/download", handlers.DownloadModelScorecard)
		admin.POST("/stability-reset", guardReset, handlers.ResetStability)
		admin.GET("/auth/users", handlers.ListUsers)
		admin.POST("/auth/users", handlers.CreateUser)
		admin.DELETE("/auth/users/:username", handlers.DeleteUser)
	}

	return r
}
