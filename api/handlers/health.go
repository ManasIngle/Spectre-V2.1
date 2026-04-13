package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

func GetHealth(c *gin.Context) {
	sidecarOK := false
	if _, err := services.CheckSidecarHealth(); err == nil {
		sidecarOK = true
	}

	status := "DEGRADED"
	if sidecarOK {
		status = "ONLINE"
	}

	c.JSON(http.StatusOK, gin.H{
		"status":     status,
		"sidecar_ok": sidecarOK,
		"timestamp":  time.Now().Format(time.RFC3339),
		"service":    "Spectre Go",
	})
}
