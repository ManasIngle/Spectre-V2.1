package handlers

import (
"net/http"
"time"

"github.com/gin-gonic/gin"
)

func GetHealth(c *gin.Context) {
c.JSON(http.StatusOK, gin.H{
"status":    "ONLINE",
"timestamp": time.Now().Format(time.RFC3339),
"service":   "Spectre Go",
})
}
