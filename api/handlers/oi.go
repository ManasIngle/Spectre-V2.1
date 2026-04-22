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

// GetOITrend returns the intraday OI snapshot history (one entry per NSE refresh).
// Used by the "Trending OI" tab to visualize how PE/CE OI changes evolve across the session.
func GetOITrend(c *gin.Context) {
	// Trigger a fetch in case the cache is cold; result is ignored — we only want the side-effect
	// of appending a snapshot when it succeeds.
	services.FetchOIChain()
	c.JSON(http.StatusOK, gin.H{"snapshots": services.GetOITrend()})
}
